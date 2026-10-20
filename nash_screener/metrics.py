"""Derived numbers (TTM, growth, margins, ratios). Every result carries its source.

Rules from the spec: never estimate a missing value (a missing input gives value None, which the
steps turn into UNKNOWN); for every metric try an ordered list of yfinance labels and record the
one used; when a definition needs more quarters than yfinance returned, fall back to the matching
info field, then to the annual statements, and record the fallback.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import config


@dataclass
class M:
    """A metric value with provenance. value None = missing (never PASS)."""
    value: object = None
    source: str = ""
    note: str = ""
    assumptions: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.value is not None


# Ordered candidate labels; the first one present (with any value) is used.
LABELS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "net_income": ["Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "cash": ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"],
    "debt": ["Total Debt"],
    "total_assets": ["Total Assets"],
    "goodwill": ["Goodwill"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "equity": ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
    "inventory": ["Inventory"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
    "fcf": ["Free Cash Flow"],
    "ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure"],
    "acquisitions": ["Purchase Of Business", "Net Business Purchase And Sale"],
}
STATEMENT_OF = {
    "revenue": "income", "operating_income": "income", "net_income": "income", "interest_expense": "income",
    "cash": "balance", "debt": "balance", "total_assets": "balance", "goodwill": "balance",
    "total_liabilities": "balance", "current_assets": "balance", "current_liabilities": "balance",
    "equity": "balance", "inventory": "balance", "shares": "balance",
    "fcf": "cashflow", "ocf": "cashflow", "capex": "cashflow", "acquisitions": "cashflow",
}
NON_MONETARY = {"shares"}
# Lines that may be legitimately absent from a filing (A22): absent in every period = not reported.
ABSENT_MEANS_ZERO = {"goodwill", "inventory", "interest_expense", "debt"}


def growth_pct(new, old):
    """(new / old - 1) in %. None when either side is missing or the base is not positive."""
    if new is None or old is None or old <= 0:
        return None
    return (new / old - 1.0) * 100.0


def pct(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den * 100.0


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def consecutive_quarters(dates) -> bool:
    """Newest-first period end dates spaced like consecutive quarters (60-120 days apart)."""
    ds = [_d(x) for x in dates]
    return all(60 <= (a - b).days <= 120 for a, b in zip(ds, ds[1:]))


class Stmt:
    def __init__(self, d: dict, name: str, fx: float = 1.0):
        d = d or {}
        self.name = name
        self.columns = d.get("columns", [])
        self.rows = d.get("rows", {})
        self.fx = fx

    @property
    def empty(self) -> bool:
        return not self.columns or not self.rows

    def find(self, key):
        """(label, [(date, value) newest first, nulls dropped]) or (None, [])."""
        for label in LABELS[key]:
            vals = self.rows.get(label)
            if not vals:
                continue
            pairs = []
            for c, v in zip(self.columns, vals):
                if v is None:
                    continue
                pairs.append((c, v if key in NON_MONETARY else v * self.fx))
            if pairs:
                return label, pairs
        return None, []


class Metrics:
    def __init__(self, raw: dict, today: dt.date | None = None, now: dt.datetime | None = None):
        self.raw = raw
        self.info = raw.get("info") or {}
        self.fast = raw.get("fast") or {}
        self.now = now or dt.datetime.now(dt.timezone.utc)
        self.today = today or self.now.date()
        fxb = raw.get("fx") or {}
        self.fx_block = fxb
        st = fxb.get("statements")
        self.fx_ok, self.fx_rate, self.fx_note = True, 1.0, ""
        if st is not None:
            if st.get("rate") is None:
                self.fx_ok = False
                self.fx_note = (f"FX {st.get('pair')} unavailable: statements stay in "
                                f"{fxb.get('financial_currency')}; per-share and market-cap comparisons are UNKNOWN")
            else:
                self.fx_rate = st["rate"]
                self.fx_note = (f"statements converted {fxb.get('financial_currency')} -> "
                                f"{fxb.get('trading_currency')} at {st['rate']:.6g} ({st.get('pair')}, {st.get('date')})")
        r = self.fx_rate
        self.stmts = {
            ("q", "income"): Stmt(raw.get("q_income"), "quarterly income statement", r),
            ("q", "balance"): Stmt(raw.get("q_balance"), "quarterly balance sheet", r),
            ("q", "cashflow"): Stmt(raw.get("q_cashflow"), "quarterly cash flow", r),
            ("a", "income"): Stmt(raw.get("a_income"), "annual income statement", r),
            ("a", "balance"): Stmt(raw.get("a_balance"), "annual balance sheet", r),
            ("a", "cashflow"): Stmt(raw.get("a_cashflow"), "annual cash flow", r),
        }
        self._memo = {}

    # ------------------------------------------------------------ series
    def series(self, key: str, freq: str = "q") -> M:
        """All non-null values of a line, newest first: M(value=[(date, value), ...])."""
        if key == "fcf":
            return self._fcf_series(freq)
        stmt = self.stmts[(freq, STATEMENT_OF[key])]
        label, pairs = stmt.find(key)
        if label is None:
            if key in ABSENT_MEANS_ZERO and not stmt.empty:
                return M(None, f"{stmt.name}: no {' / '.join(LABELS[key])} line in any period",
                         meta={"absent": True, "columns": stmt.columns})
            return M(None, f"{stmt.name}: none of {LABELS[key]}")
        return M(pairs, f"{stmt.name} '{label}'", meta={"label": label})

    def _fcf_series(self, freq) -> M:
        """FCF = 'Free Cash Flow', fallback operating cash flow minus capital expenditure, per period."""
        stmt = self.stmts[(freq, "cashflow")]
        f_label, f_pairs = stmt.find("fcf")
        o_label, o_pairs = stmt.find("ocf")
        c_label, c_pairs = stmt.find("capex")
        fcf = dict(f_pairs)
        ocf, capex = dict(o_pairs), dict(c_pairs)
        used_fallback = []
        for date in stmt.columns:
            if date not in fcf and date in ocf and date in capex:
                fcf[date] = ocf[date] - abs(capex[date])
                used_fallback.append(date)
        if not fcf:
            return M(None, f"{stmt.name}: no 'Free Cash Flow' and no operating cash flow + capex")
        pairs = sorted(fcf.items(), reverse=True)
        src = f"{stmt.name} '{f_label}'" if f_label else f"{stmt.name} '{o_label}' - '{c_label}'"
        if f_label and used_fallback:
            src += f"; '{o_label}' - '{c_label}' for {', '.join(used_fallback)}"
        return M(pairs, src, meta={"label": f_label or f"{o_label} - {c_label}"})

    def annual(self, key: str, years: int = config.ANNUAL_YEARS) -> M:
        s = self.series(key, "a")
        if not s.ok:
            return s
        return M(s.value[:years], s.source, meta=s.meta)

    def latest(self, key: str) -> M:
        """Latest quarter value, fallback latest annual."""
        q = self.series(key, "q")
        if q.ok:
            d, v = q.value[0]
            return M(v, f"{q.source} @ {d}", meta={"date": d})
        a = self.series(key, "a")
        if a.ok:
            d, v = a.value[0]
            return M(v, f"{a.source} @ {d} (no quarterly value)", meta={"date": d})
        return M(None, q.source, meta=q.meta)

    # ------------------------------------------------------------ TTM
    def ttm(self, key: str, offset: int = 0) -> M:
        """Sum of 4 consecutive quarters. offset 0 = TTM, 4 = prior TTM, 8 = the 4 before that."""
        s = self.series(key, "q")
        if not s.ok:
            return M(None, s.source)
        window = s.value[:offset + 4]
        if len(window) < offset + 4:
            return M(None, s.source, f"needs {offset + 4} quarters, yfinance returned {len(s.value)}")
        if not consecutive_quarters([d for d, _ in window]):
            return M(None, s.source, f"quarters not consecutive: {[d for d, _ in window]}")
        part = window[offset:offset + 4]
        return M(sum(v for _, v in part), f"{s.source}, 4 quarters ending {part[0][0]}",
                 meta={"end": part[0][0]})

    def ttm_or_fallback(self, key: str) -> M:
        """TTM, fallback matching info field, fallback latest annual."""
        t = self.ttm(key)
        if t.ok:
            return t
        info_field = {"revenue": "totalRevenue", "net_income": "netIncomeToCommon"}.get(key)
        if info_field and self.info.get(info_field) is not None:
            return M(self.info[info_field] * self.fx_rate, f"info.{info_field}", f"TTM unavailable ({t.note})")
        a = self.series(key, "a")
        if a.ok:
            d, v = a.value[0]
            return M(v, f"{a.source} FY {d}", f"TTM unavailable ({t.note}); latest fiscal year used")
        return M(None, t.source, t.note)

    # ------------------------------------------------------------ growth and margins
    def _annual_growths(self, key):
        a = self.annual(key)
        if not a.ok:
            return a, []
        v = a.value
        return a, [(v[i][0], growth_pct(v[i][1], v[i + 1][1])) for i in range(len(v) - 1)]

    def revenue_growth(self) -> M:
        if "rev_growth" in self._memo:
            return self._memo["rev_growth"]
        cur, prev = self.ttm("revenue"), self.ttm("revenue", 4)
        g = growth_pct(cur.value, prev.value)
        if g is not None:
            m = M(g, f"TTM vs prior TTM ({cur.source})", meta={"basis": "ttm"})
        elif self.info.get("revenueGrowth") is not None:
            m = M(self.info["revenueGrowth"] * 100, "info.revenueGrowth",
                  f"prior TTM unavailable ({prev.note or prev.source})", meta={"basis": "info"})
        else:
            a, gs = self._annual_growths("revenue")
            if gs and gs[0][1] is not None:
                m = M(gs[0][1], f"latest annual vs previous ({a.source}, FY {gs[0][0]})",
                      "prior TTM and info.revenueGrowth unavailable", meta={"basis": "annual"})
            else:
                m = M(None, "revenue growth: no TTM pair, no info.revenueGrowth, fewer than 2 fiscal years")
        self._memo["rev_growth"] = m
        return m

    def revenue_growth_previous(self) -> M:
        """Previous comparable period's growth, for 'below 10% and falling' (A24)."""
        basis = self.revenue_growth().meta.get("basis")
        if basis == "ttm":
            g = growth_pct(self.ttm("revenue", 4).value, self.ttm("revenue", 8).value)
            if g is not None:
                return M(g, "prior TTM vs the 4 quarters before", assumptions=["A24"])
        a, gs = self._annual_growths("revenue")
        idx = 1 if basis == "annual" else 0
        if len(gs) > idx and gs[idx][1] is not None:
            return M(gs[idx][1], f"annual growth FY {gs[idx][0]} ({a.source})",
                     "fallback to annual" if basis != "annual" else "", assumptions=["A24"])
        return M(None, "previous period growth unavailable", assumptions=["A24"])

    def expense_growth(self) -> M:
        """Expenses = revenue - operating income. TTM vs prior TTM, fallback annual (A24)."""
        r0, r1 = self.ttm("revenue"), self.ttm("revenue", 4)
        o0, o1 = self.ttm("operating_income"), self.ttm("operating_income", 4)
        if all(x.ok for x in (r0, r1, o0, o1)):
            g = growth_pct(r0.value - o0.value, r1.value - o1.value)
            if g is not None:
                return M(g, "TTM vs prior TTM, expenses = revenue - operating income", meta={"basis": "ttm"})
        ra, oa = self.annual("revenue"), self.annual("operating_income")
        if ra.ok and oa.ok:
            om = dict(oa.value)
            exp = [(d, v - om[d]) for d, v in ra.value if d in om]
            if len(exp) >= 2:
                g = growth_pct(exp[0][1], exp[1][1])
                if g is not None:
                    return M(g, f"annual FY {exp[0][0]} vs FY {exp[1][0]}, expenses = revenue - operating income",
                             "prior TTM unavailable", assumptions=["A24"], meta={"basis": "annual"})
        return M(None, "expense growth unavailable (needs 8 quarters or 2 fiscal years of revenue and operating income)")

    def operating_margin(self) -> M:
        rev, op = self.ttm("revenue"), self.ttm("operating_income")
        if rev.ok and op.ok and rev.value:
            return M(pct(op.value, rev.value), f"TTM operating income / TTM revenue ({op.source})")
        if self.info.get("operatingMargins") is not None:
            return M(self.info["operatingMargins"] * 100, "info.operatingMargins", "TTM unavailable")
        ra, oa = self.annual("revenue"), self.annual("operating_income")
        if ra.ok and oa.ok and ra.value[0][0] == oa.value[0][0]:
            return M(pct(oa.value[0][1], ra.value[0][1]), f"annual FY {ra.value[0][0]}", "TTM unavailable")
        return M(None, "operating margin unavailable")

    def prior_ttm_operating_margin(self) -> M:
        rev, op = self.ttm("revenue", 4), self.ttm("operating_income", 4)
        if rev.ok and op.ok and rev.value:
            return M(pct(op.value, rev.value), "prior TTM operating income / prior TTM revenue")
        return M(None, "prior TTM unavailable", rev.note or op.note)

    def quarter_yoy_margins(self) -> M:
        """Latest quarter's operating margin and the same quarter a year earlier (needs 5 quarters)."""
        r, o = self.series("revenue", "q"), self.series("operating_income", "q")
        if not (r.ok and o.ok):
            return M(None, "quarterly revenue / operating income unavailable")
        rd, od = dict(r.value), dict(o.value)
        dates = [d for d, _ in r.value if d in od]
        if len(dates) < 5 or not rd[dates[0]] or not rd[dates[4]]:
            return M(None, "needs 5 quarters of revenue and operating income")
        return M((pct(od[dates[0]], rd[dates[0]]), pct(od[dates[4]], rd[dates[4]]), dates[0], dates[4]),
                 "latest quarter vs the same quarter a year earlier")

    def fcf_margin(self) -> M:
        f, r = self.ttm("fcf"), self.ttm("revenue")
        if f.ok and r.ok and r.value:
            return M(pct(f.value, r.value), f"TTM FCF / TTM revenue ({f.source})")
        fa, ra = self.annual("fcf"), self.annual("revenue")
        if fa.ok and ra.ok and fa.value[0][0] == ra.value[0][0]:
            return M(pct(fa.value[0][1], ra.value[0][1]), f"annual FY {fa.value[0][0]} FCF / revenue",
                     "TTM unavailable")
        return M(None, "FCF margin unavailable")

    def annual_margins(self) -> list:
        """[(date, operating margin %)] newest first, years with both lines."""
        ra, oa = self.annual("revenue"), self.annual("operating_income")
        if not (ra.ok and oa.ok):
            return []
        om = dict(oa.value)
        return [(d, pct(om[d], v)) for d, v in ra.value if d in om and v]

    # ------------------------------------------------------------ per-quarter lists (step 3)
    def per_quarter(self, key) -> M:
        s = self.series(key, "q")
        if not s.ok:
            return s
        return M(s.value[:config.PRESCREEN_MAX_QUARTERS], s.source)

    def net_cash_per_quarter(self) -> M:
        c, d = self.series("cash", "q"), self.series("debt", "q")
        if c.ok and d.meta.get("absent"):  # no debt line in any period: zero debt (A22)
            rows = [(dt_, cv, 0.0) for dt_, cv in c.value][:config.PRESCREEN_MAX_QUARTERS]
            return M(rows, f"{c.source} vs {d.source}", assumptions=["A22"])
        if not (c.ok and d.ok):
            return M(None, f"{c.source}; {d.source}")
        dd = dict(d.value)
        rows = [(dt_, cv, dd[dt_]) for dt_, cv in c.value if dt_ in dd][:config.PRESCREEN_MAX_QUARTERS]
        return M(rows, f"{c.source} vs {d.source}")

    # ------------------------------------------------------------ market data
    def price(self) -> M:
        for src, v in (("fast_info.last_price", self.fast.get("last_price")),
                       ("info.currentPrice", self.info.get("currentPrice")),
                       ("info.regularMarketPrice", self.info.get("regularMarketPrice"))):
            if v:
                return M(v, src)
        hist = self.raw.get("history") or {}
        if hist:
            last = sorted(hist)[-1]
            return M(hist[last], f"last daily close {last}")
        return M(None, "no price")

    def quote_time(self) -> M:
        t = self.info.get("regularMarketTime")
        if isinstance(t, (int, float)):
            return M(dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                     "info.regularMarketTime")
        hist = self.raw.get("history") or {}
        if hist:
            return M(sorted(hist)[-1], "last daily close date")
        return M(None, "no quote time")

    def market_open(self) -> M:
        """A8: regular session in the exchange time zone, Mon-Fri, holidays not modeled."""
        tzname = self.info.get("exchangeTimezoneName") or self.fast.get("timezone") or config.DEFAULT_EXCHANGE_TZ
        try:
            local = self.now.astimezone(ZoneInfo(tzname))
        except Exception:
            tzname = config.DEFAULT_EXCHANGE_TZ
            local = self.now.astimezone(ZoneInfo(tzname))
        hm = (local.hour, local.minute)
        is_open = local.weekday() < 5 and config.MARKET_OPEN_HHMM <= hm < config.MARKET_CLOSE_HHMM
        note = f"marketState={self.info.get('marketState')}" if self.info.get("marketState") else ""
        return M(is_open, f"computed in {tzname}", note, assumptions=["A8"])

    def market_cap(self) -> M:
        for src, v in (("fast_info.market_cap", self.fast.get("market_cap")), ("info.marketCap", self.info.get("marketCap"))):
            if v:
                return M(v, src)
        return M(None, "no market cap")

    def market_cap_usd(self) -> M:
        mc = self.market_cap()
        if not mc.ok:
            return mc
        major = self.fx_block.get("trade_major") or self.info.get("currency") or "USD"
        if major == "USD":
            return mc
        fx = self.fx_block.get("to_usd") or {}
        if fx.get("rate") is None:
            return M(None, f"{mc.source} in {major}; FX {fx.get('pair')} unavailable", assumptions=["A25"])
        return M(mc.value * fx["rate"], f"{mc.source} x {fx['pair']} {fx['rate']:.6g} ({fx.get('date')})",
                 assumptions=["A25"])

    def shares_outstanding(self) -> M:
        for f in ("sharesOutstanding", "impliedSharesOutstanding"):
            if self.info.get(f):
                return M(self.info[f], f"info.{f}")
        s = self.latest("shares")
        return s if s.ok else M(None, "no shares outstanding")

    def short_interest(self) -> M:
        v = self.info.get("shortPercentOfFloat")
        if v is not None:
            return M(v * 100, "info.shortPercentOfFloat")
        sh, fl = self.info.get("sharesShort"), self.info.get("floatShares")
        if sh is not None and fl:
            return M(sh / fl * 100, "info.sharesShort / info.floatShares", "shortPercentOfFloat missing (A26)",
                     assumptions=["A26"])
        return M(None, "info.shortPercentOfFloat")

    def institutional_ownership(self) -> M:
        v = self.info.get("heldPercentInstitutions")
        if v is not None:
            return M(v * 100, "info.heldPercentInstitutions")
        mh = self.raw.get("major_holders") or {}
        if mh.get("institutionsPercentHeld") is not None:
            return M(mh["institutionsPercentHeld"] * 100, "major_holders.institutionsPercentHeld")
        return M(None, "no institutional ownership")

    # ------------------------------------------------------------ returns
    @staticmethod
    def _price_on_or_before(hist: dict, target: dt.date):
        dates = [d for d in hist if _d(d) <= target]
        if not dates:
            return None, None
        d = max(dates)
        if (target - _d(d)).days > 7:
            return None, None
        return d, hist[d]

    def period_return(self, years: float, hist: dict | None = None) -> M:
        hist = hist if hist is not None else (self.raw.get("history") or {})
        if not hist:
            return M(None, "no price history")
        end = max(hist)
        start_target = _d(end) - dt.timedelta(days=round(365.25 * years))
        d0, p0 = self._price_on_or_before(hist, start_target)
        if p0 is None or not p0:
            return M(None, f"history starts {min(hist)}, needs {start_target}")
        return M((hist[end] / p0 - 1) * 100, f"adjusted close {d0} -> {end}", meta={"start": d0, "end": end})

    def five_year_excess(self, spy_hist: dict) -> M:
        """A14: ticker 5-year total return minus SPY's, in percentage points, same dates."""
        t = self.period_return(5)
        if not t.ok:
            return M(None, t.source, assumptions=["A14"])
        hist = self.raw.get("history") or {}
        end = max(hist)
        spy_end = self._price_on_or_before(spy_hist or {}, _d(end))
        spy_start = self._price_on_or_before(spy_hist or {}, _d(t.meta["start"]))
        if spy_end[1] is None or spy_start[1] is None:
            return M(None, "SPY history unavailable for the same dates", assumptions=["A14"])
        spy_ret = (spy_end[1] / spy_start[1] - 1) * 100
        return M(t.value - spy_ret, f"ticker {t.value:.1f}% vs SPY {spy_ret:.1f}% ({t.source})",
                 assumptions=["A14"], meta={"ticker": t.value, "spy": spy_ret})

    # ------------------------------------------------------------ age
    def first_trade_date(self) -> M:
        v = self.raw.get("first_trade_date")
        return M(v, "yfinance history metadata firstTradeDate" if v else "no first trading date")

    def company_age(self, founding_year) -> M:
        """Step 1 startup / step 3 age kill. PASS logic lives in steps; here: years and source."""
        if founding_year:
            return M(self.today.year - int(founding_year), f"manual founding_year {founding_year}")
        ftd = self.first_trade_date()
        if ftd.ok:
            years = (self.today - _d(ftd.value)).days / 365.25
            return M(None, f"founding_year missing; first trading date {ftd.value} ({years:.1f} years ago)",
                     meta={"listed_years": years})
        return M(None, "founding_year missing and no first trading date")

    # ------------------------------------------------------------ earnings
    def reported_earnings(self) -> list:
        """[(date, estimate, reported)] newest first, only quarters already reported with an estimate."""
        rows = (self.raw.get("earnings") or {}).get("rows", [])
        out = []
        for r in rows:
            if r.get("reported") is None or r.get("estimate") is None:
                continue
            if _d(r["date"]) > self.today:
                continue
            out.append((r["date"], r["estimate"], r["reported"]))
        return sorted(out, reverse=True)

    def earnings_source(self) -> str:
        return f"yfinance {(self.raw.get('earnings') or {}).get('source') or 'earnings'}"

    # ------------------------------------------------------------ insiders
    def insider_activity(self, days: int = 365) -> M:
        tx = self.raw.get("insider_transactions") or []
        if not tx:
            return M(None, "no insider transactions")
        cutoff = self.today - dt.timedelta(days=days)
        bought = sold = 0
        n_buy = 0
        for t in tx:
            if not t.get("date") or _d(t["date"]) < cutoff:
                continue
            text = (t.get("text") or "").lower()
            sh = t.get("shares") or 0
            if text.startswith("purchase") or " purchase " in f" {text} ":
                bought += sh
                n_buy += 1
            elif text.startswith("sale"):
                sold += sh
        return M({"open_market_purchases": n_buy, "shares_bought": bought, "shares_sold": sold,
                  "net_sold": sold - bought}, f"yfinance insider_transactions, last {days} days")

    # ------------------------------------------------------------ business model
    def business_model_guess(self) -> M:
        sector = self.info.get("sector") or ""
        industry = self.info.get("industry") or ""
        if "Software" in industry:
            return M("software", f"auto: industry '{industry}'")
        if "Bank" in industry:
            return M("bank", f"auto: industry '{industry}'")
        if any(k in industry for k in config.HARDWARE_INDUSTRY_KEYWORDS):
            return M("hardware", f"auto: industry '{industry}'")
        op = self.ttm_or_fallback("operating_income")
        if op.ok and op.value <= 0:
            return M("early_growth", f"auto: not profitable (operating income {op.value:,.0f})")
        if op.ok:
            return M("mature", f"auto: profitable, sector '{sector}', industry '{industry}'")
        return M(None, "auto-guess impossible: no industry match and no operating income")
