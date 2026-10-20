import pytest

import manual
import scorecard as sc
from fixtures import SPY, good_manual, good_raw
from helpers import metrics


@pytest.mark.parametrize("cash,debt,pts", [(10, 10, 0), (9, 10, 0), (10.01, 10, 5), (19.99, 10, 5), (20, 10, 10),
                                           (25, 10, 10), (1, 0, 10), (0, 0, 0)])
def test_cash_vs_debt(cash, debt, pts):
    assert sc.score_cash_debt(cash, debt) == pts


@pytest.mark.parametrize("v,pts", [(9.99, 0), (10, 5), (15, 5), (20, 5), (20.01, 10), (10.0000000001, 5)])
def test_revenue_growth_bands(v, pts):
    assert sc.score_revenue_growth(v) == pts


@pytest.mark.parametrize("v,pts", [(9.99, 0), (10, 5), (25, 5), (25.01, 10)])
def test_operating_margin_bands(v, pts):
    assert sc.score_operating_margin(v) == pts


@pytest.mark.parametrize("v,pts", [(4.99, 10), (5, 5), (10, 5), (10.01, 0)])
def test_short_interest_bands(v, pts):
    assert sc.score_short_interest(v) == pts


@pytest.mark.parametrize("v,pts", [(29.99, 0), (30, 5), (60, 5), (60.01, 10)])
def test_institutional_bands(v, pts):
    assert sc.score_institutional(v) == pts


@pytest.mark.parametrize("v,pts", [(-5, 0), (0, 0), (9.99, 0), (10, 5), (19.99, 5), (20, 10), (35, 10)])
def test_five_year_bands(v, pts):
    """A13: 0-10 points = 0; 20 exactly = 10 (overlap resolved upward)."""
    assert sc.score_five_year(v) == pts


def test_scalability():
    assert sc.score_scalability(25, 13) == 10
    assert sc.score_scalability(10, 10) == 0
    assert sc.score_scalability(120, 250) == 0


def test_missing_values_are_none_not_zero():
    for f in (sc.score_revenue_growth, sc.score_operating_margin, sc.score_short_interest,
              sc.score_institutional, sc.score_five_year):
        assert f(None) is None
    assert sc.score_cash_debt(None, 1) is None


@pytest.mark.parametrize("total,band", [(74, "Absolute no-go"), (75, "Watchlist. Investable."),
                                        (99, "Watchlist. Investable."), (100, "Exceptional. Once in a lifetime."),
                                        (130, "Exceptional. Once in a lifetime.")])
def test_bands(total, band):
    assert sc.band(total) == band


def _compute(man_over):
    mm = good_manual()
    mm["step6"] = man_over
    return sc.compute(metrics(good_raw()), manual.Manual("GOODCO", mm), SPY)


def test_min_max_with_missing_manual_scores():
    full = _compute({"moat": 10, "ceo": 10, "recession_proof_pricing_power": 10, "secular_trend": 10,
                     "culture_mission": 10, "talent": 10})
    assert full["complete"]
    computed = full["computed"]
    partial = _compute({"moat": 0, "ceo": None, "recession_proof_pricing_power": None, "secular_trend": 5,
                        "culture_mission": None, "talent": None})
    assert partial["computed"] == computed
    assert partial["manual"] == 5
    assert partial["min"] == computed + 5
    assert partial["max"] == computed + 5 + 40
    assert not partial["complete"]


def test_step6_status_from_range():
    # computed part of the fixture is 70 (7 categories x 10); range decides
    none = _compute({k: None for k in manual.SCORE_FIELDS})
    assert none["computed"] == 70
    assert none["status"] == "PASS"             # empty manual scores are ignored, bar scaled to 7 categories (A28)
    low = _compute({"moat": 0, "ceo": 0, "recession_proof_pricing_power": 0, "secular_trend": 0,
                    "culture_mission": None, "talent": None})
    assert low["max"] == 90 and low["status"] == "PASS"
    zero = _compute({k: 0 for k in manual.SCORE_FIELDS})
    assert zero["min"] == 70 and zero["status"] == "FAIL"
    five = _compute({"moat": 5, "ceo": None, "recession_proof_pricing_power": None, "secular_trend": None,
                     "culture_mission": None, "talent": None})
    assert five["min"] == 75 and five["status"] == "PASS"


def test_step6_fail_when_max_below_75():
    raw = good_raw()
    raw["info"]["shortPercentOfFloat"] = 0.2          # 0
    raw["info"]["heldPercentInstitutions"] = 0.1      # 0
    raw["q_balance"]["rows"]["Total Debt"] = [60e9] * 8  # 0
    mm = good_manual()
    mm["step6"] = {k: 0 for k in manual.SCORE_FIELDS}
    mm["step6"]["moat"] = None
    r = sc.compute(metrics(raw), manual.Manual("X", mm), SPY)
    assert r["max"] < 75 and r["status"] == "FAIL"
