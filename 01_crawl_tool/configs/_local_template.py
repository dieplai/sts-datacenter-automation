"""Copy this file to `_local.py` and fill in your values.

`_local.py` is gitignored — it's the ONLY place your credentials live on
this machine. Every name defined here overrides the committed default in
`auth.py`, `proxy.py`, `settings.py`, or `scrape_filters.py`.

You only need to define the values you want to change. Everything else
falls back to the committed defaults.
"""

# ================================================================
# REQUIRED — pro.52wmb.com credentials
# ================================================================
USERNAME = "your-email@example.com"
PASSWORD = "your-password"

# ================================================================
# OPTIONAL — Brightdata proxy (leave empty if not using)
# ================================================================
PROXY_HOST = ""
PROXY_PORT = ""
PROXY_USER = ""
PROXY_PASS = ""

# ================================================================
# OPTIONAL — output directory
# Default: <project_root>/output/
# Set to bronze landing zone so CSV lands directly in the pipeline.
# Example (same machine as pipeline server):
#   OUTPUT_DIR = r"D:\datacenter\bronze\2026"
# ================================================================
# OUTPUT_DIR = r"D:\datacenter\bronze\2026"

# Set True to also produce a .xlsx file alongside the CSV (slow, rarely needed).
SAVE_EXCEL = False

# ================================================================
# OPTIONAL — scrape filters (override per run)
# ================================================================
# DETAIL_COUNTRY = "Vietnam"
# DETAIL_DATA_TYPE = "Import data"
# DETAIL_START_DATE = "2026-01-01"
# DETAIL_END_DATE = "2026-02-28"
# DETAIL_HS_CODE = "57"
# DETAIL_BUYER = ""
# DETAIL_SUPPLIER = ""
# DETAIL_MAX_PAGES = None     # 5 = quick test; None = full run

# ================================================================
# OPTIONAL — TRANSACTIONS_BATCH for multi-mode
# ================================================================
# TRANSACTIONS_BATCH = [
#     {"name": "im_buyer_foo_23_26", "hs_code": "", "data_type": "Import data",
#      "start_date": "2023-01-01", "end_date": "2026-12-31",
#      "buyer": "foo", "expected": 2417},
# ]
