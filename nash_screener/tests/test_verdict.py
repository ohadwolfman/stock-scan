import manual
from fixtures import good_manual, good_raw
from helpers import check, evaluate


def test_survived_all_12():
    r = evaluate()
    assert r.verdict == "SURVIVED ALL 12" and r.eliminated_at is None
    assert r.missing == []


def test_first_fail_in_step_order_wins():
    raw = good_raw()
    raw["info"]["shortPercentOfFloat"] = 0.2                                   # step 3
    raw["q_balance"]["rows"]["Stockholders Equity"] = [10e9] * 8               # step 8
    r = evaluate(raw)
    assert r.verdict == "ELIMINATED AT STEP 3"
    assert r.steps[7].status == "FAIL"                                         # all steps still evaluated
    man = good_manual()
    man["step1"]["has_gap"] = False                                            # "No gap, no edge"
    r = evaluate(raw, man)
    assert r.verdict == "ELIMINATED AT STEP 1" and r.eliminated_at == 1


def test_empty_manual_is_ignored_not_passed():
    r = evaluate(None, {})
    assert r.verdict == "PASSED ALL EVALUATED"   # A28: nothing failed, but manual-only steps are N/A, not PASS
    for f in ("step1.paying_customers", "step4.provides", "step9.types", "step11.bear_reasons", "skip_zones.seasonal"):
        assert f in r.missing
    assert r.steps[3].status == "NA" and r.steps[4].status == "NA"


def test_fail_beats_unknown():
    man = good_manual()
    man["step5"]["broad_market"] = False
    man["step1"]["paying_customers"] = None
    r = evaluate(None, man)
    assert r.verdict == "ELIMINATED AT STEP 5"


def test_no_auto_check_passes_on_missing_data():
    empty = {"ticker": "EMPTY", "info": {}, "fast": {}, "errors": ["info: simulated failure"]}
    r = evaluate(empty, good_manual(), spy={})
    offenders = [(s.n, c.id, c.status) for s in r.steps for c in s.checks
                 if c.kind == "auto" and c.status not in ("UNKNOWN", "INFO")]
    assert offenders == []
    assert r.verdict == "INCOMPLETE"
    assert r.completeness == 0.0


def test_missing_single_fields_make_unknown_not_pass():
    raw = good_raw()
    del raw["info"]["shortPercentOfFloat"]
    assert check(evaluate(raw), 3, "kill_short_interest").status == "UNKNOWN"
    raw = good_raw()
    del raw["q_balance"]["rows"]["Total Debt"]
    del raw["a_balance"]["rows"]["Total Debt"]
    r = evaluate(raw)
    assert check(r, 3, "kill_debt_gt_cash").status == "UNKNOWN"
    assert check(r, 2, "cash_gt_debt").status == "UNKNOWN"


def test_invalid_manual_values_are_ignored():
    man = good_manual()
    man["step6"]["moat"] = 7
    man["step1"]["has_gap"] = "yes"
    m = manual.Manual("X", man)
    assert m.d["step6"]["moat"] is None and m.d["step1"]["has_gap"] is None
    assert len(m.errors) == 2
