"""Nash 12-step stock screener.

    python nash_screen.py NVDA MSFT
    python nash_screen.py --file tickers.txt
    python nash_screen.py NVDA MSFT --init-manual     # create / extend nash_manual.yaml with hints

Workflow: run on a long list with no manual inputs; most names die at steps 2-3 on the numbers.
Fill the manual file only for the names that come out INCOMPLETE, then run again.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import manual  # noqa: E402
import report  # noqa: E402
import steps  # noqa: E402
from fetch import Fetcher  # noqa: E402
from metrics import Metrics  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass


def parse_tickers(args_tickers, file_path) -> list[str]:
    raw = list(args_tickers or [])
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8")
        text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
        raw += re.split(r"[\s,;]+", text)
    out = []
    for t in raw:
        t = manual.normalize_ticker(t)
        if t and t not in out:
            out.append(t)
    return out


def build_hints(t: str, m: Metrics) -> dict:
    """YAML comments for --init-manual: raw material only, never auto-filled values."""
    i = m.info
    header = [f"{i.get('longName') or t} | {i.get('country')} | {i.get('sector')} | {i.get('industry')}",
              f"first trading date: {m.first_trade_date().value} | auto business model: "
              f"{m.business_model_guess().value} ({m.business_model_guess().source})"]
    officers = i.get("companyOfficers") or []
    if officers:
        header.append("officers: " + "; ".join(f"{o.get('name')} ({o.get('title')}"
                                                f"{', born ' + str(o.get('yearBorn')) if o.get('yearBorn') else ''})"
                                                for o in officers[:6]))
    if i.get("longBusinessSummary"):
        header.append("business summary (raw material for step 4, never auto-filled): " + i["longBusinessSummary"])
    e = steps.earnings_counts(m)
    act = m.insider_activity()
    co, co_src = steps.co_ceo_auto(m)
    s10 = [
        "hints (yfinance):",
        f"  skin_in_the_game: " + (f"{act.value['open_market_purchases']} insider open-market purchases in 12 months, "
                                   f"{act.value['shares_bought']:,.0f} shares bought, {act.value['shares_sold']:,.0f} sold"
                                   if act.ok else "no insider transaction data"),
        f"  consistent_beats (auto, A21): beats {e['beats4']}/{e['n4']} last 4, {e['beats8']}/{e['n8']} last 8",
        f"  co_ceo (auto): {co} from {co_src}",
        f"  acquisition_spree: {steps.acquisition_hint(m)}",
    ]
    ih = steps.insider_hint(m)
    ss = steps.share_sales(m)
    margins = m.annual_margins()
    s11 = [
        "hints (yfinance):",
        f"  insiders_selling_hard (A7 hint): {ih.value} ({ih.note or ih.source})",
        f"  constant share sales (A10): {ss.value} ({ss.note or ss.source})",
        "  operating margin by year: " + ", ".join(f"FY{d[:4]} {v:.1f}%" for d, v in margins),
        "  over-expansion / acquisition spree: use step10.acquisition_spree",
    ]
    return {"header": header, "fields": {"step10": s10, "step11": s11}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tom Nash 12-step stock screener (yfinance)")
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--file", help="tickers file: one per line, or separated by commas or spaces")
    ap.add_argument("--manual", default=config.MANUAL_FILE, help="manual inputs YAML (default nash_manual.yaml)")
    ap.add_argument("--init-manual", action="store_true", help="create or extend the manual file with hints and exit")
    ap.add_argument("--full", action="store_true", help="long per-ticker HTML report instead of the compact ranking")
    ap.add_argument("--refresh", action="store_true", help="ignore today's cache")
    ap.add_argument("--cache-dir", default=config.CACHE_DIR)
    ap.add_argument("--reports-dir", default=config.REPORTS_DIR)
    a = ap.parse_args(argv)

    tickers = parse_tickers(a.tickers, a.file)
    if not tickers:
        ap.error("no tickers given")
    fetcher = Fetcher(a.cache_dir, a.refresh, log=lambda *x: print(*x, file=sys.stderr))

    if a.init_manual:
        hints = {}
        for t in tickers:
            try:
                hints[t] = build_hints(t, Metrics(fetcher.get(t)))
            except Exception as ex:  # one failing ticker never stops the run
                print(f"{t}: hints unavailable ({type(ex).__name__}: {ex})", file=sys.stderr)
        added, updated = manual.init_manual(a.manual, tickers, hints)
        print(f"{a.manual}: {added} tickers added, {updated} refreshed (filled values kept)")
        return 0

    man_all = manual.load(a.manual)
    spy = fetcher.get_history(config.BENCHMARK).get("history") or {}
    if not spy:
        print("warning: SPY history unavailable; scorecard category 7 will be UNKNOWN", file=sys.stderr)
    results, raws, errors = [], {}, {}
    peer_cache: dict = {}
    for n, t in enumerate(tickers, 1):
        print(f"[{n}/{len(tickers)}] {t}", file=sys.stderr)
        try:
            raw = fetcher.get(t)
            raws[t] = raw
            m = Metrics(raw)
            man = manual.Manual(t, man_all.get(t))
            peers = {}
            for p in man.peek("step8.peers") or []:
                p = manual.normalize_ticker(p)
                if p not in peer_cache:
                    try:
                        peer_cache[p] = Metrics(fetcher.get(p))
                    except Exception as ex:
                        print(f"  peer {p}: {type(ex).__name__}: {ex}", file=sys.stderr)
                        peer_cache[p] = None
                peers[p] = peer_cache[p]
            results.append(steps.evaluate(t, m, man, spy, peers))
        except Exception as ex:
            errors[t] = f"{type(ex).__name__}: {ex}"
            print(f"  {t} failed: {errors[t]}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    try:
        import yfinance
        yfv = yfinance.__version__
    except Exception:
        yfv = "n/a"
    meta = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "yfinance": yfv, "tickers": tickers,
            "manual_file": str(a.manual), "spy_points": len(spy)}
    print()
    print(report.console_table(results, errors))
    paths = report.write_all(results, raws, errors, a.reports_dir, meta, full=a.full)
    print()
    for k, p in paths.items():
        print(f"{k}: {p}")
    print(config.DISCLAIMER_HE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
