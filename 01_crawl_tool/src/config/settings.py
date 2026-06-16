"""Paths, driver path resolution, and runtime toggles."""
import os

# BASE_DIR: project root (two parents up from src/config/settings.py)
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
INTERMEDIATE_DIR = os.path.join(OUTPUT_DIR, "intermediate")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(INTERMEDIATE_DIR, exist_ok=True)

# Chromedriver path auto-resolution. `undetected-chromedriver` auto-downloads
# the correct version when this is None.
CHROMEDRIVER_PATH = os.path.join(BASE_DIR, "chromedriver", "chromedriver.exe")
if not os.path.exists(CHROMEDRIVER_PATH):
    CHROMEDRIVER_PATH = os.path.join(BASE_DIR, "chromedriver.exe")
if not os.path.exists(CHROMEDRIVER_PATH):
    CHROMEDRIVER_PATH = os.path.join(os.getcwd(), "chromedriver.exe")
if not os.path.exists(CHROMEDRIVER_PATH):
    CHROMEDRIVER_PATH = None

# --- Runtime toggles ----------------------------------------------------
TEST_MODE = False

# Intermediate save format. "csv" is fastest; "excel" keeps original behaviour.
INTERMEDIATE_FORMAT = "csv"

# Set True to also produce a .xlsx file alongside the CSV after each run.
# Default False — the DA pipeline only needs CSV.
SAVE_EXCEL = False

# --- FAST API MODE (experimental) ---------------------------------------
# Recon (2026-04-20) revealed the server returns state=40 for any bill_id
# not previously clicked in the browser, so cold parallel API fetch fails.
# The flag is kept off by default and can be flipped per-run via env.
FAST_API_MODE = bool(int(os.environ.get("FAST_API_MODE", "0")))
FAST_API_CONCURRENCY = int(os.environ.get("FAST_API_CONCURRENCY", "5"))
FAST_API_RATE_LIMIT = int(os.environ.get("FAST_API_RATE_LIMIT", "20"))  # req/s
FAST_API_RETRIES = int(os.environ.get("FAST_API_RETRIES", "3"))
FAST_API_FALLBACK_THRESHOLD = int(os.environ.get("FAST_API_FALLBACK_THRESHOLD", "3"))
FAST_API_USE_PROXY = bool(int(os.environ.get("FAST_API_USE_PROXY", "1")))
