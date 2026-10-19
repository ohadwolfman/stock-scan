"""Synthetic raw dicts in the exact shape fetch.Fetcher produces. Test-only numbers, not market data."""
import copy
import datetime as dt

Q = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"]
A = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
B = 1e9

TODAY = dt.date(2026, 10, 18)
NOW = dt.datetime(2026, 10, 18, 22, 0, tzinfo=dt.timezone.utc)


def stmt(cols, rows):
    return {"columns": list(cols), "rows": {k: list(v) for k, v in rows.items()}}


def daily(start_price, end_price, years=6, end=dt.date(2026, 10, 16)):
    start = end - dt.timedelta(days=int(365.25 * years))
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    n = len(days) - 1
    return {d.isoformat(): start_price + (end_price - start_price) * i / n for i, d in enumerate(days)}


def good_raw():
    qrev = [130, 125, 120, 115, 100, 96, 92, 88]
    qmargin = [0.45] * 4 + [0.40] * 4
    arev = [460, 360, 280, 220]
    amargin = [0.44, 0.40, 0.36, 0.30]
    return {
        "ticker": "GOODCO", "fetched_at": "2026-10-18T22:00:00+00:00", "errors": [], "cache": "miss",
        "info": {"longName": "Good Co (synthetic)", "shortName": "Good Co", "currency": "USD",
                 "financialCurrency": "USD", "marketCap": 50 * B, "sharesOutstanding": 1 * B, "currentPrice": 50.0,
                 "shortPercentOfFloat": 0.02, "heldPercentInstitutions": 0.75, "country": "United States",
                 "sector": "Technology", "industry": "Software - Infrastructure", "forwardPE": 30.0,
                 "trailingPegRatio": 1.5, "forwardEps": 2.2, "trailingEps": 2.0, "revenueGrowth": 0.30,
                 "operatingMargins": 0.45, "regularMarketTime": 1792353600, "exchangeTimezoneName": "America/New_York",
                 "companyOfficers": [{"name": "Jane Founder", "title": "Founder & CEO"}],
                 "longBusinessSummary": "Synthetic company used by the unit tests."},
        "fast": {"last_price": 50.0, "market_cap": 50 * B, "currency": "USD"},
        "q_income": stmt(Q, {"Total Revenue": [v * B for v in qrev],
                             "Operating Income": [v * B * m for v, m in zip(qrev, qmargin)],
                             "Net Income": [v * B * 0.3 for v in qrev],
                             "Interest Expense": [1 * B] * 8}),
        "q_balance": stmt(Q, {"Cash Cash Equivalents And Short Term Investments": [50 * B] * 8,
                              "Total Debt": [10 * B] * 8, "Total Assets": [200 * B] * 8, "Goodwill": [10 * B] * 8,
                              "Total Liabilities Net Minority Interest": [60 * B] * 8,
                              "Current Assets": [90 * B] * 8, "Current Liabilities": [30 * B] * 8,
                              "Stockholders Equity": [140 * B] * 8, "Ordinary Shares Number": [1 * B] * 8}),
        "q_cashflow": stmt(Q, {"Free Cash Flow": [v * B * 0.35 for v in qrev]}),
        "a_income": stmt(A, {"Total Revenue": [v * B for v in arev],
                             "Operating Income": [v * B * m for v, m in zip(arev, amargin)],
                             "Net Income": [v * B * 0.3 for v in arev], "Interest Expense": [4 * B] * 4}),
        "a_balance": stmt(A, {"Cash Cash Equivalents And Short Term Investments": [50 * B, 40 * B, 30 * B, 20 * B],
                              "Total Debt": [10 * B] * 4, "Total Assets": [200 * B] * 4, "Goodwill": [10 * B] * 4,
                              "Total Liabilities Net Minority Interest": [60 * B] * 4,
                              "Stockholders Equity": [140 * B] * 4,
                              "Ordinary Shares Number": [1.00 * B, 1.01 * B, 1.02 * B, 1.03 * B]}),
        "a_cashflow": stmt(A, {"Free Cash Flow": [v * B * m for v, m in zip(arev, [0.34, 0.32, 0.30, 0.28])],
                               "Purchase Of Business": [0, 0, -1 * B, 0]}),
        "earnings": {"source": "get_earnings_dates",
                     "rows": [{"date": d, "estimate": 1.0, "reported": 1.1} for d in
                              ["2026-07-28", "2026-04-28", "2026-01-28", "2025-10-28", "2025-07-28", "2025-04-28",
                               "2025-01-28", "2024-10-28"]] + [{"date": "2026-11-01", "estimate": 1.2, "reported": None}]},
        "insider_transactions": [{"date": "2026-03-01", "shares": 10000, "value": 500000,
                                  "text": "Purchase at price 50.00 per share.", "insider": "Jane Founder",
                                  "position": "CEO"}],
        "insider_purchases": {}, "major_holders": {},
        "growth_estimates": {"column": "stockTrend", "values": {"+5y": 0.2}},
        "history": daily(10, 50),
        "first_trade_date": "2005-03-01",
        "fx": {"trading_currency": "USD", "financial_currency": "USD", "trade_major": "USD", "subunit_factor": 1},
    }


def good_manual():
    return {
        "founding_year": 2001, "business_model_type": "software",
        "skip_zones": {"seasonal": False},
        "step1": {"trend_name": "AI infrastructure", "paying_customers": True, "sustainable_growth": True,
                  "moat_not_commodity": True, "regulatory_tailwind": True, "real_world_adoption": True,
                  "built_for_trend": True, "market_story": "story", "what_it_is_becoming": "becoming", "has_gap": True},
        "step3": {"ceo_team_track_record": True, "no_regulatory_legal_overhang": True},
        "step4": {"provides": "X", "helps": "Y", "achieve": "Z", "charges": "subscriptions", "sentence_clean": True,
                  "pain": "p", "who_and_why": "w", "why_us": "u"},
        "step5": {"broad_market": True, "checked_market_size_myself": True, "market_big_enough": True},
        "step6": {"moat": 10, "ceo": 10, "recession_proof_pricing_power": 5, "secular_trend": 10,
                  "culture_mission": 5, "talent": 10},
        "step9": {"types": ["switching_costs", "scale"], "getting_weaker": False, "why_customers_stay": "because",
                  "copyable_in_a_year": False, "margin_proves_it": True},
        "step10": {"execution_track_record": True, "skin_in_the_game": True, "ten_years_in_role": True,
                   "capital_allocation": True, "straight_answers": True, "great_people_want_to_work": True,
                   "results_not_excuses": True, "clown_ceo": False, "acquisition_spree": False},
        "step11": {"bear_reasons": ["a", "b", "c"], "read_bear_analysis": True, "bear_case": "bear",
                   "can_live_with_it": True, "fraud_or_accounting_suspicion": False, "auditor_change": False,
                   "insiders_selling_hard": False},
    }


def clone(x):
    return copy.deepcopy(x)


SPY = daily(100, 180)
