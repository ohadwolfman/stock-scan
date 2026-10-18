"""Every document threshold at its boundary, through the real step code."""
import pytest

import config
import steps
from fixtures import B, Q, daily, good_manual, good_raw
from helpers import check, evaluate, metrics
from metrics import M


# ------------------------------------------------------------ generic comparator
@pytest.mark.parametrize("v,op,thr,st", [(40, ">=", 40, "PASS"), (39.99, ">=", 40, "FAIL"),
                                         (10.0000000001, ">=", 10, "PASS"), (4, "<", 4, "FAIL"),
                                         (3.99, "<", 4, "PASS"), (10, "<=", 10, "PASS"), (0, ">", 0, "FAIL")])
def test_num_check(v, op, thr, st):
    assert steps.num_check("x", "x", M(v, "s"), op, thr).status == st


def test_num_check_missing_is_unknown():
    assert steps.num_check("x", "x", M(None, "s"), ">=", 1).status == "UNKNOWN"


# ------------------------------------------------------------ step 3
def test_operating_margin_20_boundary():
    raw = good_raw()
    rev = raw["q_income"]["rows"]["Total Revenue"]
    raw["q_income"]["rows"]["Operating Income"] = [v * 0.20 for v in rev[:4]] + [v * 0.2 for v in rev[4:]]
    assert check(evaluate(raw), 3, "kill_operating_margin").status == "PASS"
    raw["q_income"]["rows"]["Operating Income"] = [v * 0.1999 for v in rev]
    assert check(evaluate(raw), 3, "kill_operating_margin").status == "FAIL"


def test_revenue_growth_10_boundary_and_falling():
    raw = good_raw()
    prior = 490 / 1.1 / 4
    raw["q_income"]["rows"]["Total Revenue"][4:] = [prior * B] * 4
    r = evaluate(raw)
    assert check(r, 3, "revenue_growth").status == "PASS"
    assert check(r, 3, "kill_growth_falling").status == "PASS"
    raw["q_income"]["rows"]["Total Revenue"][4:] = [prior * 1.001 * B] * 4  # just below 10%
    r = evaluate(raw)
    assert check(r, 3, "revenue_growth").status == "FAIL"
    # previous period = latest annual growth 27.8% -> falling -> instant kill
    assert check(r, 3, "kill_growth_falling").status == "FAIL"


def test_growth_below_10_not_falling_is_not_killed():
    raw = good_raw()
    raw["q_income"]["rows"]["Total Revenue"][4:] = [490 / 1.05 / 4 * B] * 4   # 5%
    raw["a_income"]["rows"]["Total Revenue"] = [v * B for v in (100, 98, 97, 96.5)]  # previous growth ~1%
    raw["a_income"]["rows"]["Operating Income"] = [v * B * 0.4 for v in (100, 98, 97, 96.5)]
    c = check(evaluate(raw), 3, "kill_growth_falling")
    assert c.status == "PASS" and "not falling" in c.note


def test_market_cap_1b_and_small_cap_2b():
    raw = good_raw()
    raw["fast"]["market_cap"] = 1e9
    r = evaluate(raw)
    assert check(r, 3, "kill_market_cap").status == "PASS"
    assert check(r, 1, "skip_small_cap").status == "FAIL"     # 1B < 2B (A1)
    raw["fast"]["market_cap"] = 0.999e9
    assert check(evaluate(raw), 3, "kill_market_cap").status == "FAIL"
    raw["fast"]["market_cap"] = 2e9
    assert check(evaluate(raw), 1, "skip_small_cap").status == "PASS"


def test_short_interest_10_boundary():
    raw = good_raw()
    raw["info"]["shortPercentOfFloat"] = 0.10
    assert check(evaluate(raw), 3, "kill_short_interest").status == "PASS"
    raw["info"]["shortPercentOfFloat"] = 0.1001
    assert check(evaluate(raw), 3, "kill_short_interest").status == "FAIL"


def test_debt_vs_cash_even_by_a_dollar():
    raw = good_raw()
    raw["q_balance"]["rows"]["Total Debt"][0] = 50 * B
    assert check(evaluate(raw), 3, "kill_debt_gt_cash").status == "PASS"   # equal: not more debt
    raw["q_balance"]["rows"]["Total Debt"][0] = 50 * B + 1
    assert check(evaluate(raw), 3, "kill_debt_gt_cash").status == "FAIL"


def test_earnings_misses_boundary():
    raw = good_raw()
    rows = raw["earnings"]["rows"]
    rows[0]["reported"] = 0.9
    assert check(evaluate(raw), 3, "kill_earnings_misses").status == "PASS"
    rows[1]["reported"] = 0.9
    assert check(evaluate(raw), 3, "kill_earnings_misses").status == "FAIL"


def test_earnings_misses_fewer_than_4_quarters():
    raw = good_raw()
    raw["earnings"]["rows"] = raw["earnings"]["rows"][:3]
    assert check(evaluate(raw), 3, "kill_earnings_misses").status == "UNKNOWN"


def test_fcf_quarters_rule():
    raw = good_raw()
    raw["q_cashflow"]["rows"]["Free Cash Flow"][2] = -1
    assert check(evaluate(raw), 3, "fcf_positive_quarters").status == "FAIL"
    raw = good_raw()
    raw["q_cashflow"] = {"columns": Q[:3], "rows": {"Free Cash Flow": [1e9] * 3}}
    assert check(evaluate(raw), 3, "fcf_positive_quarters").status == "UNKNOWN"


def test_fcf_fallback_ocf_minus_capex():
    raw = good_raw()
    raw["q_cashflow"] = {"columns": Q, "rows": {"Operating Cash Flow": [10 * B] * 8,
                                                "Capital Expenditure": [-4 * B] * 8}}
    s = metrics(raw).series("fcf", "q")
    assert s.value[0][1] == 6 * B and "Operating Cash Flow" in s.source


def test_rule_of_40_required_only_for_software():
    r = evaluate()
    c = check(r, 3, "rule_of_40")
    assert c.required and c.status == "PASS"
    man = good_manual()
    man["business_model_type"] = "hardware"
    c = check(evaluate(None, man), 3, "rule_of_40")
    assert not c.required and c.status == "INFO"


def test_rule_of_40_labels():
    raw = good_raw()
    raw["q_cashflow"]["rows"]["Free Cash Flow"] = [v * 0.9 for v in raw["q_income"]["rows"]["Total Revenue"]]
    c = check(evaluate(raw), 3, "rule_of_40")
    assert "shuts everybody up" in c.note


def test_scalability_test_b():
    r = evaluate()
    assert check(r, 3, "scalability").status == "PASS"
    raw = good_raw()
    raw["q_income"]["rows"]["Operating Income"][:4] = [v * 0.30 for v in raw["q_income"]["rows"]["Total Revenue"][:4]]
    assert check(evaluate(raw), 3, "scalability").status == "FAIL"


# ------------------------------------------------------------ step 2
def test_step2_combinations():
    assert evaluate().steps[1].status == "PASS"
    raw = good_raw()
    raw["q_balance"]["rows"]["Total Debt"] = [60 * B] * 8          # fails cash vs debt only
    man = good_manual()
    assert evaluate(raw, man).steps[1].status == "UNKNOWN"          # reason null
    man["step2_valid_reason"] = "none"
    assert evaluate(raw, man).steps[1].status == "FAIL"
    man["step2_valid_reason"] = "infrastructure_leverage"
    r = evaluate(raw, man)
    assert r.steps[1].status == "PASS"
    assert check(r, 3, "kill_debt_gt_cash").status == "FAIL"        # the instant kill wins
    assert any("Inconsistency 2" in n for n in r.notes)
    raw["q_income"]["rows"]["Operating Income"] = [-1 * B] * 8      # two fail
    raw["a_income"]["rows"]["Operating Income"] = [-1 * B] * 4
    assert evaluate(raw, man).steps[1].status == "FAIL"


def test_step2_revenue_rise_needs_three_years():
    raw = good_raw()
    raw["a_income"]["rows"]["Total Revenue"] = [460 * B, 360 * B, 280 * B, None]
    assert check(evaluate(raw), 2, "revenue_rose").status == "UNKNOWN"
    raw["a_income"]["rows"]["Total Revenue"] = [460 * B, 470 * B, 280 * B, 220 * B]
    assert check(evaluate(raw), 2, "revenue_rose").status == "FAIL"


# ------------------------------------------------------------ step 8
def _bal(**kw):
    raw = good_raw()
    for k, v in kw.items():
        raw["q_balance"]["rows"][k] = [v] * 8
    return steps.loan_ratios(metrics(raw))


def test_interest_coverage_boundary():
    raw = good_raw()
    op = sum(raw["q_income"]["rows"]["Operating Income"][:4])
    raw["q_income"]["rows"]["Interest Expense"] = [op / 16] * 8
    assert check(evaluate(raw), 8, "interest_coverage").status == "PASS"
    raw["q_income"]["rows"]["Interest Expense"] = [op / 15.9] * 8
    assert check(evaluate(raw), 8, "interest_coverage").status == "FAIL"
    raw["q_income"]["rows"]["Interest Expense"] = [op / 400] * 8
    assert "above the document's 4-10x range" in check(evaluate(raw), 8, "interest_coverage").note


def test_no_interest_expense_passes_with_note():
    raw = good_raw()
    del raw["q_income"]["rows"]["Interest Expense"]
    del raw["a_income"]["rows"]["Interest Expense"]
    c = check(evaluate(raw), 8, "interest_coverage")
    assert c.status == "PASS" and "A22" in c.assumptions


def test_assets_to_liabilities_boundaries():
    assert _bal(**{"Total Assets": 130 * B})["assets_to_liabilities"].value == pytest.approx(2.0)
    raw = good_raw()
    raw["q_balance"]["rows"]["Total Assets"] = [130 * B] * 8
    assert check(evaluate(raw), 8, "assets_to_liabilities").status == "PASS"
    raw["q_balance"]["rows"]["Total Assets"] = [129.9 * B] * 8
    assert check(evaluate(raw), 8, "assets_to_liabilities").status == "FAIL"
    raw["q_balance"]["rows"]["Total Assets"] = [190 * B] * 8
    assert "ideal" in check(evaluate(raw), 8, "assets_to_liabilities").note


def test_current_ratio_boundary():
    raw = good_raw()
    raw["q_balance"]["rows"]["Current Assets"] = [30 * B] * 8
    assert check(evaluate(raw), 8, "current_ratio").status == "PASS"
    raw["q_balance"]["rows"]["Current Assets"] = [29.9 * B] * 8
    assert check(evaluate(raw), 8, "current_ratio").status == "FAIL"


def test_debt_to_equity_boundary_and_negative_equity():
    raw = good_raw()
    raw["q_balance"]["rows"]["Stockholders Equity"] = [15 * B] * 8      # 60 / 15 = 4.0
    assert check(evaluate(raw), 8, "debt_to_equity").status == "FAIL"
    raw["q_balance"]["rows"]["Stockholders Equity"] = [15.1 * B] * 8
    assert check(evaluate(raw), 8, "debt_to_equity").status == "PASS"
    raw["q_balance"]["rows"]["Stockholders Equity"] = [-5 * B] * 8
    c = check(evaluate(raw), 8, "debt_to_equity")
    assert c.status == "FAIL" and "negative equity" in c.note


def test_peer_medians_info():
    from helpers import metrics as mk
    peer = good_raw()
    peer["q_balance"]["rows"]["Current Assets"] = [60 * B] * 8
    man = good_manual()
    man["step8"] = {"peers": ["P1"]}
    r = evaluate(None, man, peers={"P1": mk(peer)})
    c = check(r, 8, "peer_current_ratio")
    assert c.status == "INFO" and c.value.startswith("2.00")


# ------------------------------------------------------------ step 7
def test_step7_margin_expanding_a5():
    r = evaluate()
    assert check(r, 7, "margin_expanding").status == "PASS"
    raw = good_raw()
    rev = [460, 360, 280, 220]
    raw["a_income"]["rows"]["Operating Income"] = [v * B * m for v, m in zip(rev, [0.44, 0.35, 0.40, 0.30])]
    assert check(evaluate(raw), 7, "margin_expanding").status == "PASS"   # one down year allowed
    raw["a_income"]["rows"]["Operating Income"] = [v * B * m for v, m in zip(rev, [0.44, 0.35, 0.40, 0.45])]
    assert check(evaluate(raw), 7, "margin_expanding").status == "FAIL"   # latest below first


def test_step7_labels():
    c = check(evaluate(), 7, "revenue_every_year")
    assert c.status == "PASS"
    raw = good_raw()
    raw["a_income"]["rows"]["Total Revenue"] = [v * B for v in (230, 220, 200, 160)]
    raw["a_income"]["rows"]["Operating Income"] = [v * B * 0.4 for v in (230, 220, 200, 160)]
    assert "maturing" in check(evaluate(raw), 7, "revenue_every_year").note


# ------------------------------------------------------------ step 10 / 11
def test_step10_checklist_a6():
    man = good_manual()
    assert check(evaluate(None, man), 10, "checklist").status == "PASS"   # consistent_beats auto (A21)
    man["step10"]["straight_answers"] = False
    assert check(evaluate(None, man), 10, "checklist").status == "FAIL"
    man["step10"]["straight_answers"] = None
    assert check(evaluate(None, man), 10, "checklist").status == "UNKNOWN"


def test_co_ceo_auto_and_override():
    raw = good_raw()
    raw["info"]["companyOfficers"] = [{"name": "A", "title": "Co-CEO"}, {"name": "B", "title": "Co-CEO"}]
    assert check(evaluate(raw), 10, "co_ceo").status == "FAIL"
    man = good_manual()
    man["step10"]["co_ceo"] = False
    assert check(evaluate(raw, man), 10, "co_ceo").status == "PASS"


def test_declining_margins_a18():
    assert check(evaluate(), 11, "declining_margins").status == "PASS"
    raw = good_raw()
    rev = [460, 360, 280, 220]
    raw["a_income"]["rows"]["Operating Income"] = [v * B * m for v, m in zip(rev, [0.39, 0.40, 0.36, 0.30])]
    c = check(evaluate(raw), 11, "declining_margins")
    assert c.status == "PASS" and "warning" in c.note                       # one of two fell
    q = raw["q_income"]["rows"]["Total Revenue"]
    raw["q_income"]["rows"]["Operating Income"] = [v * 0.35 for v in q[:4]] + [v * 0.40 for v in q[4:]]
    assert check(evaluate(raw), 11, "declining_margins").status == "FAIL"   # both fell


def test_inventory_pileup_a9():
    raw = good_raw()
    assert check(evaluate(raw), 11, "inventory_pileup").status == "PASS"   # no Inventory line (A22)
    raw["q_balance"]["rows"]["Inventory"] = [20 * B, 18 * B, 16 * B, 14 * B, 10 * B, 10 * B, 10 * B, 10 * B]
    assert check(evaluate(raw), 11, "inventory_pileup").status == "FAIL"   # +100% vs +30.3%
    raw["q_balance"]["rows"]["Inventory"] = [12 * B, 18 * B, 16 * B, 14 * B, 10 * B, 10 * B, 10 * B, 10 * B]
    assert check(evaluate(raw), 11, "inventory_pileup").status == "PASS"   # +20%


def test_share_sales_a10_boundary():
    raw = good_raw()
    raw["a_balance"]["rows"]["Ordinary Shares Number"] = [1.05 * B, 1.03 * B, 1.01 * B, 1.00 * B]
    assert steps.share_sales(metrics(raw)).value is False                  # exactly 5% is not "more than 5%"
    raw["a_balance"]["rows"]["Ordinary Shares Number"] = [1.06 * B, 1.03 * B, 1.01 * B, 1.00 * B]
    assert steps.share_sales(metrics(raw)).value is True


def test_hype_trap_all_four():
    raw = good_raw()
    for k in ("q_income", "a_income"):
        raw[k]["rows"]["Total Revenue"] = [0.0] * len(raw[k]["columns"])
        raw[k]["rows"]["Operating Income"] = [-1 * B] * len(raw[k]["columns"])
    raw["q_balance"]["rows"]["Total Debt"] = [60 * B] * 8
    raw["a_balance"]["rows"]["Ordinary Shares Number"] = [1.2 * B, 1.1 * B, 1.05 * B, 1.0 * B]
    raw["info"].pop("revenueGrowth")
    man = good_manual()
    man["step11"]["nonstop_media_hype"] = True
    assert check(evaluate(raw, man), 11, "hype_trap").status == "FAIL"
    man["step11"]["nonstop_media_hype"] = False
    assert check(evaluate(raw, man), 11, "hype_trap").status == "PASS"


def test_insider_hint_a7():
    raw = good_raw()
    raw["insider_transactions"] = [{"date": "2026-05-01", "shares": 20_000_000, "text": "Sale at price 45.00 per share."}]
    h = steps.insider_hint(metrics(raw))
    assert h.meta["net_pct"] == pytest.approx(2.0)
    assert h.value is False                       # fixture 12-month return is ~15%, not a run
    raw["history"] = daily(10, 100, years=1.5)    # the stock ran
    h = steps.insider_hint(metrics(raw))
    assert h.meta["ret"] > 50 and h.value is True
