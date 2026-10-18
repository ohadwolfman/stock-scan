"""Step 12: the 10-20 minute DCF, the reverse DCF, the right multiple and PEG."""
from __future__ import annotations

import statistics

import config

TERMINAL_GROWTH = 0.04  # 12.04: fixed, not configurable. "That's a rule you don't break."


def dcf(base_revenue, growth, fcf_margin, rate, cash, debt, shares, years=config.DCF_YEARS):
    """Project revenue x FCF margin for `years`, discount at `rate`, Gordon terminal value at 4%,
    add cash, subtract debt, divide by shares. growth and margin are fractions."""
    if rate <= TERMINAL_GROWTH:
        raise ValueError("discount rate must exceed terminal growth")
    flows, pv = [], 0.0
    rev = base_revenue
    for t in range(1, years + 1):
        rev = rev * (1 + growth)
        fcf = rev * fcf_margin
        disc = fcf / (1 + rate) ** t
        flows.append({"year": t, "revenue": rev, "fcf": fcf, "pv": disc})
        pv += disc
    tv = flows[-1]["fcf"] * (1 + TERMINAL_GROWTH) / (rate - TERMINAL_GROWTH)
    pv_tv = tv / (1 + rate) ** years
    ev = pv + pv_tv
    equity = ev + cash - debt
    return {"flows": flows, "pv_fcf": pv, "terminal": tv, "pv_terminal": pv_tv, "ev": ev,
            "equity": equity, "per_share": equity / shares, "rate": rate, "growth": growth}


def reverse_dcf(price, base_revenue, fcf_margin, rate, cash, debt, shares,
                lo=config.REVERSE_DCF_BOUNDS[0], hi=config.REVERSE_DCF_BOUNDS[1], tol=1e-7):
    """Constant 5-year revenue growth that makes value per share equal price (bisection).
    Returns (growth, note). Value is increasing in growth when the FCF margin is positive."""
    if fcf_margin <= 0:
        return None, "FCF margin not positive: reverse DCF not meaningful"

    def f(g):
        return dcf(base_revenue, g, fcf_margin, rate, cash, debt, shares)["per_share"] - price

    flo, fhi = f(lo), f(hi)
    if flo > 0:
        return lo, f"even {lo:.0%} growth gives a value above the price"
    if fhi < 0:
        return hi, f"even {hi:.0%} growth gives a value below the price"
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < tol or hi - lo < tol:
            return mid, ""
        if fm < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, ""


def peg_label(peg):
    if peg is None:
        return None
    if peg < config.PEG_UNDERVALUED:
        return "undervalued"
    if peg == config.PEG_UNDERVALUED:
        return "fair"
    if peg > config.PEG_VERY_EXPENSIVE:
        return "very expensive"
    return "between fair and very expensive"  # A12


def peer_median(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def peer_mean(values):
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else None
