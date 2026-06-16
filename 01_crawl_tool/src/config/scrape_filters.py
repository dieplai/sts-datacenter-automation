"""Search filters for the detail scraper.

Everything here is a sensible default. For a specific run, edit `_local.py`
(gitignored) and override only the fields you care about — the rest
inherits from this file.
"""

# ============================================================
# TEST MODE CONFIGURATION
# ============================================================
TEST_SEARCH_CONFIG = {
    "country": "Vietnam",
    "data_type": "Import data",
    "start_date": "2025-01-01",
    "end_date": "2025-01-31",
    "hs_code": "55",
    "product": "",
    "buyer": "",
    "supplier": "",
    "expected": None,
}

# ============================================================
# DETAIL MODE (Market Analysis → Customs Data)
# ============================================================
DETAIL_COUNTRY = "Vietnam"
DETAIL_DATA_TYPE = "Import data"   # "Import data" | "Export data"

DETAIL_START_DATE = "2026-01-01"
DETAIL_END_DATE = "2026-02-28"
DETAIL_EXPECTED_TOTAL = None

DETAIL_HS_CODE = ""
DETAIL_PRODUCT = ""
DETAIL_BILL_NUMBER = ""
DETAIL_SUPPLIER = ""
DETAIL_BUYER = ""
DETAIL_BUYER_COUNTRY = ""
DETAIL_POL = ""
DETAIL_POD = ""
DETAIL_SHIPPING_METHOD = ""

DETAIL_MIN_QTY = None
DETAIL_MAX_QTY = None
DETAIL_MIN_AMOUNT = None
DETAIL_MAX_AMOUNT = None
DETAIL_MIN_UUSD = None
DETAIL_MAX_UUSD = None

# Page cap. None = all pages; small int = quick smoke test.
DETAIL_MAX_PAGES = None

# "single" | "multi" | "daily"
DETAIL_SUBMODE = "single"

# Batch for TRANSACTIONS mode (filled per-run via _local.py)
TRANSACTIONS_BATCH = []
