"""Steps 1-12 and the verdict. "Run them top to bottom, in this order. Fail any step and the company leaves."

Every check returns status PASS | FAIL | UNKNOWN | INFO with value, threshold, distance to pass,
source and note. A missing input is UNKNOWN, never PASS. All 12 steps are always evaluated.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config
import scorecard
import valuation
from metrics import M, Metrics, growth_pct, pct

PASS, FAIL, UNKNOWN, INFO = "PASS", "FAIL", "UNKNOWN", "INFO"


@dataclass
class Check:
    id: str
    name: str                 # Hebrew label
    status: str
    value: str = ""
    threshold: str = ""
    distance: str = ""
    source: str = ""
    note: str = ""
    required: bool = True
    quote: str = ""           # the document's own English phrase
    assumptions: tuple = ()
    kind: str = "auto"        # auto | manual
    raw: object = None        # machine value for the CSV


@dataclass
class Step:
    n: int
    name: str
    name_en: str
    checks: list
    quote: str = ""
    notes: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        req = [c for c in self.checks if c.required and c.status != INFO]
        if any(c.status == FAIL for c in req):
            return FAIL
        if any(c.status == UNKNOWN for c in req):
            return UNKNOWN
        return PASS

    def failed(self):
        return [c for c in self.checks if c.required and c.status == FAIL]

    def unknown(self):
        return [c for c in self.checks if c.required and c.status == UNKNOWN]


@dataclass
class Result:
    ticker: str
    steps: list
    verdict: str
    eliminated_at: int | None
    header: dict
    missing: list
    manual_errors: list
    assumptions: list
    notes: list
    errors: list
    completeness: float
    score: dict
    valuation: dict


# ------------------------------------------------------------------ formatting
def fmt(v, unit="", digits=1):
    if v is None:
        return "n/a"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if unit == "$":
            return money(v)
        return f"{v:,.{digits}f}{unit}"
    return str(v)


def money(v):
    if v is None:
        return "n/a"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{v / div:,.2f}{suf}"
    return f"{v:,.2f}"


def _cmp(v, op, thr):
    v, thr = round(v, 6), round(thr, 6)
    return {">=": v >= thr, ">": v > thr, "<=": v <= thr, "<": v < thr}[op]


def num_check(cid, name, m: M, op, thr, unit="%", quote="", required=True, note="", digits=1):
    """Numeric threshold check. distance = headroom (+) or shortfall (-) toward the threshold."""
    if not m.ok:
        return Check(cid, name, UNKNOWN, "n/a", f"{op} {fmt(thr, unit, digits)}", "", m.source,
                     " ".join(x for x in (m.note, note) if x), required, quote, tuple(m.assumptions))
    passed = _cmp(m.value, op, thr)
    dist = m.value - thr if op in (">=", ">") else thr - m.value
    dist_txt = ("+" if dist >= 0 else "") + money(dist) if unit == "$" else f"{dist:+,.{digits}f}{unit}"
    return Check(cid, name, PASS if passed else FAIL, fmt(m.value, unit, digits), f"{op} {fmt(thr, unit, digits)}",
                 dist_txt, m.source, " ".join(x for x in (m.note, note) if x),
                 required, quote, tuple(m.assumptions), raw=m.value)


def manual_bool(man, path, name, bad=False, quote="", required=True, note=""):
    """Manual true/false. `bad` is the value that fails (False for 'must be true', True for red flags)."""
    v = man.get(path) if required else man.peek(path)
    if v is None:
        return Check(path.split(".")[-1], name, UNKNOWN, "null", f"{'false' if bad else 'true'}", "",
                     f"manual {path}", note, required, quote, kind="manual")
    return Check(path.split(".")[-1], name, FAIL if v == bad else PASS, fmt(v), f"{'false' if bad else 'true'}",
                 "", f"manual {path}", note, required, quote, kind="manual", raw=v)


def manual_text(man, path, name, quote="", required=True):
    v = man.get(path) if required else man.peek(path)
    filled = bool(v and str(v).strip())
    return Check(path.split(".")[-1], name, PASS if filled else (UNKNOWN if required else INFO),
                 str(v) if filled else "(empty)", "filled", "", f"manual {path}", "", required, quote,
                 kind="manual", raw=v if filled else None)


def info(cid, name, value, source="", note="", quote="", assumptions=(), raw=None):
    return Check(cid, name, INFO, value, "", "", source, note, False, quote, tuple(assumptions), raw=raw)


def tri(cid, name, flag, source, value="", note="", bad=True, quote="", required=True, kind="auto",
        assumptions=()):
    """Auto boolean where flag == bad fails. flag None = UNKNOWN."""
    if flag is None:
        return Check(cid, name, UNKNOWN, value or "n/a", "", "", source, note, required, quote, tuple(assumptions),
                     kind)
    return Check(cid, name, FAIL if flag == bad else PASS, value or fmt(flag), "", "", source, note, required,
                 quote, tuple(assumptions), kind, raw=flag)


# ------------------------------------------------------------------ shared logic
def age_check(m: Metrics, man, cid, name, quote=""):
    """Under 10 years from founding fails. founding_year missing: first trading date 10+ years ago passes
    (founding precedes listing), otherwise UNKNOWN."""
    fy = man.peek("founding_year")
    a = m.company_age(fy)
    if a.ok:
        ok = a.value >= config.MIN_COMPANY_AGE_YEARS
        return Check(cid, name, PASS if ok else FAIL, f"{a.value} years", f">= {config.MIN_COMPANY_AGE_YEARS} years",
                     f"{a.value - config.MIN_COMPANY_AGE_YEARS:+d} years", a.source, "", True, quote,
                     kind="manual", raw=a.value)
    listed = a.meta.get("listed_years")
    if listed is not None and listed >= config.MIN_COMPANY_AGE_YEARS:
        return Check(cid, name, PASS, f"listed {listed:.1f} years", f">= {config.MIN_COMPANY_AGE_YEARS} years",
                     f"{listed - config.MIN_COMPANY_AGE_YEARS:+.1f} years", a.source,
                     "founding precedes listing", True, quote, raw=listed)
    if "founding_year" not in man.missing:
        man.missing.append("founding_year")
    return Check(cid, name, UNKNOWN, "n/a" if listed is None else f"listed {listed:.1f} years",
                 f">= {config.MIN_COMPANY_AGE_YEARS} years", "", a.source, "fill founding_year", True, quote)


def per_period_positive(cid, name, m: M, quote="", fmt_row=None):
    """Positive in each of the last 4 to 6 quarters; fewer than 4 available = UNKNOWN."""
    if not m.ok:
        return Check(cid, name, UNKNOWN, "n/a", "> 0 in each of the last 4-6 quarters", "", m.source, m.note,
                     True, quote)
    rows = m.value
    bad = [r for r in rows if (r[1] <= 0 if len(r) == 2 else r[1] <= r[2])]
    shown = "; ".join(fmt_row(r) for r in rows)
    n = len(rows)
    if bad:
        st = FAIL
    elif n < config.PRESCREEN_MIN_QUARTERS:
        st = UNKNOWN
    else:
        st = PASS
    note = f"{n} quarters available" + (f"; failing: {', '.join(r[0] for r in bad)}" if bad else "")
    return Check(cid, name, st, shown, "> 0 in each of the last 4-6 quarters", f"{n - len(bad)}/{n} positive",
                 m.source, note, True, quote)


def loan_ratios(m: Metrics) -> dict:
    """Step 8 ratios: balance sheet latest quarter, operating income and interest expense TTM."""
    op = m.ttm_or_fallback("operating_income")
    ie = m.ttm("interest_expense")
    ie_src = ie.source
    if not ie.ok:
        q = m.series("interest_expense", "q")
        a = m.series("interest_expense", "a")
        if q.meta.get("absent") and (a.meta.get("absent") or m.stmts[("a", "income")].empty):
            ie = M(0.0, q.source, "no interest expense reported", assumptions=["A22"])
        elif a.ok:
            ie = M(a.value[0][1], f"{a.source} FY {a.value[0][0]}", "TTM unavailable; latest fiscal year")
    if op.ok and ie.ok:
        if ie.value == 0:
            cov = M(float("inf"), f"{op.source}; {ie.source}", "No interest expense", assumptions=ie.assumptions)
        else:
            cov = M(op.value / abs(ie.value), f"{op.source} / {ie.source}")
    else:
        cov = M(None, f"{op.source}; {ie_src}", " ".join(x for x in (op.note, ie.note) if x))

    ta, gw, tl = m.latest("total_assets"), m.latest("goodwill"), m.latest("total_liabilities")
    if not gw.ok and gw.meta.get("absent"):
        gw = M(0.0, gw.source, "no Goodwill line reported, taken as 0", assumptions=["A22"])
    if ta.ok and gw.ok and tl.ok and tl.value:
        a2l = M((ta.value - gw.value) / tl.value, f"({ta.source} - {gw.source}) / {tl.source}", gw.note,
                assumptions=gw.assumptions)
    else:
        a2l = M(None, f"{ta.source}; {gw.source}; {tl.source}")
    ca, cl = m.latest("current_assets"), m.latest("current_liabilities")
    cr = M(ca.value / cl.value, f"{ca.source} / {cl.source}") if ca.ok and cl.ok and cl.value \
        else M(None, f"{ca.source}; {cl.source}")
    eq = m.latest("equity")
    de = M(tl.value / eq.value, f"{tl.source} / {eq.source}", meta={"equity": eq.value}) \
        if tl.ok and eq.ok and eq.value else M(None, f"{tl.source}; {eq.source}", meta={"equity": eq.value})
    return {"coverage": cov, "assets_to_liabilities": a2l, "current_ratio": cr, "debt_to_equity": de,
            "operating_income": op, "interest_expense": ie}


def share_sales(m: Metrics) -> M:
    """A10: share count up in each of the last 3 fiscal years and by more than 5% in total."""
    s = m.annual("shares")
    need = config.SHARE_SALES_YEARS + 1
    if not s.ok or len(s.value) < need:
        return M(None, s.source, f"needs {need} fiscal years of share count", assumptions=["A10"])
    v = s.value[:need]
    each_up = all(v[i][1] > v[i + 1][1] for i in range(need - 1))
    total = growth_pct(v[0][1], v[-1][1])
    flag = each_up and total is not None and round(total, 6) > config.SHARE_SALES_TOTAL_PCT
    return M(flag, s.source, f"share count {', '.join(f'{d}: {money(x)}' for d, x in v)}; total {fmt(total, '%')}",
             assumptions=["A10"])


def acquisition_hint(m: Metrics) -> str:
    acq, fcf, gw = m.annual("acquisitions", 3), m.annual("fcf", 3), m.annual("goodwill")
    parts = []
    if acq.ok:
        spent = -sum(v for _, v in acq.value if v < 0)
        parts.append(f"acquisition outflows {len(acq.value)}y: {money(spent)}")
        if fcf.ok:
            f = sum(v for _, v in fcf.value)
            parts.append(f"FCF {len(fcf.value)}y: {money(f)}" + (f" ({spent / f * 100:.0f}% of FCF)" if f > 0 else ""))
    else:
        parts.append("no acquisition cash flow line")
    if gw.ok and len(gw.value) >= 2:
        g = growth_pct(gw.value[0][1], gw.value[min(3, len(gw.value) - 1)][1])
        parts.append(f"goodwill {gw.value[min(3, len(gw.value) - 1)][0]} -> {gw.value[0][0]}: {fmt(g, '%')}")
    return "; ".join(parts)


def insider_hint(m: Metrics) -> M:
    """A7: net insider selling above 1% of shares in 12 months while the 12-month return is above 50%."""
    act, sh, ret = m.insider_activity(), m.shares_outstanding(), m.period_return(1)
    if not (act.ok and sh.ok and ret.ok):
        return M(None, f"{act.source}; {sh.source}; {ret.source}", assumptions=["A7"])
    net_pct = act.value["net_sold"] / sh.value * 100
    flag = round(net_pct, 6) > config.INSIDER_NET_SELL_PCT and round(ret.value, 6) > config.INSIDER_RUN_RETURN_PCT
    return M(flag, act.source, f"net sold {net_pct:.2f}% of shares, 12-month return {ret.value:.1f}%",
             assumptions=["A7"], meta={"net_pct": net_pct, "ret": ret.value})


def earnings_counts(m: Metrics):
    rows = m.reported_earnings()
    l4, l8 = rows[:4], rows[:8]
    return {
        "rows": rows,
        "misses4": sum(1 for _, e, r in l4 if r < e), "n4": len(l4),
        "beats4": sum(1 for _, e, r in l4 if r > e),
        "beats8": sum(1 for _, e, r in l8 if r > e), "n8": len(l8),
    }


def co_ceo_auto(m: Metrics):
    officers = m.info.get("companyOfficers")
    if not officers:
        return None, "no officers in info.companyOfficers"
    hits = [o.get("title", "") for o in officers
            if any(p in str(o.get("title", "")).lower() for p in config.CO_CEO_PATTERNS)]
    return bool(hits), f"info.companyOfficers titles{': ' + '; '.join(hits) if hits else ' (no Co-CEO title)'}"


def business_type(m: Metrics, man) -> M:
    v = man.peek("business_model_type")
    if v:
        return M(v, "manual business_model_type")
    return m.business_model_guess()


# ------------------------------------------------------------------ steps
def step1(m, man, mcap_usd):
    c = []
    q = "The trend test"
    for f, he in (("paying_customers", "ביקוש אמיתי ולקוחות משלמים"),
                  ("sustainable_growth", "צמיחה בת קיימא בהכנסות וברווחים"),
                  ("moat_not_commodity", "חפיר, לא סחורה (commodity)"),
                  ("regulatory_tailwind", "רוח גבית רגולטורית או ממשלתית"),
                  ("real_world_adoption", "אימוץ שרואים בעולם האמיתי")):
        c.append(manual_bool(man, f"step1.{f}", he, quote=q))
    c.append(manual_bool(man, "step1.built_for_trend", "נבנתה עבור המגמה מהיום הראשון, לא עסק ותיק שמנסה להתאים את עצמו",
                         quote="Built for the trend from day one"))
    c.append(manual_text(man, "step1.market_story", "השורה הראשונה: הסיפור שהשוק מספר עליה",
                         quote="the story the market tells about it"))
    c.append(manual_text(man, "step1.what_it_is_becoming", "השורה השנייה: מה החברה הופכת להיות בפועל",
                         quote="what the company is actually becoming"))
    c.append(manual_bool(man, "step1.has_gap", "יש פער בין שתי השורות", quote="No gap, no edge"))

    # skip zones: manual value always overrides auto-detection
    info_ = m.info
    country, industry = info_.get("country"), info_.get("industry")
    fy = man.peek("founding_year")
    age = m.company_age(fy)
    if age.ok:
        startup_auto = age.value < config.MIN_COMPANY_AGE_YEARS
    elif (age.meta.get("listed_years") or 0) >= config.MIN_COMPANY_AGE_YEARS:
        startup_auto = False
    else:
        startup_auto = None
    autos = {
        "small_cap": (None if not mcap_usd.ok else mcap_usd.value < config.SMALL_CAP_SKIP_USD,
                      f"market cap USD {money(mcap_usd.value)} vs $2B ({mcap_usd.source})", ("A1", "A25")),
        "chinese": (None if not country else country in config.CHINESE_COUNTRIES, f"info.country = {country}", ("A2",)),
        "commodity": (None if not industry else industry in config.COMMODITY_INDUSTRIES,
                      f"info.industry = {industry}", ("A3",)),
        "airline": (None if not industry else config.AIRLINE_INDUSTRY_KEYWORD in industry,
                    f"info.industry = {industry}", ()),
        "seasonal": (None, "manual only", ()),
        "startup": (startup_auto, age.source, ()),
    }
    startup_kind = "manual" if age.ok else "auto"  # founding_year is a manual input
    he = {"small_cap": "אזור דילוג: חברה קטנה (small cap)", "chinese": "אזור דילוג: חברה סינית",
          "commodity": "אזור דילוג: סחורות", "airline": "אזור דילוג: חברת תעופה",
          "seasonal": "אזור דילוג: עסק עונתי", "startup": "אזור דילוג: סטארטאפ (פחות מ 10 שנים)"}
    for zone, (auto, src, asm) in autos.items():
        override = man.peek(f"skip_zones.{zone}")
        if override is not None:
            c.append(tri(f"skip_{zone}", he[zone], override, f"manual skip_zones.{zone}", kind="manual",
                         note=f"auto: {fmt(auto)}"))
        else:
            if auto is None:
                man.missing.append(f"skip_zones.{zone}")
            c.append(tri(f"skip_{zone}", he[zone], auto, src, assumptions=asm,
                         kind=startup_kind if zone == "startup" else "auto"))

    # evidence for "sustainable revenue and earnings growth"
    _, rg = m._annual_growths("revenue")
    _, og = m._annual_growths("operating_income")
    c.append(info("annual_growth", "ראיה: צמיחה שנתית ב 3 השנים האחרונות",
                  "revenue " + ", ".join(f"FY{d[:4]} {fmt(g, '%')}" for d, g in rg[:3]) +
                  " | operating income " + ", ".join(f"FY{d[:4]} {fmt(g, '%')}" for d, g in og[:3]),
                  "annual income statement"))
    tn = man.peek("step1.trend_name")
    c.append(info("trend_name", "שם המגמה", tn or "(empty)", "manual step1.trend_name"))
    return Step(1, "מציאת המגמה ארוכת הטווח", "Find the secular trend", c)


def step2(m, man):
    a = m.annual("revenue", config.REVENUE_RISE_YEARS + 1)
    need = config.REVENUE_RISE_YEARS
    if a.ok:
        pairs = [(a.value[i][0], a.value[i][1], a.value[i + 1][1]) for i in range(len(a.value) - 1)][:need]
        falls = [p for p in pairs if p[1] <= p[2]]
        st = FAIL if falls else (UNKNOWN if len(pairs) < need else PASS)
        val = ", ".join(f"FY{d[:4]} {money(n)} ({fmt(growth_pct(n, o), '%')})" for d, n, o in pairs)
        q1 = Check("revenue_rose", "ההכנסות צמחו בכל אחת מ 3 השנים האחרונות", st, val,
                   f"up each of the last {need} fiscal years", f"{len(pairs) - len(falls)}/{need} years up",
                   a.source, f"{len(a.value)} fiscal years returned", False,
                   "Revenue has grown for the past few years", ("A4",))
    else:
        q1 = Check("revenue_rose", "ההכנסות צמחו בכל אחת מ 3 השנים האחרונות", UNKNOWN, "n/a", "", "", a.source,
                   "", False, "Revenue has grown for the past few years", ("A4",))
    q2 = num_check("profitable", "החברה רווחית (רווח תפעולי TTM)", m.ttm_or_fallback("operating_income"), ">", 0,
                   unit="$", required=False, quote="The company is profitable")
    ni = m.ttm_or_fallback("net_income")
    cash, debt = m.latest("cash"), m.latest("debt")
    if cash.ok and debt.ok:
        q3 = Check("cash_gt_debt", "יותר מזומן מחוב (רבעון אחרון)", PASS if cash.value > debt.value else FAIL,
                   f"cash {money(cash.value)} / debt {money(debt.value)}", "cash > debt",
                   money(cash.value - debt.value), f"{cash.source}; {debt.source}", "", False,
                   "More cash than debt", ("A16",))
    else:
        q3 = Check("cash_gt_debt", "יותר מזומן מחוב (רבעון אחרון)", UNKNOWN, "n/a", "cash > debt", "",
                   f"{cash.source}; {debt.source}", "", False, "More cash than debt", ("A16",))
    qs = [q1, q2, q3]
    n_pass = sum(q.status == PASS for q in qs)
    n_fail = sum(q.status == FAIL for q in qs)
    notes = []
    reason = None
    if n_fail >= 2:
        st, val = FAIL, f"{n_pass}/3"
    elif n_pass == 3:
        st, val = PASS, "3/3"
    elif n_fail == 0:
        st, val = UNKNOWN, f"{n_pass}/3, {3 - n_pass} unknown"
    else:  # exactly one fail: 2 of 3 at best, the valid reason decides
        reason = man.get("step2_valid_reason")
        if reason == "none":
            st = FAIL
        elif reason is None:
            st = UNKNOWN
        elif n_pass == 2:
            st = PASS
        else:
            st = UNKNOWN
        val = f"{n_pass}/3, reason: {reason}"
        if reason == "infrastructure_leverage" and q3.status == FAIL:
            notes.append("Inconsistency 2: step 2 accepts leverage for infrastructure, but step 3 kills any company "
                         "with more debt than cash 'even by a dollar'. The instant kill wins; the exception only "
                         "saves step 2.")
    rule = Check("two_of_three", "לפחות 2 מתוך 3, ו 2 מתוך 3 רק עם סיבה תקפה", st, val,
                 "3/3, or 2/3 with infrastructure_leverage | path_to_profitability", "",
                 "computed" + (", manual step2_valid_reason" if reason is not None else ""),
                 "Anything else, it's out" if st == FAIL else "", True,
                 "an infrastructure company that genuinely needs leverage / a clear path to profitability")
    c = qs + [rule, info("net_income", "רווח נקי TTM (מידע בלבד)", money(ni.value), ni.source,
                         "Read income from operations, not net income")]
    return Step(2, "בדיקת שפיות", "Sanity check (the No B***t Rule)", c, notes=notes)


def step3(m, man, mcap_usd, s9: Step, btype: M):
    c = []
    c.append(per_period_positive("fcf_positive_quarters", "תזרים חופשי חיובי בכל אחד מ 4 עד 6 הרבעונים האחרונים",
                                 m.per_quarter("fcf"), fmt_row=lambda r: f"{r[0]}: {money(r[1])}"))
    c.append(per_period_positive("net_cash_quarters", "מזומן נטו חיובי בכל אחד מ 4 עד 6 הרבעונים האחרונים",
                                 m.net_cash_per_quarter(),
                                 fmt_row=lambda r: f"{r[0]}: {money(r[1])} vs {money(r[2])}"))
    rg = m.revenue_growth()
    c.append(num_check("revenue_growth", "צמיחת הכנסות 10% ומעלה", rg, ">=", config.MIN_REVENUE_GROWTH_PCT,
                       quote="Revenue growing 10% or more"))
    types = man.peek("step9.types") or []
    if not types:
        man.get("step9.types")
        moat = Check("moat", "חפיר אמיתי (שלב 9)", UNKNOWN, "no moat type", "step9.types and step 9 PASS", "",
                     "manual step9", "", True, "An actual moat", kind="manual")
    else:
        moat = Check("moat", "חפיר אמיתי (שלב 9)", s9.status, ", ".join(types), "step9.types and step 9 PASS", "",
                     "manual step9", f"step 9 status {s9.status}", True, "An actual moat", kind="manual")
    c.append(moat)
    c.append(manual_bool(man, "step3.ceo_team_track_record", "מנכ\"ל וצוות עם רקורד", quote="A CEO and team with a track record"))
    c.append(manual_bool(man, "step3.no_regulatory_legal_overhang", "אין צל רגולטורי או משפטי משמעותי",
                         quote="No major regulatory or legal overhang"))

    # Test A: Rule of 40
    fm = m.fcf_margin()
    r40 = M(rg.value + fm.value, f"{rg.source} + {fm.source}") if rg.ok and fm.ok else M(None, f"{rg.source}; {fm.source}")
    required_types = config.RULE_OF_40_REQUIRED_TYPES
    req = btype.value in required_types
    chk = num_check("rule_of_40", "מבחן A: Rule of 40 (צמיחה + מרווח FCF)", r40, ">=", config.RULE_OF_40, unit="",
                    required=req, quote="40 is the perfect company")
    chk.assumptions = ("A15",)
    chk.note = (f"business model: {btype.value or 'unknown'} ({btype.source}); "
                + ("required" if req else "INFO for this business model"))
    if r40.ok:
        if r40.value > config.RULE_OF_40_SHUTS_UP:
            chk.note += "; basically shuts everybody up"
        elif round(r40.value, 6) < config.RULE_OF_40:
            chk.note += "; below 40: pass on it"
    if btype.value is None and chk.status == FAIL:
        chk.status, chk.required = UNKNOWN, True
        chk.note += "; business model unknown, fill business_model_type"
        man.missing.append("business_model_type")
    elif not req:
        chk.note += f"; result {chk.status}"
        chk.status = INFO
    c.append(chk)

    # Test B: scalability
    eg = m.expense_growth()
    ex = "; ".join(f"{lbl} {r}% vs {e}%" for lbl, r, e in config.SCALABILITY_EXAMPLES)
    if rg.ok and eg.ok:
        ok = round(rg.value, 6) > round(eg.value, 6)
        c.append(Check("scalability", "מבחן B: סקלביליות, הכנסות צומחות מהר יותר מהוצאות", PASS if ok else FAIL,
                       f"revenue {fmt(rg.value, '%')} vs expenses {fmt(eg.value, '%')}", "revenue growth > expense growth",
                       f"{rg.value - eg.value:+.1f} pp", f"{rg.source}; {eg.source}", f"document examples: {ex}",
                       raw=rg.value - eg.value))
    else:
        c.append(Check("scalability", "מבחן B: סקלביליות, הכנסות צומחות מהר יותר מהוצאות", UNKNOWN, "n/a",
                       "revenue growth > expense growth", "", f"{rg.source}; {eg.source}", f"document examples: {ex}"))

    # Instant kills
    k = num_check("kill_market_cap", "הריגה מיידית: שווי שוק מתחת ל 1 מיליארד דולר", mcap_usd, ">=",
                  config.MIN_MARKET_CAP_USD, unit="$", quote="Market cap under $1 billion")
    if mcap_usd.ok:
        k.distance = money(mcap_usd.value - config.MIN_MARKET_CAP_USD)
        k.threshold = ">= 1.00B USD"
    c.append(k)
    cash, debt = m.latest("cash"), m.latest("debt")
    if cash.ok and debt.ok:
        c.append(Check("kill_debt_gt_cash", "הריגה מיידית: יותר חוב ממזומן, אפילו בדולר", FAIL if debt.value > cash.value else PASS,
                       f"cash {money(cash.value)} / debt {money(debt.value)}", "debt <= cash",
                       money(cash.value - debt.value), f"{cash.source}; {debt.source}", "", True,
                       "More debt than cash, even by a dollar", ("A16",), raw=cash.value - debt.value))
    else:
        c.append(Check("kill_debt_gt_cash", "הריגה מיידית: יותר חוב ממזומן, אפילו בדולר", UNKNOWN, "n/a", "debt <= cash", "",
                       f"{cash.source}; {debt.source}", "", True, "More debt than cash, even by a dollar", ("A16",)))
    prev = m.revenue_growth_previous()
    if not rg.ok:
        st, note = UNKNOWN, ""
    elif round(rg.value, 6) >= config.MIN_REVENUE_GROWTH_PCT:
        st, note = PASS, ""
    elif not prev.ok:
        st, note = UNKNOWN, "below 10%, previous period unknown"
    else:
        st = FAIL if rg.value < prev.value else PASS
        note = "falling" if st == FAIL else "below 10% but not falling"
    c.append(Check("kill_growth_falling", "הריגה מיידית: צמיחה מתחת ל 10% ויורדת", st,
                   f"{fmt(rg.value, '%')} (previous {fmt(prev.value, '%')})", ">= 10%, or not falling", "",
                   f"{rg.source}; previous: {prev.source}", note, True, "Revenue growth below 10% and falling",
                   ("A24",)))
    c.append(age_check(m, man, "kill_age", "הריגה מיידית: פחות מ 10 שנים מהקמה", "Less than 10 years old"))
    c.append(num_check("kill_short_interest", "הריגה מיידית: שורט מעל 10%", m.short_interest(), "<=",
                       config.MAX_SHORT_INTEREST_PCT, quote="Short interest above 10%"))
    c.append(num_check("kill_operating_margin", "הריגה מיידית: מרווח תפעולי מתחת ל 20%", m.operating_margin(), ">=",
                       config.MIN_OPERATING_MARGIN_PCT, quote="Operating margin below 20%"))
    e = earnings_counts(m)
    detail = "; ".join(f"{d}: {r} vs {est}" for d, est, r in e["rows"][:4])
    if e["misses4"] >= config.MAX_EARNINGS_MISSES:
        st = FAIL
    elif e["n4"] < 4:
        st = UNKNOWN
    else:
        st = PASS
    c.append(Check("kill_earnings_misses", "הריגה מיידית: 2 החטאות רווח או יותר ב 4 הרבעונים האחרונים", st,
                   f"{e['misses4']} misses in {e['n4']} quarters", "< 2 misses in the last 4", "", m.earnings_source(),
                   detail, True, "2 or more earnings misses in the last 4 quarters", raw=e["misses4"]))
    return Step(3, "סינון מקדים", "Pre-screen", c, quote="most companies die right here")


def step4(m, man):
    c = []
    parts = {k: man.peek(f"step4.{k}") for k in ("provides", "helps", "achieve", "charges")}
    empty = [k for k, v in parts.items() if not (v and str(v).strip())]
    for k in empty:
        man.missing.append(f"step4.{k}")
    name = m.info.get("shortName") or m.raw.get("ticker")
    sentence = (f"{name} provides {parts['provides'] or '[X]'} that helps {parts['helps'] or '[Y]'} achieve "
                f"{parts['achieve'] or '[Z]'}, and charges {parts['charges'] or '[revenue model]'}")
    c.append(Check("sentence", "המשפט: [Company] provides X that helps Y achieve Z, and charges [revenue model]",
                   UNKNOWN if empty else PASS, sentence, "all four parts filled", "", "manual step4",
                   f"missing: {', '.join(empty)}" if empty else "", True, kind="manual"))
    c.append(manual_bool(man, "step4.sentence_clean", "המשפט יוצא נקי",
                         quote="If the sentence won't come out clean, you're not ready for the numbers"))
    c.append(manual_text(man, "step4.pain", "איזה כאב אנחנו מרפאים?", quote="What pain are we curing?"))
    c.append(manual_text(man, "step4.who_and_why", "למי כואב, ולמה?", quote="Who's in pain, and why?"))
    c.append(manual_text(man, "step4.why_us", "למה הלקוח יבוא אלינו ולא למתחרה?",
                         quote="Why will the customer come to us and not the competitor?"))
    return Step(4, "הגדרת העסק", "Define the business", c)


def step5(m, man):
    c = [manual_bool(man, "step5.broad_market", "מוכרת לשוק רחב, לא לנישה"),
         manual_bool(man, "step5.checked_market_size_myself", "בדקתי את גודל השוק בעצמי, לא סמכתי על דוח אנליסט"),
         manual_bool(man, "step5.market_big_enough", "השוק גדול מספיק לתמוך בצמיחה שאני מהמר עליה")]
    note = man.peek("step5.note")
    if note:
        c.append(info("note", "הערה", note, "manual step5.note"))
    return Step(5, "פוטנציאל שוק", "Market potential", c, quote="Great tech in a tiny market is a bad investment.")


def step6(m, man, spy_hist):
    sc = scorecard.compute(m, man, spy_hist)
    total = (f"{sc['computed']} computed + {sc['manual']} manual = {sc['min']}"
             + ("" if sc["complete"] else f"; possible range {sc['min']}-{sc['max']}") + f" /{config.SCORE_MAX}")
    c = [Check("total", "ציון כולל (75 ומעלה עובר)", sc["status"], total,
               f">= {config.SCORE_WATCHLIST}", f"{sc['min'] - config.SCORE_WATCHLIST:+d} (min)",
               "computed categories 1-7 + manual step6", sc["band"] + (" (document calls it 125)"), True,
               "If you love a stock but it scores 75, the stock doesn't love you back.", raw=sc["min"]),]
    for r in sc["rows"]:
        c.append(Check(f"cat{r.n}", f"{r.n}. {r.name_he}", INFO, r.value, "0 / 5 / 10",
                       "" if r.points is None else f"{r.points} pts", r.source,
                       "*Subjective. Score these as harshly as you can." if r.manual else "", False,
                       r.name, r.assumptions, "manual" if r.manual else "auto", raw=r.points))
    return Step(6, "כרטיס ניקוד", "Scorecard", c, extra={"scorecard": sc})


def step7(m, man):
    c = []
    rev = m.annual("revenue")
    years = len(rev.value) if rev.ok else 0
    c.append(info("years", "שנות כספים שהתקבלו מ yfinance", f"{years} (the document asks for 5 from the 10-K)", rev.source))
    if rev.ok and years >= 2:
        chron = list(reversed(rev.value))
        ups = [chron[i + 1][1] > chron[i][1] for i in range(len(chron) - 1)]
        gs = [growth_pct(chron[i + 1][1], chron[i][1]) for i in range(len(chron) - 1)]
        label = ""
        if len(gs) >= 2 and None not in gs[-2:]:
            if gs[-1] > gs[-2]:
                label = "growth stage"
            elif gs[-1] < config.MATURING_GROWTH_PCT:
                label = "maturing"
        c.append(Check("revenue_every_year", "ההכנסות עולות בכל שנה", PASS if all(ups) else FAIL,
                       ", ".join(f"FY{d[:4]} {money(v)}" for d, v in chron), "each year above the previous",
                       f"{sum(ups)}/{len(ups)} years up", rev.source,
                       ("growth " + ", ".join(fmt(g, '%') for g in gs) + (f"; {label}" if label else "")),
                       assumptions=("A20",)))
    else:
        c.append(Check("revenue_every_year", "ההכנסות עולות בכל שנה", UNKNOWN, "n/a", "each year above the previous",
                       "", rev.source, f"{years} fiscal years"))
    margins = list(reversed(m.annual_margins()))
    if len(margins) >= 2:
        downs = sum(1 for i in range(len(margins) - 1) if margins[i + 1][1] < margins[i][1])
        ok = margins[-1][1] > margins[0][1] and downs <= config.MARGIN_MAX_DOWN_YEARS
        c.append(Check("margin_expanding", "המרווח התפעולי מתרחב", PASS if ok else FAIL,
                       ", ".join(f"FY{d[:4]} {fmt(v, '%')}" for d, v in margins),
                       "latest > first, at most 1 down year", f"{margins[-1][1] - margins[0][1]:+.1f} pp, {downs} down",
                       "annual income statement", "", True,
                       "Expanding margins mean freedom. Weak margins mean fragility.", ("A5",)))
    else:
        c.append(Check("margin_expanding", "המרווח התפעולי מתרחב", UNKNOWN, "n/a", "latest > first", "",
                       "annual income statement", "fewer than 2 fiscal years", True,
                       "Expanding margins mean freedom. Weak margins mean fragility.", ("A5",)))
    fcf = m.annual("fcf")
    if fcf.ok and len(fcf.value) >= 2:
        chron = list(reversed(fcf.value))
        ok = all(v > 0 for _, v in chron) and chron[-1][1] > chron[0][1]
        c.append(Check("fcf_positive_rising", "תזרים חופשי חיובי בכל שנה ועולה", PASS if ok else FAIL,
                       ", ".join(f"FY{d[:4]} {money(v)}" for d, v in chron), "> 0 every year, latest > first",
                       money(chron[-1][1] - chron[0][1]), fcf.source))
    else:
        c.append(Check("fcf_positive_rising", "תזרים חופשי חיובי בכל שנה ועולה", UNKNOWN, "n/a",
                       "> 0 every year, latest > first", "", fcf.source))
    ca, da = m.annual("cash"), m.annual("debt")
    if ca.ok and da.ok:
        dd = dict(da.value)
        rows = [(d, v, dd[d]) for d, v in reversed(ca.value) if d in dd]
        ok = all(cv > dv for _, cv, dv in rows)
        c.append(Check("cash_gt_debt_every_year", "יותר מזומן מחוב בסוף כל שנת כספים",
                       (PASS if ok else FAIL) if len(rows) >= 2 or not ok else UNKNOWN,
                       "; ".join(f"FY{d[:4]} {money(cv)} vs {money(dv)}" for d, cv, dv in rows),
                       "cash > debt every year", f"{sum(cv > dv for _, cv, dv in rows)}/{len(rows)} years",
                       f"{ca.source}; {da.source}", assumptions=("A16",)))
    else:
        c.append(Check("cash_gt_debt_every_year", "יותר מזומן מחוב בסוף כל שנת כספים", UNKNOWN, "n/a",
                       "cash > debt every year", "", f"{ca.source}; {da.source}"))
    ndr = man.peek("step7.net_dollar_retention_pct")
    c.append(info("net_dollar_retention", "שימור הכנסה נטו (NDR), לתוכנה", fmt(ndr, "%"),
                  "manual step7.net_dollar_retention_pct",
                  ("120% or higher: existing customers keep spending more every year" if ndr is not None and ndr >= 120
                   else ""), assumptions=("A19",)))
    c.append(info("segments", "אילו מגזרים מניעים הכנסות, ואיך החברה זוכה בלקוחות",
                  man.peek("step7.revenue_segments_note") or "(empty)", "manual step7.revenue_segments_note",
                  "yfinance has no segment data"))
    return Step(7, "מנוע ההכנסות והיסטוריה של 5 שנים", "Revenue engine and 5-year history", c)


def step8(m, man, peers: dict):
    r = loan_ratios(m)
    c = []
    cov = r["coverage"]
    if cov.ok and cov.value == float("inf"):
        c.append(Check("interest_coverage", "כיסוי ריבית (רווח תפעולי / הוצאות ריבית)", PASS, "no interest expense",
                       ">= 4x", "", cov.source, cov.note, True, "4 to 10x", tuple(cov.assumptions)))
    else:
        ch = num_check("interest_coverage", "כיסוי ריבית (רווח תפעולי / הוצאות ריבית)", cov, ">=",
                       config.MIN_INTEREST_COVERAGE, unit="x", quote="4 to 10x")
        if cov.ok and cov.value > config.INTEREST_COVERAGE_RANGE_TOP:
            ch.note = (ch.note + " above the document's 4-10x range").strip()
        c.append(ch)
    a2l = num_check("assets_to_liabilities", "נכסים להתחייבויות, בלי מוניטין", r["assets_to_liabilities"], ">=",
                    config.MIN_ASSETS_TO_LIABILITIES, unit=":1", digits=2,
                    quote="Leave goodwill out of the assets. Real assets only.")
    if r["assets_to_liabilities"].ok and r["assets_to_liabilities"].value >= config.IDEAL_ASSETS_TO_LIABILITIES:
        a2l.note = (a2l.note + " ideal (3:1 or more)").strip()
    c.append(a2l)
    c.append(num_check("current_ratio", "יחס שוטף", r["current_ratio"], ">=", config.MIN_CURRENT_RATIO, unit="",
                       digits=2))
    de = r["debt_to_equity"]
    eq = de.meta.get("equity")
    if eq is not None and eq <= 0:
        c.append(Check("debt_to_equity", "התחייבויות להון עצמי", FAIL, f"equity {money(eq)}", "< 4x, equity > 0", "",
                       de.source, "negative equity", True, "a red flag"))
    else:
        c.append(num_check("debt_to_equity", "התחייבויות להון עצמי", de, "<", config.MAX_DEBT_TO_EQUITY, unit="x",
                           digits=2, quote="a red flag"))
    peer_list = man.peek("step8.peers") or []
    extra = {"peers": {}}
    if peer_list:
        for key, he, unit in (("coverage", "חציון עמיתים: כיסוי ריבית", "x"),
                              ("assets_to_liabilities", "חציון עמיתים: נכסים להתחייבויות", ":1"),
                              ("current_ratio", "חציון עמיתים: יחס שוטף", ""),
                              ("debt_to_equity", "חציון עמיתים: התחייבויות להון", "x")):
            vals = {}
            for p, pm in peers.items():
                if pm is None:
                    continue
                v = loan_ratios(pm)[key].value
                vals[p] = None if v == float("inf") else v
            med = valuation.peer_median(vals.values())
            extra["peers"][key] = vals
            c.append(info(f"peer_{key}", he, f"{fmt(med, unit, 2)} (stock {fmt(r[key].value if r[key].value != float('inf') else None, unit, 2)})",
                          "peers: " + ", ".join(f"{p} {fmt(v, unit, 2)}" for p, v in vals.items()),
                          quote="Always compare against peers in the same industry. A retailer will always look less "
                                "liquid because of its inventory."))
    return Step(8, "מבחן קצין ההלוואות", "Loan Officer Test", c, extra=extra)


def step9(m, man, s7: Step):
    c = []
    types = man.get("step9.types") or []
    note = "The best companies have more than one" if len(types) > 1 else ""
    c.append(Check("types", "לפחות אחד מששת סוגי החפיר", PASS if types else UNKNOWN, ", ".join(types) or "(none)",
                   ", ".join(config.MOAT_TYPES), "", "manual step9.types", note, True,
                   "Without a moat, revenue growth is irrelevant.", kind="manual"))
    mt = next((x for x in s7.checks if x.id == "margin_expanding"), None)
    c.append(manual_bool(man, "step9.getting_weaker", "החפיר נחלש עם הזמן", bad=True,
                         note=f"evidence, operating margin trend: {mt.value if mt else 'n/a'}"))
    c.append(manual_text(man, "step9.why_customers_stay", "למה לקוחות בוחרים, נשארים וחוזרים ב 10 השנים הבאות"))
    c.append(manual_bool(man, "step9.copyable_in_a_year", "מתחרה עם 20 מהנדסים על כל אחד שלך יעתיק את זה בשנה", bad=True))
    om = m.operating_margin()
    c.append(manual_bool(man, "step9.margin_proves_it", "המרווח התפעולי מוכיח את החפיר",
                         quote="Pricing power shows up there", note=f"TTM operating margin {fmt(om.value, '%')} ({om.source})"))
    return Step(9, "חפיר תחרותי", "Competitive moat", c)


def step10(m, man):
    c = []
    e = earnings_counts(m)
    act = m.insider_activity()
    items = [
        ("execution_track_record", "רקורד ביצוע: צמיחת הכנסות, מרווחים טובים יותר וחדשנות במשמרת שלו", ""),
        ("skin_in_the_game", "עור במשחק: קונה מניות בשוק הפתוח, לא רק אופציות",
         (f"hint: {act.value['open_market_purchases']} open-market purchases in 12 months "
          f"({money(act.value['shares_bought'])} shares)" if act.ok else "hint: no insider data")),
        ("ten_years_in_role", "10 שנים ומעלה בתפקיד, רצוי המייסד", ""),
        ("capital_allocation", "הקצאת הון ממושמעת: רכישה עצמית, חוב ורכישות", ""),
        ("straight_answers", "תשובות ישירות, גם כשהן לא נראות טוב", ""),
        ("consistent_beats", "עקביות בעקיפת תחזיות הרווח", ""),
        ("great_people_want_to_work", "מנהיג שאנשים טובים רוצים לעבוד אצלו", ""),
        ("results_not_excuses", "תוצאות, לא תירוצים", ""),
    ]
    trues = unknowns = 0
    for f, he, hint in items:
        if f == "consistent_beats":
            v = man.peek("step10.consistent_beats")
            auto = None if e["n4"] < 4 else e["beats4"] >= config.CONSISTENT_BEATS_MIN_OF_4
            ev = f"beats {e['beats4']}/{e['n4']} last 4, {e['beats8']}/{e['n8']} last 8"
            if v is None:
                if auto is None:
                    man.missing.append("step10.consistent_beats")
                ch = tri(f, he, auto, m.earnings_source(), value=ev, bad=False, required=False, assumptions=("A21",))
            else:
                ch = Check(f, he, PASS if v else FAIL, fmt(v), "true", "", "manual step10.consistent_beats",
                           f"auto: {ev}", False, kind="manual", raw=v)
        else:
            ch = manual_bool(man, f"step10.{f}", he, note=hint)
            ch.required = False
        c.append(ch)
        trues += ch.status == PASS
        unknowns += ch.status == UNKNOWN
    need = config.CEO_CHECKLIST_MIN
    st = PASS if trues >= need else (FAIL if trues + unknowns < need else UNKNOWN)
    c.append(Check("checklist", "רשימת 8 הבדיקות", st, f"{trues}/8 true, {unknowns} unknown", f">= {need} of 8",
                   f"{trues - need:+d}", "step 10 items", "", True, "I won't invest unless I'm amazed by the CEO.",
                   ("A6",)))
    c.append(manual_bool(man, "step10.clown_ceo", "דגל אדום: מנכ\"ל ליצן", bad=True))
    v = man.peek("step10.co_ceo")
    auto, src = co_ceo_auto(m)
    if v is None:
        if auto is None:
            man.missing.append("step10.co_ceo")
        c.append(tri("co_ceo", "דגל אדום: מבנה Co-CEO", auto, src))
    else:
        c.append(tri("co_ceo", "דגל אדום: מבנה Co-CEO", v, "manual step10.co_ceo", kind="manual",
                     note=f"auto: {fmt(auto)}"))
    c.append(manual_bool(man, "step10.acquisition_spree", "דגל אדום: מסע רכישות", bad=True,
                         note=f"hint: {acquisition_hint(m)}"))
    return Step(10, "הנהלה", "Management", c, quote="I won't invest unless I'm amazed by the CEO.")


def declining_margins(m: Metrics) -> Check:
    """A18: FAIL when margin fell both TTM vs prior TTM and latest FY vs previous; one = warning.
    When one comparison is unavailable, the other decides alone (data fallback rule)."""
    now, prior = m.ttm("revenue"), m.ttm("revenue", 4)
    op_now, op_prior = m.ttm("operating_income"), m.ttm("operating_income", 4)
    ttm_fell = None
    ttm_txt = "TTM vs prior TTM unavailable"
    if all(x.ok for x in (now, prior, op_now, op_prior)) and now.value and prior.value:
        a, b = pct(op_now.value, now.value), pct(op_prior.value, prior.value)
        ttm_fell = a < b
        ttm_txt = f"TTM {a:.1f}% vs prior {b:.1f}%"
    am = m.annual_margins()
    ann_fell = None
    ann_txt = "annual comparison unavailable"
    if len(am) >= 2:
        ann_fell = am[0][1] < am[1][1]
        ann_txt = f"FY{am[0][0][:4]} {am[0][1]:.1f}% vs FY{am[1][0][:4]} {am[1][1]:.1f}%"
    known = [x for x in (ttm_fell, ann_fell) if x is not None]
    note = ""
    if not known:
        st = UNKNOWN
    elif len(known) == 2:
        st = FAIL if all(known) else PASS
        note = "warning: margin fell on one of the two comparisons" if any(known) and not all(known) else ""
    else:
        st = FAIL if known[0] else PASS
        note = "only one comparison available; it decides alone"
    return Check("declining_margins", "דגל אדום: מרווחים יורדים", st, f"{ttm_txt}; {ann_txt}",
                 "not falling on both", "", "computed (quarterly + annual income statement)", note, True,
                 "Declining margins", ("A18",))


def inventory_check(m: Metrics) -> Check:
    rg = m.revenue_growth()
    name = "דגל אדום: הכנסות מזנקות בזמן שהמלאי נערם"
    q = "Revenue spiking while inventory piles up"
    if not rg.ok:
        return Check("inventory_pileup", name, UNKNOWN, "n/a", "", "", rg.source, "", True, q, ("A9",))
    if round(rg.value, 6) <= config.INVENTORY_SPIKE_REV_GROWTH_PCT:
        return Check("inventory_pileup", name, PASS, f"revenue growth {fmt(rg.value, '%')}", "revenue growth <= 30%, or "
                     "inventory growth <= revenue growth", "", rg.source, "no revenue spike", True, q, ("A9",))
    basis = rg.meta.get("basis")
    inv_q, inv_a = m.series("inventory", "q"), m.series("inventory", "a")
    ig, src = None, ""
    if basis == "ttm" and inv_q.ok and len(inv_q.value) >= 5:
        ig, src = growth_pct(inv_q.value[0][1], inv_q.value[4][1]), f"{inv_q.source} {inv_q.value[0][0]} vs {inv_q.value[4][0]}"
    elif inv_a.ok and len(inv_a.value) >= 2:
        ig, src = growth_pct(inv_a.value[0][1], inv_a.value[1][1]), f"{inv_a.source} FY {inv_a.value[0][0]} vs previous"
    elif inv_q.meta.get("absent") and (inv_a.meta.get("absent") or not inv_a.ok):
        return Check("inventory_pileup", name, PASS, "no inventory reported", "", "", inv_q.source,
                     "no Inventory line in any period (A22)", True, q, ("A9", "A22"))
    if ig is None:
        return Check("inventory_pileup", name, UNKNOWN, f"revenue {fmt(rg.value, '%')}, inventory n/a", "", "",
                     inv_q.source, "", True, q, ("A9",))
    return Check("inventory_pileup", name, FAIL if round(ig, 6) > round(rg.value, 6) else PASS,
                 f"revenue {fmt(rg.value, '%')} vs inventory {fmt(ig, '%')}", "inventory growth <= revenue growth",
                 f"{rg.value - ig:+.1f} pp", f"{rg.source}; {src}", "", True, q, ("A9",))


def step11(m, man, s2: Step):
    c = []
    reasons = man.peek("step11.bear_reasons") or []
    n = len([r for r in reasons if str(r).strip()])
    if n < config.BEAR_REASONS_MIN:
        man.missing.append("step11.bear_reasons")
    c.append(Check("bear_reasons", "3 עד 5 סיבות כתובות למה התזה שגויה", PASS if n >= config.BEAR_REASONS_MIN else UNKNOWN,
                   f"{n} reasons", ">= 3", f"{n - config.BEAR_REASONS_MIN:+d}", "manual step11.bear_reasons",
                   "", True, "3 to 5 reasons the thesis is wrong", kind="manual", raw=n))
    rb = man.get("step11.read_bear_analysis")
    c.append(Check("read_bear_analysis", "קראתי את הניתוח הדובי", PASS if rb else UNKNOWN, fmt(rb), "true", "",
                   "manual step11.read_bear_analysis", "" if rb else "read it first", True, kind="manual"))
    if rb is False and "step11.read_bear_analysis" not in man.missing:
        man.missing.append("step11.read_bear_analysis")
    c.append(manual_text(man, "step11.bear_case", "תרחיש דובי קצר במילים פשוטות"))
    c.append(manual_bool(man, "step11.can_live_with_it", "אני יכול לחיות עם זה?", quote="Can I live with it? If not, it's out"))
    c.append(manual_bool(man, "step11.fraud_or_accounting_suspicion", "דגל אדום: הונאה או שערוריית חשבונאות, אפילו חשד",
                         bad=True))
    c.append(manual_bool(man, "step11.auditor_change", "דגל אדום: החלפת רואה חשבון מבקר", bad=True))
    c.append(declining_margins(m))
    ih = insider_hint(m)
    c.append(manual_bool(man, "step11.insiders_selling_hard", "דגל אדום: בעלי עניין מוכרים בכבדות בזמן שהמניה רצה",
                         bad=True, note=f"hint (A7): {fmt(ih.value)}; {ih.note or ih.source}"))
    c.append(manual_bool(man, "step10.acquisition_spree", "דגל אדום: התרחבות יתר או מסע רכישות", bad=True,
                         note=f"hint: {acquisition_hint(m)}"))
    c[-1].id = "over_expansion"
    c.append(inventory_check(m))

    # hype trap: all four at once = FAIL
    rev = m.ttm_or_fallback("revenue")
    no_rev = (not rev.ok) or rev.value == 0
    weak = {FAIL: True, PASS: False}.get(s2.status)
    ss = share_sales(m)
    auto = [no_rev, weak, ss.value]
    hype = None
    if all(x is not False for x in auto):
        hype = man.get("step11.nonstop_media_hype")
    else:
        hype = man.peek("step11.nonstop_media_hype")
    four = auto + [hype]
    st = FAIL if all(x is True for x in four) else (PASS if any(x is False for x in four) else UNKNOWN)
    desc = (f"no revenue: {fmt(no_rev)} ({rev.source}); weak fundamentals (step 2 {s2.status}): {fmt(weak)}; "
            f"constant share sales: {fmt(ss.value)} ({ss.note or ss.source}); nonstop media hype: {fmt(hype)}")
    c.append(Check("hype_trap", "מלכודת הייפ: ארבעתם יחד", st, desc, "not all four", "", "computed + manual",
                   "", True, "All four at once? Run.", ("A10",)))
    return Step(11, "להרוס משהו יפה", "Destroy something beautiful", c,
                quote="By now you like this stock. That's exactly when you're most dangerous to yourself.")


def step12(m, man, s3: Step, peers: dict, btype: M):
    c = []
    vals: dict = {"cases": {}, "reverse": None, "multiple": None, "peg": None}
    price, shares, mc = m.price(), m.shares_outstanding(), m.market_cap()
    rev = m.annual("revenue", config.DCF_AVG_YEARS + 1)
    fcf = m.annual("fcf", config.DCF_AVG_YEARS)
    cash, debt = m.latest("cash"), m.latest("debt")
    n_avg = config.DCF_AVG_YEARS
    base_rev = avg_growth = avg_margin = None
    why_na = []
    if rev.ok and len(rev.value) >= n_avg:
        base_rev = sum(v for _, v in rev.value[:n_avg]) / n_avg
        gs = [growth_pct(rev.value[i][1], rev.value[i + 1][1]) for i in range(min(n_avg, len(rev.value) - 1))]
        gs = [g for g in gs if g is not None]
        if len(gs) >= 2:
            avg_growth = sum(gs) / len(gs) / 100
        else:
            why_na.append("fewer than 2 annual growth rates")
        if fcf.ok:
            rm = dict(rev.value)
            ms = [v / rm[d] for d, v in fcf.value if d in rm and rm[d]]
            if len(ms) >= n_avg:
                avg_margin = sum(ms[:n_avg]) / n_avg
            else:
                why_na.append(f"FCF margin for only {len(ms)} fiscal years")
        else:
            why_na.append("no annual FCF")
    else:
        why_na.append(f"needs {n_avg} fiscal years of revenue")
    for x, label in ((price, "price"), (shares, "shares"), (cash, "cash"), (debt, "debt")):
        if not x.ok:
            why_na.append(f"no {label}")
    if not m.fx_ok:
        why_na.append(m.fx_note)
    trim = man.peek("step12.growth_trim_override")
    trim = config.GROWTH_TRIM if trim is None else trim
    vals.update(base_revenue=base_rev, avg_growth=avg_growth, avg_fcf_margin=avg_margin, trim=trim,
                years_used=len(rev.value) if rev.ok else 0)
    c.append(info("inputs", "12.01 ממוצע 3 שנים: הכנסות, צמיחה, מרווח FCF",
                  f"revenue {money(base_rev)}, growth {fmt(avg_growth * 100 if avg_growth is not None else None, '%')}, "
                  f"FCF margin {fmt(avg_margin * 100 if avg_margin is not None else None, '%')}",
                  f"{rev.source}; {fcf.source}", assumptions=("A17",)))
    dcf_applies = not why_na and avg_margin is not None and avg_margin > 0
    bear_ok = None
    if avg_margin is not None and avg_margin <= 0:
        c.append(info("dcf", "DCF", "N/A", "", "3-year average FCF margin is zero or negative: the DCF is not meaningful"))
    elif why_na:
        c.append(info("dcf", "DCF", "n/a", "", "; ".join(why_na)))
    if dcf_applies:
        g = avg_growth * (1 - trim) if avg_growth > 0 else avg_growth
        gnote = f"{avg_growth:.1%} trimmed {trim:.0%} -> {g:.1%}" if avg_growth > 0 else \
            f"{avg_growth:.1%} (negative, not trimmed toward zero)"
        for case, rate in (("bull", config.DCF_RATE_BULL), ("base", config.DCF_RATE_BASE), ("bear", config.DCF_RATE_BEAR)):
            r = valuation.dcf(base_rev, g, avg_margin, rate, cash.value, debt.value, shares.value)
            r["upside"] = r["per_share"] / price.value - 1
            r["mc_upside"] = r["equity"] / mc.value - 1 if mc.ok else None
            vals["cases"][case] = r
            c.append(info(f"dcf_{case}", f"DCF {case} ({rate:.0%})", f"{fmt(r['per_share'], '', 2)} vs price "
                          f"{fmt(price.value, '', 2)} ({r['upside']:+.1%})", f"growth {gnote}; terminal 4%",
                          raw=r["per_share"], assumptions=("A11", "A16", "A17")))
        bear = vals["cases"]["bear"]
        bear_ok = bear["per_share"] >= price.value
        c.append(Check("bear_case_attractive", "גם התרחיש הדובי מושך: ערך למניה בתרחיש דובי >= מחיר היום",
                       PASS if bear_ok else FAIL, f"{fmt(bear['per_share'], '', 2)} vs {fmt(price.value, '', 2)}",
                       ">= price", f"{bear['upside']:+.1%}", f"DCF bear 12%; price {price.source}", "", True,
                       "Even the bear case has to be attractive", raw=bear["per_share"]))
        if mc.ok:
            implied_mc = shares.value * price.value
            gap = implied_mc / mc.value - 1
            flag = abs(gap) > config.CROSS_CHECK_TOLERANCE
            vals["cross_check"] = {"equity": vals["cases"]["base"]["equity"], "market_cap": mc.value, "gap": gap, "flag": flag}
            c.append(info("cross_check", "בדיקה צולבת: שווי הון מול שווי שוק",
                          f"base equity {money(vals['cases']['base']['equity'])} vs market cap {money(mc.value)} "
                          f"({vals['cases']['base']['mc_upside']:+.1%}); shares x price vs market cap {gap:+.1%}",
                          f"{shares.source}; {mc.source}",
                          "DISAGREEMENT above 10%: per-share result may be wrong (ADR ratio or share classes)" if flag else ""))
        # Part 1: reverse DCF
        ig, note = valuation.reverse_dcf(price.value, base_rev, avg_margin, config.DCF_RATE_BASE, cash.value,
                                         debt.value, shares.value)
        if ig is not None:
            gap = avg_growth - ig
            vals["reverse"] = {"implied": ig, "delivered": avg_growth, "gap": gap, "note": note}
            c.append(info("reverse_dcf", "DCF הפוך: הצמיחה שמגולמת במחיר",
                          f"implied {ig:.1%} vs delivered {avg_growth:.1%} (3y avg): gap {gap:+.1%}",
                          "bisection on the base-rate model", note, quote="The gap is where you make money."))

    # Part 3: the right multiple
    bt = btype.value
    fpe = m.info.get("forwardPE")
    peer_list = man.peek("step8.peers") or []
    mult_status = None
    if bt in ("mature", "hardware", "bank"):
        pv = {p: (pm.info.get("forwardPE") if pm else None) for p, pm in peers.items()}
        med = valuation.peer_median(pv.values())
        if peer_list and fpe is not None and med is not None:
            mult_status = PASS if fpe <= med else FAIL
        vals["multiple"] = {"type": "forward P/E vs peer median", "value": fpe, "peers": pv, "benchmark": med}
        c.append(info("multiple", "המכפיל הנכון: Forward P/E מול חציון העמיתים",
                      f"{fmt(fpe, 'x')} vs median {fmt(med, 'x')}", "info.forwardPE; " +
                      ", ".join(f"{p} {fmt(v, 'x')}" for p, v in pv.items()), "no peers in step8.peers" if not peer_list else "",
                      quote="Forward PE is life", assumptions=("A23",)))
    elif bt in ("software", "subscription"):
        r40 = next((x for x in s3.checks if x.id == "rule_of_40"), None)
        r40v = r40.raw if r40 else None
        if r40v is not None:
            mult_status = PASS if round(r40v, 6) >= config.RULE_OF_40 else FAIL
        vals["multiple"] = {"type": "Rule of 40", "value": r40v}
        c.append(info("multiple", "המכפיל הנכון: Rule of 40", fmt(r40v, ""), "step 3 test A",
                      quote="tells you more than PE"))
    elif bt == "early_growth":
        def ps(mm):
            v = mm.info.get("priceToSalesTrailing12Months")
            if v is None:
                r, mcap = mm.ttm_or_fallback("revenue"), mm.market_cap()
                v = mcap.value / r.value if r.ok and mcap.ok and r.value and mm.fx_ok else None
            return v
        own = ps(m)
        pv = {p: (ps(pm) if pm else None) for p, pm in peers.items()}
        avg = valuation.peer_mean(pv.values())
        if peer_list and own is not None and avg is not None:
            mult_status = PASS if own <= avg else FAIL
        vals["multiple"] = {"type": "P/S vs peer average", "value": own, "peers": pv, "benchmark": avg}
        c.append(info("multiple", "המכפיל הנכון: מכפיל מכירות מול ממוצע העמיתים", f"{fmt(own, 'x')} vs avg {fmt(avg, 'x')}",
                      ", ".join(f"{p} {fmt(v, 'x')}" for p, v in pv.items()) or "no peers",
                      "" if peer_list else "no peers in step8.peers", assumptions=("A23",)))
    else:
        c.append(info("multiple", "המכפיל הנכון", "n/a", btype.source, f"business model: {bt}"))

    # PEG
    ge = (m.raw.get("growth_estimates") or {}).get("values", {})
    eg, eg_src = None, ""
    for k in ("+5y", "LTG"):
        if ge.get(k) is not None:
            eg, eg_src = ge[k] * 100, f"growth_estimates {k}"
            break
    if eg is None:
        fe, te = m.info.get("forwardEps"), m.info.get("trailingEps")
        if fe is not None and te and te > 0:
            eg, eg_src = (fe / te - 1) * 100, "forwardEps / trailingEps - 1"
    peg = fpe / eg if fpe and fpe > 0 and eg and eg > 0 else None
    vals["peg"] = {"peg": peg, "growth": eg, "source": eg_src, "label": valuation.peg_label(peg),
                   "trailingPegRatio": m.info.get("trailingPegRatio")}
    c.append(info("peg", "PEG = Forward P/E / צמיחת EPS", f"{fmt(peg, '', 2)} {valuation.peg_label(peg) or ''}".strip(),
                  f"forward P/E {fmt(fpe, 'x')}; EPS growth {fmt(eg, '%')} ({eg_src or 'n/a'}); "
                  f"yfinance trailingPegRatio {fmt(m.info.get('trailingPegRatio'), '', 2)}",
                  assumptions=("A12",) if peg is not None and 1 < peg <= 2 else ()))

    # step 12 status: bear-case test when the DCF applies, else the multiple, else UNKNOWN
    if bear_ok is None:
        st = mult_status or UNKNOWN
        c.append(Check("valuation_status", "סטטוס הערכת שווי (ללא DCF)", st,
                       vals["multiple"]["type"] if vals["multiple"] else "n/a", "multiple at or below peers / Rule of 40 >= 40",
                       "", "step 12 part 3", "" if mult_status else
                       ("add step8.peers" if not peer_list else "multiple not available"), True,
                       assumptions=("A23",)))
        if st == UNKNOWN and not peer_list and bt not in ("software", "subscription"):
            man.missing.append("step8.peers")
    return Step(12, "הערכת שווי", "Valuation", c,
                quote="You can get the thesis 100% right and still lose money if you overpay.",
                notes=["Cisco: revenue from $2B to $60B, and peak buyers still down 23% twenty-five years later."],
                extra={"valuation": vals})


# ------------------------------------------------------------------ the whole run for one ticker
def evaluate(ticker: str, m: Metrics, man, spy_hist: dict, peers: dict | None = None) -> Result:
    peers = peers or {}
    mcap_usd = m.market_cap_usd()
    btype = business_type(m, man)
    s1 = step1(m, man, mcap_usd)
    s2 = step2(m, man)
    s7 = step7(m, man)
    s9 = step9(m, man, s7)
    s3 = step3(m, man, mcap_usd, s9, btype)
    s4 = step4(m, man)
    s5 = step5(m, man)
    s6 = step6(m, man, spy_hist)
    s8 = step8(m, man, peers)
    s10 = step10(m, man)
    s11 = step11(m, man, s2)
    s12 = step12(m, man, s3, peers, btype)
    steps = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12]

    eliminated = next((s.n for s in steps if s.status == FAIL), None)
    if eliminated:
        verdict = f"ELIMINATED AT STEP {eliminated}"
    elif any(s.status == UNKNOWN for s in steps):
        verdict = "INCOMPLETE"
    else:
        verdict = "SURVIVED ALL 12"

    asm = sorted({a for s in steps for ch in s.checks for a in ch.assumptions},
                 key=lambda x: int(x[1:]))
    autos = [ch for s in steps for ch in s.checks if ch.kind == "auto" and ch.status != INFO]
    completeness = 100.0 * sum(ch.status != UNKNOWN for ch in autos) / len(autos) if autos else 0.0
    notes = [n for s in steps for n in s.notes if n.startswith("Inconsistency")]
    if m.fx_note:
        notes.append(m.fx_note)
    price = m.price()
    header = {
        "name": m.info.get("longName") or m.info.get("shortName") or ticker,
        "price": price.value, "price_source": price.source,
        "currency": m.info.get("currency") or m.fast.get("currency"),
        "market_cap": m.market_cap().value, "market_cap_usd": mcap_usd.value,
        "quote_time": m.quote_time().value, "market_open": m.market_open().value,
        "market_state": m.info.get("marketState"),
        "fetched_at": m.raw.get("fetched_at"), "cache": m.raw.get("cache"),
        "sector": m.info.get("sector"), "industry": m.info.get("industry"), "country": m.info.get("country"),
        "business_model": btype.value, "business_model_source": btype.source,
        "fx": m.fx_block,
    }
    if "A8" not in asm:
        asm.append("A8")
    return Result(ticker, steps, verdict, eliminated, header, sorted(set(man.missing), key=man.missing.index),
                  man.errors, asm, notes, list(m.raw.get("errors") or []), completeness,
                  s6.extra["scorecard"], s12.extra["valuation"])
