"""Every threshold of Tom Nash's 12-step process, each tagged with its step.

Values the document defines are marked with their step. Values the document leaves undefined
are ASSUMPTIONS (A1-A19 from the build spec, A20+ added during implementation). Every check
that relies on an assumption records its id, and the report prints the text of each one used.
"""

# ---------------------------------------------------------------- data access
CACHE_DIR = "cache"
REPORTS_DIR = "reports"
MANUAL_FILE = "nash_manual.yaml"
HISTORY_PERIOD = "6y"            # 5+ years of daily prices (step 6 category 7)
EARNINGS_DATES_LIMIT = 16        # enough rows for the last 8 reported quarters
RETRY_ATTEMPTS = 4
RETRY_BASE_SECONDS = 2.0         # backoff 2s, 4s, 8s
BENCHMARK = "SPY"

# Sub-unit trading currencies: (major currency, units per major unit)
CURRENCY_SUBUNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ILA": ("ILS", 100), "ZAc": ("ZAR", 100)}

# A8. Market open/closed detection: regular session in the exchange's local time zone.
DEFAULT_EXCHANGE_TZ = "America/New_York"
MARKET_OPEN_HHMM = (9, 30)
MARKET_CLOSE_HHMM = (16, 0)

# ---------------------------------------------------------------- step 1
SMALL_CAP_SKIP_USD = 2e9                                  # A1
CHINESE_COUNTRIES = {"China", "Hong Kong", "Macau"}       # A2
AIRLINE_INDUSTRY_KEYWORD = "Airlines"                     # step 1 skip zone (auto)
COMMODITY_INDUSTRIES = {                                  # A3
    "Gold", "Silver", "Copper", "Steel", "Aluminum",
    "Other Industrial Metals & Mining", "Other Precious Metals & Mining",
    "Oil & Gas E&P", "Oil & Gas Integrated", "Oil & Gas Drilling",
    "Coking Coal", "Thermal Coal", "Uranium", "Agricultural Inputs",
    "Farm Products", "Lumber & Wood Production",
}
MIN_COMPANY_AGE_YEARS = 10       # step 1 startup skip zone and step 3 instant kill

# ---------------------------------------------------------------- step 2
REVENUE_RISE_YEARS = 3           # A4. "Revenue has grown for the past few years"
STEP2_VALID_REASONS = ("infrastructure_leverage", "path_to_profitability")

# ---------------------------------------------------------------- step 3
PRESCREEN_MIN_QUARTERS = 4       # "each of the last 4 to 6 quarters"
PRESCREEN_MAX_QUARTERS = 6
MIN_REVENUE_GROWTH_PCT = 10.0    # "Revenue growing 10% or more"; instant kill below 10% and falling
RULE_OF_40 = 40.0                # Test A. 40 = "the perfect company"; below 40 = pass on it
RULE_OF_40_SHUTS_UP = 100.0      # above 100 "basically shuts everybody up"
RULE_OF_40_REQUIRED_TYPES = ("software", "subscription")   # A15
MIN_MARKET_CAP_USD = 1e9         # instant kill: market cap under $1 billion
MAX_SHORT_INTEREST_PCT = 10.0    # instant kill: short interest above 10%
MIN_OPERATING_MARGIN_PCT = 20.0  # instant kill: operating margin below 20%
MAX_EARNINGS_MISSES = 2          # instant kill: 2 or more misses in the last 4 quarters
SCALABILITY_EXAMPLES = [         # Test B examples: (label, revenue growth %, expense growth %)
    ("Bad", 120.0, 250.0), ("Good", 25.0, 13.0), ("Phenomenal", 21.6, 1.5),
]

# ---------------------------------------------------------------- step 6
SCORE_REV_GROWTH_BANDS = (10.0, 20.0)     # below 10 = 0, 10..20 = 5, above 20 = 10
SCORE_OP_MARGIN_BANDS = (10.0, 25.0)      # below 10 = 0, 10..25 = 5, above 25 = 10
SCORE_SHORT_BANDS = (5.0, 10.0)           # above 10 = 0, 5..10 = 5, below 5 = 10
SCORE_INST_BANDS = (30.0, 60.0)           # below 30 = 0, 30..60 = 5, above 60 = 10
SCORE_CASH_DEBT_STRONG = 2.0              # 2x+ cash vs debt = 10
SCORE_5Y_BANDS = (10.0, 20.0)             # beat by 10..20 = 5, 20+ = 10 (0..10 = 0, A13)
SCORE_MAX = 130                           # 13 x 10 (the document calls it 125)
SCORE_EXCEPTIONAL = 100                   # 100-125 "Exceptional. Once in a lifetime."
SCORE_WATCHLIST = 75                      # 75-100 "Watchlist. Investable."; below = no-go
MANUAL_SCORE_VALUES = (0, 5, 10)

# ---------------------------------------------------------------- step 7
ANNUAL_YEARS = 5                 # "five years from the 10-K"
MARGIN_MAX_DOWN_YEARS = 1        # A5
MATURING_GROWTH_PCT = 10.0       # A20. "slowing toward single digits"

# ---------------------------------------------------------------- step 8
MIN_INTEREST_COVERAGE = 4.0      # "4 to 10x"; above 10x still passes (A-note 6)
INTEREST_COVERAGE_RANGE_TOP = 10.0
MIN_ASSETS_TO_LIABILITIES = 2.0  # 2:1 minimum
IDEAL_ASSETS_TO_LIABILITIES = 3.0
MIN_CURRENT_RATIO = 1.0
MAX_DEBT_TO_EQUITY = 4.0         # 4x or more = "a red flag"

# ---------------------------------------------------------------- step 9
MOAT_TYPES = ("network_effects", "technology_patents", "switching_costs", "scale", "regulation", "brand")

# ---------------------------------------------------------------- step 10
CEO_CHECKLIST_MIN = 8            # A6. "amazed by the CEO": all 8
CONSISTENT_BEATS_MIN_OF_4 = 4    # A21. auto "consistent earnings beats": beats in each of the last 4
CO_CEO_PATTERNS = ("co-ceo", "co-chief executive")

# ---------------------------------------------------------------- step 11
BEAR_REASONS_MIN = 3             # "3 to 5 reasons"
INSIDER_NET_SELL_PCT = 1.0       # A7
INSIDER_RUN_RETURN_PCT = 50.0    # A7
INVENTORY_SPIKE_REV_GROWTH_PCT = 30.0   # A9
INVENTORY_TOLERANCE_PP = 10.0            # A9: inventory must outgrow revenue by more than this
SHARE_SALES_YEARS = 3            # A10
SHARE_SALES_TOTAL_PCT = 5.0      # A10

# ---------------------------------------------------------------- step 12
DCF_YEARS = 5
DCF_AVG_YEARS = 3                # 12.01 / A17
DCF_RATE_BASE = 0.10             # 12.03
DCF_RATE_BULL = 0.08
DCF_RATE_BEAR = 0.12
# 12.04 terminal growth 4% is fixed in valuation.TERMINAL_GROWTH: "That's a rule you don't break."
GROWTH_TRIM = 0.25               # A11
CROSS_CHECK_TOLERANCE = 0.10     # equity value vs market cap disagreement flag
PEG_UNDERVALUED = 1.0
PEG_VERY_EXPENSIVE = 2.0
REVERSE_DCF_BOUNDS = (-0.95, 5.0)
BUSINESS_MODEL_TYPES = ("software", "subscription", "mature", "hardware", "bank", "early_growth", "other")
HARDWARE_INDUSTRY_KEYWORDS = ("Semiconductor", "Computer Hardware", "Communication Equipment",
                              "Electronic Components", "Consumer Electronics",
                              "Scientific & Technical Instruments")

# ---------------------------------------------------------------- texts
FIVE_RULES = [
    ("i", "Great company, fair price", "business quality first, valuation second."),
    ("ii", "Cash is fact", '"Profit is an opinion of an accountant."'),
    ("iii", "Blend the story and the numbers", "one without the other doesn't cut it."),
    ("iv", "Probable over possible", "bet on what's likely, not on what could happen."),
    ("v", "Avoid losers first", '"Even the best investors are only right about 60% of the time."'),
]

ASSUMPTIONS = {
    "A1": "Small-cap skip zone: market cap under $2B (the document only defines the $1B instant kill).",
    "A2": "Chinese companies: info.country in {China, Hong Kong, Macau}.",
    "A3": "Commodity industries: " + "; ".join(sorted(COMMODITY_INDUSTRIES)) + ".",
    "A4": "'The past few years' in step 2: annual revenue rose in each of the last 3 fiscal years.",
    "A5": "'Expanding' operating margin: latest year above the first year of the window, with at most one down year.",
    "A6": "Step 10 requires all 8 checklist items ('amazed by the CEO'); configurable minimum count.",
    "A7": "Hint for insiders selling hard: net insider selling above 1% of shares outstanding in 12 months "
          "while the 12-month return is above 50%. Hint only; FAIL comes from the manual confirmation.",
    "A8": "Market open/closed: regular session 09:30-16:00 in the exchange time zone "
          "(info.exchangeTimezoneName, default US Eastern), Monday to Friday, holidays not modeled.",
    "A9": "Revenue spiking while inventory piles up: revenue growth above 30% and inventory growth above revenue growth by more than 10 points.",
    "A10": "Constant share sales to raise cash: share count up in each of the last 3 fiscal years and by more than 5% in total.",
    "A11": "DCF growth trim: 25% off the 3-year average growth (override: step12.growth_trim_override).",
    "A12": "PEG between 1 and 2: 'between fair and very expensive'.",
    "A13": "5-year return that beats the S&P 500 by 0 to 10 points: 0 points (no band given; conservative).",
    "A14": "5-year return: ticker vs SPY on adjusted closes (total return), in percentage points.",
    "A15": "The Rule of 40 is a required check in step 3 only for software and subscription businesses.",
    "A16": "Cash includes short-term investments; debt is yfinance 'Total Debt' (includes leases).",
    "A17": "DCF base revenue: TTM revenue (latest fiscal year if TTM is missing); growth and FCF margin are 3-year averages. A 3-year revenue average would start the projection below today's revenue.",
    "A18": "Declining margins: FAIL when operating margin fell both TTM vs prior TTM and in the latest fiscal "
           "year vs the previous one; only one of the two = warning. When prior TTM is not available, the "
           "annual comparison decides alone (data fallback rule).",
    "A19": "Net dollar retention is INFO only (the document says 'also check').",
    "A20": "Step 7 labels: growth accelerating in the latest year = 'growth stage'; decelerating with the "
           "latest growth below 10% = 'maturing'; otherwise no label.",
    "A21": "Auto 'consistent earnings beats' (step 10): reported EPS above estimate in each of the last 4 "
           "quarters; the last 8 are shown as evidence. Manual value overrides.",
    "A22": "A line yfinance does not report in any period of a non-empty statement (Goodwill, Inventory, "
           "Interest Expense) is read as not reported (zero). The check says so explicitly.",
    "A23": "Right multiple vs peers (step 12 part 3): forward P/E at or below the peer median, or P/S at or "
           "below the peer average, passes.",
    "A24": "Revenue and expense growth: TTM vs prior TTM needs 8 quarters. 'Previous period growth' for the "
           "'below 10% and falling' kill is the previous comparable period on the same basis "
           "(fallback: annual).",
    "A25": "Market cap in USD for the $1B and $2B tests: converted with the yfinance FX pair when the trading "
           "currency is not USD.",
    "A26": "Short interest falls back to sharesShort / floatShares when shortPercentOfFloat is missing.",
    "A28": "Manual judgements nobody filled in are ignored, not counted as failures; a step with nothing left "
           "to judge is N/A. Scorecard: only scored categories count and the 75/130 bar is scaled to them.",
    "A27": "Declining margins: when prior TTM is unavailable (fewer than 8 quarters), the latest quarter is compared "
           "with the same quarter a year earlier, instead of falling back to a stale fiscal year.",
}

KNOWN_INCONSISTENCIES = [
    "It is called a 125-point scorecard, but 13 categories x 10 = 130. Computed out of 130; bands applied as written.",
    "Step 2 lets an infrastructure company that needs leverage fail the cash-vs-debt question, but step 3 kills "
    "any company with more debt than cash 'even by a dollar'. The instant kill wins; the exception only saves step 2.",
    "The bands overlap at 100 (100-125 and 75-100): 100 = Exceptional.",
    "Scorecard category 7 has no band for beating the S&P 500 by 0-10 points (A13); '10 to 20%' and '20%+' "
    "overlap at 20 (20 = 10 points).",
    "PEG between 1 and 2 has no label (A12).",
    "Interest coverage is given as '4 to 10x' with nothing said above 10x: above 10x passes.",
    "'Below 40, pass' (Rule of 40) is read as 'pass on it', meaning reject.",
]

DISCLAIMER_HE = "חינוך, לא ייעוץ פיננסי"
