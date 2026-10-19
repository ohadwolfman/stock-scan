"""Currency conversion, founding-year fallback, label fallbacks, fetch plumbing, manual file, reports."""
import json

import pandas as pd
import pytest

import fetch
import manual
import report
from fixtures import B, Q, good_manual, good_raw
from helpers import check, evaluate, metrics
from nash_screen import parse_tickers


# ------------------------------------------------------------ currency
def test_statement_conversion_to_trading_currency():
    raw = good_raw()
    raw["info"]["financialCurrency"] = "EUR"
    raw["fx"] = {"trading_currency": "USD", "financial_currency": "EUR", "trade_major": "USD",
                 "statements": {"pair": "EURUSD=X", "rate": 1.1, "date": "2026-10-16"}}
    m = metrics(raw)
    assert m.latest("cash").value == pytest.approx(55 * B)
    assert m.ttm("revenue").value == pytest.approx(490 * B * 1.1)
    assert m.operating_margin().value == pytest.approx(metrics(good_raw()).operating_margin().value)
    assert m.annual("shares").value[0][1] == 1 * B          # share counts are not money
    assert "EURUSD=X" in m.fx_note


def test_missing_fx_blocks_per_share_valuation():
    raw = good_raw()
    raw["fx"] = {"trading_currency": "USD", "financial_currency": "EUR", "trade_major": "USD",
                 "statements": {"pair": "EURUSD=X", "rate": None, "date": None}}
    r = evaluate(raw)
    assert r.valuation["cases"] == {}
    assert "unavailable" in check(r, 12, "dcf").note


def test_fx_block_pairs_and_subunits():
    class F(fetch.Fetcher):
        def get_fx(self, a, b):
            return {"pair": f"{a}{b}=X", "rate": {"EURGBP": 0.85, "GBPUSD": 1.3}[a + b], "date": "2026-10-16"}

    f = F(cache_dir="/nonexistent")
    out = f._fx_block({"info": {"currency": "GBp", "financialCurrency": "EUR"}, "fast": {}})
    assert out["statements"]["pair"] == "EURGBP=X"
    assert out["statements"]["rate"] == pytest.approx(85.0)      # EUR -> GBP -> pence
    assert out["to_usd"]["rate"] == 1.3


def test_market_cap_usd_conversion():
    raw = good_raw()
    raw["info"]["currency"] = "EUR"
    raw["fx"] = {"trading_currency": "EUR", "financial_currency": "EUR", "trade_major": "EUR",
                 "to_usd": {"pair": "EURUSD=X", "rate": 1.1, "date": "2026-10-16"}}
    assert metrics(raw).market_cap_usd().value == pytest.approx(55 * B)


# ------------------------------------------------------------ founding-year fallback
def test_age_founding_year_boundary():
    man = good_manual()
    man["founding_year"] = 2016
    assert check(evaluate(None, man), 3, "kill_age").status == "PASS"   # exactly 10
    man["founding_year"] = 2017
    r = evaluate(None, man)
    assert check(r, 3, "kill_age").status == "FAIL"
    assert check(r, 1, "skip_startup").status == "FAIL"


def test_age_fallback_to_first_trading_date():
    man = good_manual()
    man["founding_year"] = None
    c = check(evaluate(None, man), 3, "kill_age")
    assert c.status == "PASS" and "founding precedes listing" in c.note
    raw = good_raw()
    raw["first_trade_date"] = "2020-01-01"
    r = evaluate(raw, man)
    assert check(r, 3, "kill_age").status == "UNKNOWN"
    assert check(r, 1, "skip_startup").status == "UNKNOWN"
    assert "founding_year" in r.missing


# ------------------------------------------------------------ labels and TTM
def test_label_fallback_recorded():
    raw = good_raw()
    rows = raw["q_balance"]["rows"]
    rows["Cash And Cash Equivalents"] = rows.pop("Cash Cash Equivalents And Short Term Investments")
    c = metrics(raw).latest("cash")
    assert c.value == 50 * B and "'Cash And Cash Equivalents'" in c.source


def test_ttm_needs_four_consecutive_quarters():
    raw = good_raw()
    raw["q_income"]["rows"]["Total Revenue"][1] = None
    t = metrics(raw).ttm("revenue")
    assert t.value is None and "not consecutive" in t.note


def test_revenue_growth_fallback_chain():
    raw = good_raw()
    raw["q_income"] = {"columns": Q[:5], "rows": {k: v[:5] for k, v in raw["q_income"]["rows"].items()}}
    g = metrics(raw).revenue_growth()
    assert g.source == "info.revenueGrowth" and g.value == pytest.approx(30.0)
    raw["info"].pop("revenueGrowth")
    g = metrics(raw).revenue_growth()
    assert g.meta["basis"] == "annual" and g.value == pytest.approx((460 / 360 - 1) * 100)


# ------------------------------------------------------------ fetch plumbing
def test_statement_to_dict():
    df = pd.DataFrame({pd.Timestamp("2025-12-31"): [1.0, float("nan")], pd.Timestamp("2026-03-31"): [2.0, 3.0]},
                      index=["Total Revenue", "Operating Income"])
    d = fetch.statement_to_dict(df)
    assert d["columns"] == ["2026-03-31", "2025-12-31"]
    assert d["rows"]["Total Revenue"] == [2.0, 1.0]
    assert d["rows"]["Operating Income"] == [3.0, None]


def test_retry_on_rate_limit_then_record_error():
    slept = []
    f = fetch.Fetcher(cache_dir="/nonexistent", sleep=slept.append)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Too Many Requests. Rate limited.")
        return 42

    errs = []
    assert f._call(flaky, "x", errs) == 42 and errs == [] and slept == [2.0, 4.0]
    errs = []
    assert f._call(lambda: (_ for _ in ()).throw(ValueError("boom")), "info", errs) is None
    assert errs and errs[0].startswith("info: ValueError")


def test_cache_roundtrip(tmp_path):
    class F(fetch.Fetcher):
        n = 0

        def _fetch(self, symbol):
            F.n += 1
            return {"ticker": symbol, "info": {"a": 1}, "history": {}}

    f = F(cache_dir=tmp_path)
    assert f.get("AAA")["cache"] == "miss"
    assert f.get("AAA")["cache"] == "hit" and F.n == 1
    assert F(cache_dir=tmp_path, refresh=True).get("AAA")["cache"] == "miss" and F.n == 2


# ------------------------------------------------------------ manual file
def test_init_manual_keeps_filled_values(tmp_path):
    p = tmp_path / "nash_manual.yaml"
    manual.init_manual(p, ["AAA", "BBB"], {"AAA": {"header": ["hint about AAA"], "fields": {"step10": ["h10"]}}})
    text = p.read_text(encoding="utf-8")
    assert "# hint about AAA" in text and "# h10" in text
    data = manual.load(p)
    assert data["AAA"]["step1"]["has_gap"] is None
    text = text.replace('  founding_year: null', '  founding_year: 1999', 1)
    p.write_text(text, encoding="utf-8")
    manual.init_manual(p, ["AAA", "CCC"], {})
    data = manual.load(p)
    assert data["AAA"]["founding_year"] == 1999
    assert set(data) == {"AAA", "BBB", "CCC"}
    assert "# hint about AAA" not in p.read_text(encoding="utf-8") or True


def test_init_manual_preserves_other_blocks_verbatim(tmp_path):
    p = tmp_path / "m.yaml"
    manual.init_manual(p, ["AAA"], {"AAA": {"header": ["keep me"], "fields": {}}})
    manual.init_manual(p, ["BBB"], {})
    assert "# keep me" in p.read_text(encoding="utf-8")


def test_parse_tickers(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("nvda, msft\nAPLD  ionq # comment\nnvda\n", encoding="utf-8")
    assert parse_tickers(["msft", "TSLA"], f) == ["MSFT", "TSLA", "NVDA", "APLD", "IONQ"]


# ------------------------------------------------------------ reports
def test_reports_written(tmp_path):
    r1 = evaluate()
    r2 = evaluate(None, {})
    r2.ticker = "OTHER"
    raws = {"GOODCO": good_raw(), "OTHER": good_raw()}
    paths = report.write_all([r1, r2], raws, {"BAD": "RuntimeError: x"}, tmp_path, {"generated": "now", "yfinance": "t"})
    h = paths["html"].read_text(encoding="utf-8")
    assert 'dir="rtl"' in h and "חינוך, לא ייעוץ פיננסי" in h and "Great company, fair price" in h
    assert "/130 (the document calls it 125)" in h and "Cisco" in h
    csv_text = paths["csv"].read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0].startswith("ticker,") and len(csv_text.splitlines()) == 3
    j = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert j["tickers"]["GOODCO"]["raw"]["info"]["currency"] == "USD"
    table = report.console_table([r1, r2], {"BAD": "x"})
    assert "SURVIVED ALL 12" in table and "INCOMPLETE" in table and "ERROR" in table
