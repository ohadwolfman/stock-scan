import pytest

import valuation as v
from fixtures import good_raw
from helpers import check, evaluate


def test_dcf_hand_checked():
    """revenue 100, growth 10%, FCF margin 20%, rate 10%: every year's PV is exactly 20.
    PV(FCF) = 100. Terminal = 32.2102 x 1.04 / 0.06 = 558.3101, PV = 346.6667.
    EV = 446.6667; + cash 50 - debt 0 = 496.6667; / 10 shares = 49.6667."""
    r = v.dcf(100, 0.10, 0.20, 0.10, 50, 0, 10)
    assert [round(f["pv"], 9) for f in r["flows"]] == [20.0] * 5
    assert r["pv_fcf"] == pytest.approx(100.0)
    assert r["terminal"] == pytest.approx(558.310133, rel=1e-6)
    assert r["pv_terminal"] == pytest.approx(346.666667, rel=1e-6)
    assert r["ev"] == pytest.approx(446.666667, rel=1e-6)
    assert r["per_share"] == pytest.approx(49.666667, rel=1e-6)


def test_dcf_debt_subtracted():
    a = v.dcf(100, 0.10, 0.20, 0.10, 50, 0, 10)["per_share"]
    b = v.dcf(100, 0.10, 0.20, 0.10, 50, 30, 10)["per_share"]
    assert a - b == pytest.approx(3.0)


def test_terminal_growth_fixed():
    assert v.TERMINAL_GROWTH == 0.04


def test_reverse_dcf_recovers_growth():
    target = v.dcf(100, 0.07, 0.20, 0.10, 50, 10, 10)["per_share"]
    g, note = v.reverse_dcf(target, 100, 0.20, 0.10, 50, 10, 10)
    assert g == pytest.approx(0.07, abs=1e-6)
    assert note == ""


def test_reverse_dcf_negative_growth_and_bounds():
    target = v.dcf(100, -0.05, 0.20, 0.10, 0, 0, 10)["per_share"]
    g, _ = v.reverse_dcf(target, 100, 0.20, 0.10, 0, 0, 10)
    assert g == pytest.approx(-0.05, abs=1e-6)
    g, note = v.reverse_dcf(1e12, 100, 0.20, 0.10, 0, 0, 10)
    assert g == 5.0 and "below the price" in note
    assert v.reverse_dcf(10, 100, -0.1, 0.10, 0, 0, 10)[0] is None


@pytest.mark.parametrize("peg,label", [(0.99, "undervalued"), (1.0, "fair"), (1.5, "between fair and very expensive"),
                                       (2.0, "between fair and very expensive"), (2.01, "very expensive"),
                                       (None, None)])
def test_peg_labels(peg, label):
    assert v.peg_label(peg) == label


def test_step12_bear_case_decides():
    r = evaluate()
    c = check(r, 12, "bear_case_attractive")
    assert c.status == "PASS"
    raw = good_raw()
    raw["info"]["currentPrice"] = raw["fast"]["last_price"] = 1e6
    r = evaluate(raw)
    assert check(r, 12, "bear_case_attractive").status == "FAIL"


def test_step12_dcf_na_on_negative_fcf_margin():
    raw = good_raw()
    raw["a_cashflow"]["rows"]["Free Cash Flow"] = [-1e9] * 4
    r = evaluate(raw)
    assert check(r, 12, "dcf").value == "N/A"
    # software: falls back to the Rule of 40 multiple
    assert check(r, 12, "valuation_status").status in ("PASS", "FAIL")


def test_step12_unknown_without_dcf_and_peers():
    raw = good_raw()
    raw["a_cashflow"]["rows"]["Free Cash Flow"] = [-1e9] * 4
    man = __import__("fixtures").good_manual()
    man["business_model_type"] = "mature"
    r = evaluate(raw, man)
    assert check(r, 12, "valuation_status").status == "UNKNOWN"
    assert "step8.peers" in r.missing


def test_cross_check_flags_share_mismatch():
    raw = good_raw()
    raw["info"]["sharesOutstanding"] = 3e9  # shares x price = 3x market cap (ADR-like mismatch)
    r = evaluate(raw)
    assert "DISAGREEMENT" in check(r, 12, "cross_check").note


def test_growth_trim_override():
    from fixtures import good_manual
    man = good_manual()
    man["step12"] = {"growth_trim_override": 0.5}
    r = evaluate(None, man)
    g = r.valuation["cases"]["base"]["growth"]
    assert g == pytest.approx(r.valuation["avg_growth"] * 0.5)
