"""Step 6: the 13-category scorecard. Each category 0, 5 or 10; None = missing.

Boundaries (from the spec): the middle band includes both ends; exactly 2x cash = 10; cash equal to
debt = 0; category 7 beat by exactly 20 points = 10, 0-10 points = 0 (A13).
"""
from __future__ import annotations

from dataclasses import dataclass

import config

R = 6  # comparisons on values rounded to 6 decimals, so 10.000000001% counts as 10%


def _r(x):
    return None if x is None else round(x, R)


def score_cash_debt(cash, debt):
    if cash is None or debt is None:
        return None
    if cash <= debt:
        return 0
    if cash >= config.SCORE_CASH_DEBT_STRONG * debt:
        return 10
    return 5


def _band_up(v, lo, hi):
    """below lo = 0, lo..hi inclusive = 5, above hi = 10"""
    v = _r(v)
    if v is None:
        return None
    if v < lo:
        return 0
    if v <= hi:
        return 5
    return 10


def score_revenue_growth(pct):
    return _band_up(pct, *config.SCORE_REV_GROWTH_BANDS)


def score_operating_margin(pct):
    return _band_up(pct, *config.SCORE_OP_MARGIN_BANDS)


def score_institutional(pct):
    return _band_up(pct, *config.SCORE_INST_BANDS)


def score_short_interest(pct):
    """above 10 = 0, 5..10 inclusive = 5, below 5 = 10"""
    v = _r(pct)
    if v is None:
        return None
    lo, hi = config.SCORE_SHORT_BANDS
    if v > hi:
        return 0
    if v >= lo:
        return 5
    return 10


def score_scalability(rev_growth, exp_growth):
    if rev_growth is None or exp_growth is None:
        return None
    return 10 if _r(rev_growth) > _r(exp_growth) else 0


def score_five_year(excess_pp):
    """underperformed = 0; beat by 0-10 = 0 (A13); 10 to <20 = 5; 20+ = 10"""
    v = _r(excess_pp)
    if v is None:
        return None
    lo, hi = config.SCORE_5Y_BANDS
    if v >= hi:
        return 10
    if v >= lo:
        return 5
    return 0


def band(total):
    if total >= config.SCORE_EXCEPTIONAL:
        return "Exceptional. Once in a lifetime."
    if total >= config.SCORE_WATCHLIST:
        return "Watchlist. Investable."
    return "Absolute no-go"


@dataclass
class Row:
    n: int
    name: str
    name_he: str
    value: str
    points: int | None
    source: str
    manual: bool
    assumptions: tuple = ()


CATEGORIES = [
    (1, "Cash vs debt", "מזומן מול חוב"),
    (2, "Revenue growth", "צמיחת הכנסות"),
    (3, "Operating margin", "מרווח תפעולי"),
    (4, "Short interest", "שורט"),
    (5, "Institutional ownership", "אחזקה מוסדית"),
    (6, "Revenue growing faster than expenses", "הכנסות צומחות מהר יותר מהוצאות"),
    (7, "5-year return vs S&P 500", "תשואת 5 שנים מול S&P 500"),
    (8, "Moat*", "חפיר*"),
    (9, "CEO*", "מנכ\"ל*"),
    (10, "Recession proof, pricing power", "חסינות למיתון, כוח תמחור"),
    (11, "Secular trend*", "מגמה ארוכת טווח*"),
    (12, "Culture and mission*", "תרבות ושליחות*"),
    (13, "Talent*", "כישרון*"),
]
MANUAL_FIELD = {8: "moat", 9: "ceo", 10: "recession_proof_pricing_power", 11: "secular_trend",
                12: "culture_mission", 13: "talent"}


def compute(m, man, spy_hist) -> dict:
    """m: Metrics, man: Manual. Returns rows, computed/manual points, min/max, band, status."""
    cash, debt = m.latest("cash"), m.latest("debt")
    rg, eg = m.revenue_growth(), m.expense_growth()
    om, si, inst = m.operating_margin(), m.short_interest(), m.institutional_ownership()
    fy = m.five_year_excess(spy_hist)

    def f(v, unit="%"):
        return "n/a" if v is None else f"{v:,.1f}{unit}"

    rows = [
        Row(1, *CATEGORIES[0][1:], f"cash {f(cash.value, '')} / debt {f(debt.value, '')}"
            + (f" = {cash.value / debt.value:.2f}x" if cash.ok and debt.ok and debt.value else ""),
            score_cash_debt(cash.value, debt.value), f"{cash.source}; {debt.source}", False, ("A16",)),
        Row(2, *CATEGORIES[1][1:], f(rg.value), score_revenue_growth(rg.value), rg.source, False),
        Row(3, *CATEGORIES[2][1:], f(om.value), score_operating_margin(om.value), om.source, False),
        Row(4, *CATEGORIES[3][1:], f(si.value), score_short_interest(si.value), si.source, False),
        Row(5, *CATEGORIES[4][1:], f(inst.value), score_institutional(inst.value), inst.source, False),
        Row(6, *CATEGORIES[5][1:], f"revenue {f(rg.value)} vs expenses {f(eg.value)}",
            score_scalability(rg.value, eg.value), f"{rg.source}; {eg.source}", False),
        Row(7, *CATEGORIES[6][1:], f(fy.value, " pp"), score_five_year(fy.value), fy.source, False, ("A13", "A14")),
    ]
    for n, name, name_he in CATEGORIES[7:]:
        field = MANUAL_FIELD[n]
        v = man.get(f"step6.{field}")
        rows.append(Row(n, name, name_he, "manual" if v is None else str(v), v, f"manual step6.{field}", True))

    computed = sum(r.points for r in rows if not r.manual and r.points is not None)
    manual_pts = sum(r.points for r in rows if r.manual and r.points is not None)
    missing = [r for r in rows if r.points is None]
    auto_missing = [r for r in missing if not r.manual]
    total_min = computed + manual_pts
    total_max = total_min + 10 * len(missing)
    # A28: categories with an empty manual score are left out; the 75/130 bar is scaled to what was scored
    scored = len(rows) - len([r for r in missing if r.manual])
    bar = config.SCORE_WATCHLIST * scored / len(rows)
    if total_min + 10 * len(auto_missing) < bar:
        status = "FAIL"
    elif total_min >= bar and not auto_missing:
        status = "PASS"
    else:
        status = "UNKNOWN"
    return {
        "scored": scored, "bar": bar, "rows": rows, "computed": computed, "manual": manual_pts, "min": total_min, "max": total_max,
        "complete": not missing, "missing": [r.n for r in missing], "status": status,
        "band": band(total_min) if not missing else
        (band(total_min) if band(total_min) == band(total_max) else f"{band(total_min)} .. {band(total_max)}"),
    }
