import re
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf


# Optional aliases when Yahoo uses a different ticker symbol than the one in your screen.
YAHOO_ALIAS = {
    "IFX": "IFNNY",
}

# Paste your watchlist here as either a flat list or a grouped text block.
TICKERS = """
A. Mega-cap AI / Cloud:         GOOG, AMZN, MSFT, META, ORCL, NVDA, AAPL
B. Semis & Memory:              MU, MRVL, AMD, AVGO, TSM, ARM, QCOM, NXPI, ASML, LRCX, AMAT, GCTS, WDC, SNDK, ACMR, CAMT
C. Power Semis / Analog:        NVTS, POWI, MPWR, ON, WOLF, IFX, ALGM, SITM
D. Networking & Optics:         ANET, CIEN, COHR, LITE, CRDO, ALAB, CLS, GLW, FN, AAOI, POET, SMTC, AXTI, LPTH, POCI
E. Neocloud / AI Compute:       NBIS, CRWV, APLD, IREN, CORZ, WULF, HIVE, CIFR, BTBT
F. Cooling / Power / Electrical: VRT, ETN, GEV, POWL, NVT, CARR, BE, FLNC, AIRJ, MOD, PWR, HUBB, EME, TLN, XYL
G. Nuclear / Uranium / SMR:     CEG, VST, OKLO, SMR, NNE, LEU, UEC, UUUU, CCJ, BWXT, FLR, NXE
H. Cybersecurity:               CRWD, PANW, ZS, S, FTNT, NET, OKTA, RBRK, TLS
I. Space & New-Space:           RKLB, RDW, LUNR, ASTS, PL, ACHR, JOBY, SIDU, KRMN, BKSY
J. Defense & Defense Tech:      LMT, RTX, NOC, GD, LHX, HII, LDOS, AVAV, KTOS, RCAT, DRS, BBAI, ONDS, VOYG, ampx
   (PLTR also carries heavy defense exposure — see sector N)
K. Robotics / Autonomy:         SERV, TSLA, SYM, PATH, ISRG, AEVA, ARBE, INVZ, AMBA, CEVA, OUST, SOUN, VPG, BOT, AUR, UBER, RR
L. Fintech:                     SOFI, HOOD, COIN, NU, AFRM, UPST, FOUR, PAYO, ALLY, CBOE
M. Quantum:                     IONQ, RGTI, QBTS, QUBT, QNT, INFQ
N. AI Software / Data:          PLTR, SNOW, DDOG, AI, GTLB, MDB, INOD, STX, GRRR
O. Clean Energy / Storage:      FSLR, ENPH, STEM, EOSE, DVN, NRGV, PSIX, P
P. Medical:                     TEM, SENS, DCTH, RXRX, SDGR, CRSP, VOR 
Q. Critical Minerals / Rare Earth: MP, USAR, TMC, UAMY, ARRT, WWR, AREC
R. AI Infra Financing / Private Credit & Data Center REITs: BX, OWL, ARES, KKR, BAM, DLR, EQIX, IRM
S. AI Server OEMs & Hardware Systems: SMCI, DELL, HPE, QMCO
""".strip()


# Edit this list to include more or fewer columns in the future.
OUTPUT_COLUMNS = [
    "Ticker",
    "Sector",
    "Price",
    "Low 5D",
    "High 5D",
    "Chg% 1W",
    "Chg% 1M",
    "% from 52W High",
    "Rel Vol 1D",
    "Rel Vol 5D",
    "RSI(14)",
    "EMA21",
    "EMA50",
    "EMA200",
    "Mkt Cap $B",
    "Cash $B",
    "Debt $B",
    "FCF TTM $B",
    "Rev Growth %",
    "Op Margin %",
    "Short % Float",
    "Inst Own %",
    "Fwd PE",
    "PEG",
    "5Y vs SPY %",
    "Misses 4Q",
]

# This file will be overwritten every time the script runs.
OUTPUT_TEXT_FILE = Path(__file__).resolve().with_name("stock_scan_snapshot.txt")
QUALITY_CACHE_FILE = Path(__file__).resolve().with_name("stock_scan_quality_cache.json")
QUALITY_CACHE_MAX_AGE = timedelta(days=7)
QUALITY_CACHE_INCOMPLETE_MAX_AGE = timedelta(days=1)
QUALITY_COLUMNS = OUTPUT_COLUMNS[-12:]


def compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def get_window_change(series: pd.Series, lookback: int) -> float:
    if len(series) <= lookback:
        return np.nan

    current = float(series.iloc[-1])
    prev = float(series.iloc[-lookback - 1])

    if prev == 0:
        return np.nan

    return ((current / prev) - 1) * 100


def get_relative_volume(volume_series: pd.Series) -> float:
    if volume_series.empty or len(volume_series) < 21:
        return np.nan

    current_volume = float(volume_series.iloc[-1])
    avg_volume = float(volume_series.iloc[-21:-1].mean())

    if avg_volume == 0:
        return np.nan

    return current_volume / avg_volume


def get_weekly_relative_volume(volume_series: pd.Series) -> float:
    # ממוצע נפח 5 הימים האחרונים חלקי ממוצע 20 הימים שלפניהם
    if len(volume_series) < 25:
        return np.nan

    recent = float(volume_series.iloc[-5:].mean())
    prior = float(volume_series.iloc[-25:-5].mean())
    if prior == 0:
        return np.nan
    return recent / prior


def empty_quality_values() -> dict[str, float]:
    return {column: np.nan for column in QUALITY_COLUMNS}


def numeric_value(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def get_monthly_return(ticker: str) -> float:
    try:
        history = yf.Ticker(ticker).history(
            period="5y", interval="1mo", auto_adjust=True, actions=False
        )
        close = history["Close"].dropna()
        if len(close) < 2 or float(close.iloc[0]) == 0:
            return np.nan
        return (float(close.iloc[-1]) / float(close.iloc[0]) - 1) * 100
    except Exception:
        return np.nan


def fetch_quality_values(ticker: str, spy_return: float) -> dict[str, float]:
    values = empty_quality_values()
    stock = yf.Ticker(YAHOO_ALIAS.get(ticker, ticker))

    try:
        info = stock.info
    except Exception:
        info = {}

    for column, key in (
        ("Mkt Cap $B", "marketCap"),
        ("Cash $B", "totalCash"),
        ("Debt $B", "totalDebt"),
        ("FCF TTM $B", "freeCashflow"),
    ):
        value = numeric_value(info.get(key))
        values[column] = value / 1_000_000_000 if not np.isnan(value) else np.nan

    for column, key in (
        ("Rev Growth %", "revenueGrowth"),
        ("Op Margin %", "operatingMargins"),
        ("Short % Float", "shortPercentOfFloat"),
        ("Inst Own %", "heldPercentInstitutions"),
    ):
        value = numeric_value(info.get(key))
        values[column] = value * 100 if not np.isnan(value) else np.nan

    values["Fwd PE"] = numeric_value(info.get("forwardPE"))
    values["PEG"] = numeric_value(info.get("trailingPegRatio"))

    ticker_return = get_monthly_return(YAHOO_ALIAS.get(ticker, ticker))
    if not np.isnan(ticker_return) and not np.isnan(spy_return):
        values["5Y vs SPY %"] = ticker_return - spy_return

    try:
        earnings = stock.get_earnings_dates(limit=12)
        if earnings is not None and not earnings.empty:
            reported = earnings[["Reported EPS", "EPS Estimate"]].dropna()
            reported = reported.sort_index(ascending=False).head(4)
            if len(reported) == 4:
                values["Misses 4Q"] = float(
                    (reported["Reported EPS"] < reported["EPS Estimate"]).sum()
                )
    except Exception:
        pass

    return values


def load_quality_cache() -> dict:
    try:
        with QUALITY_CACHE_FILE.open("r", encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
        return cache if isinstance(cache, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_quality_data(tickers: list[str]) -> tuple[dict[str, dict[str, float]], str | None]:
    now = datetime.now(timezone.utc)
    cache = load_quality_cache()
    fresh_tickers = []
    for ticker in tickers:
        record = cache.get(ticker)
        try:
            fetched_at = datetime.fromisoformat(record["fetched_at"])
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        except (TypeError, KeyError, ValueError):
            fresh_tickers.append(ticker)
            continue
        values = record.get("values", {})
        has_no_values = all(
            np.isnan(numeric_value(values.get(column))) for column in QUALITY_COLUMNS
        )
        max_age = (
            QUALITY_CACHE_INCOMPLETE_MAX_AGE
            if has_no_values
            else QUALITY_CACHE_MAX_AGE
        )
        if now - fetched_at >= max_age:
            fresh_tickers.append(ticker)

    spy_return = get_monthly_return("SPY") if fresh_tickers else np.nan
    for ticker in fresh_tickers:
        old_values = cache.get(ticker, {}).get("values", {})
        values = fetch_quality_values(ticker, spy_return)
        for column in QUALITY_COLUMNS:
            if np.isnan(values[column]):
                previous = numeric_value(old_values.get(column))
                if not np.isnan(previous):
                    values[column] = previous
        cache[ticker] = {
            "fetched_at": now.isoformat(),
            "values": {
                column: None if np.isnan(value) else value
                for column, value in values.items()
            },
        }

    try:
        with QUALITY_CACHE_FILE.open("w", encoding="utf-8") as cache_file:
            json.dump(cache, cache_file, indent=2, allow_nan=False)
    except OSError:
        pass

    result = {}
    cache_dates = []
    for ticker in tickers:
        record = cache.get(ticker, {})
        values = record.get("values", {})
        result[ticker] = {
            column: numeric_value(values.get(column)) for column in QUALITY_COLUMNS
        }
        try:
            cache_dates.append(datetime.fromisoformat(record["fetched_at"]).date())
        except (TypeError, KeyError, ValueError):
            pass

    cache_asof = min(cache_dates).isoformat() if cache_dates else None
    return result, cache_asof


def get_metrics_for_ticker(ticker: str, sector: str = "") -> dict:
    yahoo_ticker = YAHOO_ALIAS.get(ticker, ticker)
    stock = yf.Ticker(yahoo_ticker)
    try:
        hist = stock.history(period="2y", interval="1d", auto_adjust=False, actions=False)
    except Exception:
        hist = pd.DataFrame()

    now_ny = datetime.now(ZoneInfo("America/New_York"))
    if not hist.empty and hist.index[-1].date() == now_ny.date() and now_ny.hour < 16:
        hist = hist.iloc[:-1]

    if hist.empty:
        return {
            "Ticker": ticker,
            "Sector": sector,
            "Price": np.nan,
            "Low 5D": np.nan,
            "High 5D": np.nan,
            "Chg% 1W": np.nan,
            "Chg% 1M": np.nan,
            "% from 52W High": np.nan,
            "Rel Vol 1D": np.nan,
            "Rel Vol 5D": np.nan,
            "RSI(14)": np.nan,
            "EMA21": np.nan,
            "EMA50": np.nan,
            "EMA200": np.nan,
            "_asof": None,
        }

    close = hist["Close"].dropna()
    volume = hist["Volume"].dropna()
    low_5d = float(hist["Low"].tail(5).min()) if "Low" in hist.columns else np.nan
    high_5d = float(hist["High"].tail(5).max()) if "High" in hist.columns else np.nan
    high_52w = float(hist["High"].tail(252).max()) if "High" in hist.columns and not hist.empty else np.nan

    latest_price = float(close.iloc[-1])
    percent_from_52w_high = ((latest_price / high_52w) - 1) * 100 if high_52w else np.nan

    row = {
        "Ticker": ticker,
        "Sector": sector,
        "Price": latest_price,
        "Low 5D": low_5d,
        "High 5D": high_5d,
        "Chg% 1W": get_window_change(close, lookback=5),
        "Chg% 1M": get_window_change(close, lookback=21),
        "% from 52W High": percent_from_52w_high,
        "Rel Vol 1D": get_relative_volume(volume),
        "Rel Vol 5D": get_weekly_relative_volume(volume),
        "RSI(14)": compute_rsi(close, period=14),
        "EMA21": float(close.ewm(span=21, adjust=False).mean().iloc[-1]),
        "EMA50": float(close.ewm(span=50, adjust=False).mean().iloc[-1]),
        "EMA200": float(close.ewm(span=200, adjust=False).mean().iloc[-1]),
        "_asof": hist.index[-1].date(),
    }

    return row


def normalize_ticker(token: str) -> str:
    cleaned = token.strip().upper()
    cleaned = cleaned.replace(".", "")
    cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
    return cleaned


def clean_ticker_list(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        ticker = normalize_ticker(value)
        if not ticker:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        result.append(ticker)
    return result


def parse_grouped_ticker_block(text: str) -> dict[str, list[str]]:
    if not text or not isinstance(text, str):
        return {}

    grouped: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line = re.sub(r"^[\-\*\d\.\s]+", "", line)
        if ":" not in line:
            continue

        left, right = line.split(":", 1)
        left = left.strip()
        if left:
            sector = re.sub(r"^[A-Z]\.?\s*", "", left)
            sector = re.sub(r"\s+", " ", sector).strip()
        else:
            sector = "Unassigned"

        tokens = re.split(r"[\s,]+", right.strip())
        tickers = [normalize_ticker(token) for token in tokens]
        tickers = [ticker for ticker in tickers if ticker]
        if tickers:
            grouped.setdefault(sector, []).extend(tickers)

    return {sector: clean_ticker_list(values) for sector, values in grouped.items()}


def extract_tickers_from_grouped_text(text: str) -> list[str]:
    if not text or not isinstance(text, str):
        return []

    grouped = parse_grouped_ticker_block(text)
    if not grouped:
        tickers = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"\([^)]*\)", "", line)
            if ":" in line:
                _, remainder = line.split(":", 1)
            else:
                remainder = line
            remainder = remainder.replace(",", " ")
            parts = re.split(r"\s+", remainder.strip())
            tickers.extend(parts)
        return clean_ticker_list(tickers)

    flattened = []
    for values in grouped.values():
        flattened.extend(values)
    return clean_ticker_list(flattened)


def extract_tickers_from_universe(universe: dict) -> list[str]:
    values = []
    for sector_items in universe.values():
        if not isinstance(sector_items, str):
            continue
        sector_items = sector_items.replace(",", " ")
        values.extend(re.split(r"\s+", sector_items.strip()))
    return clean_ticker_list(values)


def get_tickers_to_scan() -> list[str]:
    if isinstance(TICKERS, dict):
        return extract_tickers_from_universe(TICKERS)

    if isinstance(TICKERS, str):
        return extract_tickers_from_grouped_text(TICKERS)

    flat_list = []
    for item in TICKERS:
        if isinstance(item, str):
            item = item.strip()
            if not item:
                continue
            if ":" in item or "\n" in item:
                flat_list.extend(extract_tickers_from_grouped_text(item))
            else:
                flat_list.append(normalize_ticker(item))
    return clean_ticker_list(flat_list)


def scan_tickers(tickers: list[str], sector_map: dict[str, str] | None = None) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        sector = sector_map.get(ticker, "") if sector_map else ""
        rows.append(get_metrics_for_ticker(ticker, sector=sector))

    quality_data, quality_asof = get_quality_data(tickers)
    for row in rows:
        row.update(quality_data.get(row["Ticker"], empty_quality_values()))

    df = pd.DataFrame(rows)
    df = df[OUTPUT_COLUMNS + ["_asof"]]
    df = df.sort_values("Ticker").reset_index(drop=True)
    df.attrs["quality_asof"] = quality_asof
    return df


def format_value_for_display(value, column_name: str):
    if pd.isna(value):
        return "-"
    if column_name in {"Rel Vol 1D", "Rel Vol 5D"}:
        return f"{value:.2f}x"
    if column_name in {"Price", "Low 5D", "High 5D", "RSI(14)", "EMA21", "EMA50", "EMA200"}:
        return f"{value:.2f}"
    if column_name in {
        "Chg% 1W", "Chg% 1M", "% from 52W High", "Rev Growth %",
        "Op Margin %", "Short % Float", "Inst Own %", "5Y vs SPY %",
    }:
        return f"{value:.2f}%"
    if column_name in QUALITY_COLUMNS:
        return f"{value:.2f}"
    return str(value)


def write_text_snapshot(df: pd.DataFrame, file_path: str = OUTPUT_TEXT_FILE, snapshot_date: str | None = None, missing_tickers: list[str] | None = None) -> None:
    formatted = df.drop(columns=["_asof"]).copy()
    for col in formatted.columns:
        if col in {"Ticker", "Sector"}:
            continue
        formatted[col] = formatted[col].map(lambda value: format_value_for_display(value, col))

    header_line = f"Spot data as of {snapshot_date}" if snapshot_date is not None else "Spot data"
    quality_asof = df.attrs.get("quality_asof")
    if quality_asof is not None:
        header_line += f" | Quality data cache refreshed {quality_asof}"
    missing_text = ", ".join(missing_tickers) if missing_tickers else "none"
    table_text = formatted.to_csv(sep="\t", index=False, lineterminator="\n").rstrip("\n")
    snapshot_text = f"{header_line}\n{table_text}\nMissing data tickers: {missing_text}\n"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(snapshot_text)


def build_sector_map() -> dict[str, str]:
    if isinstance(TICKERS, str):
        mapping = {}
        grouped = parse_grouped_ticker_block(TICKERS)
        for sector, tickers in grouped.items():
            for ticker in tickers:
                mapping[ticker] = sector
        return mapping

    if isinstance(TICKERS, list):
        return {}

    return {}


if __name__ == "__main__":
    tickers = get_tickers_to_scan()
    if not tickers:
        raise ValueError("No tickers found. Check TICKERS, GROUPED_TICKERS, or UNIVERSE input.")

    sector_map = build_sector_map()
    df = scan_tickers(tickers, sector_map)
    snapshot_date = df["_asof"].dropna().max() if "_asof" in df.columns and not df["_asof"].dropna().empty else None

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)

    missing = df.loc[df["Price"].isna(), "Ticker"].tolist()
    header_line = f"Spot data as of {snapshot_date}" if snapshot_date is not None else "Spot data"
    quality_asof = df.attrs.get("quality_asof")
    if quality_asof is not None:
        header_line += f" | Quality data cache refreshed {quality_asof}"

    display_df = df.drop(columns=["_asof"]).copy()
    for col in display_df.columns:
        if col in {"Ticker", "Sector"}:
            continue
        display_df[col] = display_df[col].map(lambda value: format_value_for_display(value, col))

    missing_text = ", ".join(missing) if missing else "none"
    snapshot_text = f"{header_line}\n{display_df.to_csv(sep='\t', index=False, lineterminator='\n').rstrip(chr(10))}\nMissing data tickers: {missing_text}\n"
    print(snapshot_text, end="")

    write_text_snapshot(df, OUTPUT_TEXT_FILE, snapshot_date, missing)
    print(f"Saved snapshot to: {OUTPUT_TEXT_FILE}")
