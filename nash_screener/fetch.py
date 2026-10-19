"""yfinance access: one JSON-serialisable raw dict per ticker, cached per day, with retries and FX.

Everything downstream (metrics, steps, reports) reads only this raw dict, so a cached run and a
fresh run go through exactly the same code.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
from pathlib import Path

import config

try:  # imported lazily so the unit tests run without network or yfinance installed
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None


def _clean(v):
    """numpy / pandas scalars and NaN to plain JSON values."""
    if v is None:
        return None
    if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (int, float, str, bool)):
        return v
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except (TypeError, ValueError, ImportError):
        pass
    return str(v)


def _clean_tree(obj):
    if isinstance(obj, dict):
        return {str(k): _clean_tree(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_tree(v) for v in obj]
    return _clean(obj)


def statement_to_dict(df) -> dict:
    """yfinance statement DataFrame (rows = labels, columns = period ends) to
    {"columns": [iso dates newest first], "rows": {label: [values aligned to columns]}}."""
    if df is None or getattr(df, "empty", True):
        return {"columns": [], "rows": {}}
    cols = sorted(df.columns, reverse=True)
    df = df[cols]
    rows = {}
    for label, row in df.iterrows():
        rows.setdefault(str(label), [_clean(v) for v in row.tolist()])  # first occurrence wins
    return {"columns": [str(c.date()) if hasattr(c, "date") else str(c) for c in cols], "rows": rows}


class Fetcher:
    def __init__(self, cache_dir=config.CACHE_DIR, refresh=False, log=print, sleep=time.sleep):
        self.cache_dir = Path(cache_dir)
        self.refresh = refresh
        self.log = log
        self.sleep = sleep
        self.today = dt.date.today().isoformat()

    # ------------------------------------------------------------ plumbing
    def _call(self, fn, what, errors):
        """Run one yfinance call with backoff on rate limits. Never raises."""
        for attempt in range(config.RETRY_ATTEMPTS):
            try:
                return fn()
            except Exception as e:  # yfinance raises many types; one failure must not stop the run
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                rate_limited = "RateLimit" in type(e).__name__ or "Too Many Requests" in str(e) \
                    or "429" in str(e)
                if attempt < config.RETRY_ATTEMPTS - 1 and (rate_limited or attempt == 0):
                    self.sleep(config.RETRY_BASE_SECONDS * (2 ** attempt))
                    continue
                errors.append(f"{what}: {msg}")
                return None
        return None

    def _cache_path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.cache_dir / f"{safe}_{self.today}.json"

    def _load_cache(self, key):
        p = self._cache_path(key)
        if self.refresh or not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _save_cache(self, key, data):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------ public
    def get(self, symbol: str) -> dict:
        cached = self._load_cache(symbol)
        if cached is not None:
            cached["cache"] = "hit"
            return cached
        raw = self._fetch(symbol)
        if raw.get("info") or raw.get("history"):
            self._save_cache(symbol, raw)  # do not cache a total failure
        raw["cache"] = "miss"
        return raw

    def get_history(self, symbol: str) -> dict:
        """Adjusted daily closes only (used for the benchmark)."""
        key = f"HIST_{symbol}"
        cached = self._load_cache(key)
        if cached is not None:
            return cached
        errors = []
        t = yf.Ticker(symbol)
        hist = self._call(lambda: t.history(period=config.HISTORY_PERIOD, auto_adjust=True), "history", errors)
        data = {"symbol": symbol, "history": _series_to_dict(hist), "errors": errors,
                "fetched_at": _now_iso()}
        if data["history"]:
            self._save_cache(key, data)
        return data

    def get_fx(self, from_cur: str, to_cur: str) -> dict:
        """Rate to multiply an amount in from_cur to get to_cur, via the yfinance pair FROMTO=X."""
        if from_cur == to_cur:
            return {"pair": None, "rate": 1.0, "date": None}
        pair = f"{from_cur}{to_cur}=X"
        cached = self._load_cache(f"FX_{pair}")
        if cached is not None:
            return cached
        errors = []
        t = yf.Ticker(pair)
        hist = self._call(lambda: t.history(period="5d"), f"fx {pair}", errors)
        series = _series_to_dict(hist)
        if not series:
            return {"pair": pair, "rate": None, "date": None, "errors": errors}
        last = sorted(series)[-1]
        data = {"pair": pair, "rate": series[last], "date": last, "errors": errors}
        self._save_cache(f"FX_{pair}", data)
        return data

    # ------------------------------------------------------------ the raw dict
    def _fetch(self, symbol: str) -> dict:
        if yf is None:
            raise RuntimeError("yfinance is not installed (pip install -r requirements.txt)")
        errors: list[str] = []
        t = yf.Ticker(symbol)
        raw: dict = {"ticker": symbol, "fetched_at": _now_iso(), "errors": errors}

        info = self._call(t.get_info, "info", errors) or {}
        raw["info"] = _clean_tree(info)
        hist = self._call(lambda: t.history(period=config.HISTORY_PERIOD, auto_adjust=True), "history", errors)
        raw["history"] = _series_to_dict(hist)
        if not info and not raw["history"]:
            errors.append("no info and no price history: remaining yfinance calls skipped")
            return raw

        fast = {}
        fi = self._call(lambda: t.fast_info, "fast_info", errors)
        if fi is not None:
            for attr in ("last_price", "market_cap", "currency", "timezone", "exchange"):
                fast[attr] = _clean(self._call(lambda a=attr: getattr(fi, a), f"fast_info.{attr}", []))
        raw["fast"] = fast

        for key, getter in (("q_income", lambda: t.quarterly_income_stmt),
                            ("q_balance", lambda: t.quarterly_balance_sheet),
                            ("q_cashflow", lambda: t.quarterly_cashflow),
                            ("a_income", lambda: t.income_stmt),
                            ("a_balance", lambda: t.balance_sheet),
                            ("a_cashflow", lambda: t.cashflow)):
            raw[key] = statement_to_dict(self._call(getter, key, errors))

        raw["earnings"] = self._earnings(t, errors)
        raw["insider_transactions"] = self._insider_transactions(t, errors)
        raw["insider_purchases"] = self._two_col(self._call(lambda: t.insider_purchases, "insider_purchases",
                                                            errors), value_col="Shares")
        raw["major_holders"] = self._two_col(self._call(lambda: t.major_holders, "major_holders", errors),
                                             value_col="Value", use_index=True)
        raw["growth_estimates"] = self._growth_estimates(t, errors)

        meta =self._call(t.get_history_metadata, "history_metadata", errors) or {}
        first = meta.get("firstTradeDate") if isinstance(meta, dict) else None
        raw["first_trade_date"] = _epoch_or_date(first) or _epoch_or_date(info.get("firstTradeDateMilliseconds"),
                                                                          ms=True)
        raw["fx"] = self._fx_block(raw)
        return raw

    def _earnings(self, t, errors) -> dict:
        """Reported vs estimated EPS, newest first. Primary: earnings dates; fallback: earnings history."""
        rows = []
        df = self._call(lambda: t.get_earnings_dates(limit=config.EARNINGS_DATES_LIMIT), "earnings_dates", errors)
        if df is not None and not df.empty:
            for idx, r in df.iterrows():
                if "Event Type" in df.columns and str(r.get("Event Type")) not in ("Earnings", "nan", "None"):
                    continue
                rows.append({"date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                             "estimate": _clean(r.get("EPS Estimate")), "reported": _clean(r.get("Reported EPS"))})
            if rows:
                return {"source": "get_earnings_dates", "rows": sorted(rows, key=lambda x: x["date"], reverse=True)}
        df = self._call(lambda: t.earnings_history, "earnings_history", errors)
        if df is not None and not df.empty:
            for idx, r in df.iterrows():
                rows.append({"date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                             "estimate": _clean(r.get("epsEstimate")), "reported": _clean(r.get("epsActual"))})
            return {"source": "earnings_history", "rows": sorted(rows, key=lambda x: x["date"], reverse=True)}
        return {"source": None, "rows": []}

    def _insider_transactions(self, t, errors) -> list:
        df = self._call(lambda: t.insider_transactions, "insider_transactions", errors)
        if df is None or df.empty:
            return []
        out = []
        for _, r in df.iterrows():
            out.append({"date": _clean(r.get("Start Date")), "shares": _clean(r.get("Shares")),
                        "value": _clean(r.get("Value")), "text": _clean(r.get("Text")),
                        "transaction": _clean(r.get("Transaction")), "insider": _clean(r.get("Insider")),
                        "position": _clean(r.get("Position"))})
        return out

    @staticmethod
    def _two_col(df, value_col, use_index=False) -> dict:
        if df is None or df.empty:
            return {}
        out = {}
        for idx, r in df.iterrows():
            key = idx if use_index else r.iloc[0]
            out[str(key)] = _clean(r.get(value_col)) if value_col in df.columns else _clean(r.iloc[-1])
        return out

    def _growth_estimates(self, t, errors) -> dict:
        df = self._call(lambda: t.growth_estimates, "growth_estimates", errors)
        if df is None or df.empty:
            return {}
        col = next((c for c in df.columns if "stock" in str(c).lower()), df.columns[0])
        return {"column": str(col), "values": {str(i): _clean(v) for i, v in df[col].items()}}

    def _fx_block(self, raw) -> dict:
        """Rates needed: statements -> trading currency, and trading currency -> USD (A25)."""
        info = raw["info"]
        trade = info.get("currency") or raw["fast"].get("currency")
        fin = info.get("financialCurrency") or trade
        out = {"trading_currency": trade, "financial_currency": fin}
        if not trade:
            return out
        trade_major, factor = config.CURRENCY_SUBUNITS.get(trade, (trade, 1))
        out["trade_major"], out["subunit_factor"] = trade_major, factor
        if fin and fin != trade:
            fx = self.get_fx(fin, trade_major) if fin != trade_major else {"pair": None, "rate": 1.0, "date": None}
            out["statements"] = dict(fx, rate=(fx["rate"] * factor if fx.get("rate") is not None else None))
        if trade_major != "USD":
            out["to_usd"] = self.get_fx(trade_major, "USD")
        return out


def _series_to_dict(hist) -> dict:
    if hist is None or getattr(hist, "empty", True) or "Close" not in hist:
        return {}
    return {str(i.date()): _clean(v) for i, v in hist["Close"].items() if _clean(v) is not None}


def _epoch_or_date(v, ms=False):
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return dt.datetime.fromtimestamp(v / 1000 if ms else v, tz=dt.timezone.utc).date().isoformat()
        return str(v)[:10]
    except (OverflowError, OSError, ValueError):
        return None


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
