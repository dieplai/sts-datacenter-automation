"""Generate CSV/Excel output filename from the active scrape config.

Pure function of config. No side effects other than ensuring the `output/`
directory exists.
"""
import os
import re
from datetime import datetime

try:
    from .. import config
except ImportError:  # pragma: no cover
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config  # type: ignore


def _safe(s, length=30):
    return re.sub(r"[^a-zA-Z0-9]", "_", str(s))[:length]


def _date_token(start_date, end_date):
    """Compact date-range tag for filenames.
    - Same month, full month coverage  → 'FEB_2026'
    - Same year, multi-month           → 'JAN_FEB_2026'
    - Different years / partial month  → '2026-01-15_to_2026-02-15'
    Returns "" if either date is missing."""
    if not start_date or not end_date:
        return ""
    try:
        sd = datetime.strptime(str(start_date), "%Y-%m-%d")
        ed = datetime.strptime(str(end_date), "%Y-%m-%d")
    except ValueError:
        return ""

    month_abbr = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

    # Same year, same month, AND covers most of the month → MONTH_YEAR
    if sd.year == ed.year and sd.month == ed.month:
        # Allow partial month (e.g. 1-13 still tagged FEB_2026 if same month)
        return f"{month_abbr[sd.month - 1]}_{sd.year}"

    # Same year, different months → MONTH1_MONTH2_YEAR (compact for
    # short ranges like "JAN_FEB_2026")
    if sd.year == ed.year and (ed.month - sd.month) <= 2:
        return (f"{month_abbr[sd.month - 1]}_"
                f"{month_abbr[ed.month - 1]}_{sd.year}")

    # Otherwise: explicit range
    return f"{sd.strftime('%Y-%m-%d')}_to_{ed.strftime('%Y-%m-%d')}"


def generate_output_filename():
    """Return `output/detail_<country>_<import|export>_<hs><buyer><supplier>...csv`.

    Picks values from `config.TEST_SEARCH_CONFIG` if TEST_MODE is on,
    otherwise from `config.DETAIL_*`. Only non-empty filters are included
    in the filename so the path itself documents what was scraped.
    """
    is_test = getattr(config, "TEST_MODE", False)
    test_cfg = getattr(config, "TEST_SEARCH_CONFIG", {})

    def _pick(test_key, cfg_key):
        return test_cfg.get(test_key, "") if is_test else getattr(config, cfg_key, "")

    prefix = "test_detail" if is_test else "detail"
    parts = [prefix]

    country = _pick("country", "DETAIL_COUNTRY")
    if country:
        parts.append(_safe(country))

    data_type = _pick("data_type", "DETAIL_DATA_TYPE")
    if data_type:
        if "import" in data_type.lower():
            parts.append("import")
        elif "export" in data_type.lower():
            parts.append("export")

    hs_code = _pick("hs_code", "DETAIL_HS_CODE")
    if hs_code:
        parts.append(f"hs{re.sub(r'[^a-zA-Z0-9]', '', hs_code)}")

    for (test_k, cfg_k, prefix_token) in [
        ("buyer", "DETAIL_BUYER", "buyer"),
        ("supplier", "DETAIL_SUPPLIER", "sup"),
        ("product", "DETAIL_PRODUCT", "prd"),
        ("pod", "DETAIL_POD", "pod"),
    ]:
        v = _pick(test_k, cfg_k)
        if v:
            parts.append(f"{prefix_token}_{_safe(v)}")

    # Date range tag — appended last so HS code stays adjacent to country
    # in the filename (e.g. detail_Vietnam_import_hs52_FEB_2026.csv).
    # Each date range produces its own CSV/xlsx, so changing
    # DETAIL_START_DATE / END_DATE in _local.py auto-rotates the output
    # filename without overwriting previous month's data.
    start_date = _pick("start_date", "DETAIL_START_DATE")
    end_date = _pick("end_date", "DETAIL_END_DATE")
    date_tag = _date_token(start_date, end_date)
    if date_tag:
        parts.append(date_tag)

    filename = "_".join(parts) + ".csv"
    base_dir = getattr(config, 'OUTPUT_DIR', 'output')
    if hs_code:
        hs_primary = re.sub(r'[^0-9]', '', str(hs_code).split('|')[0])
        output_dir = os.path.join(base_dir, f"hs{hs_primary}") if hs_primary else base_dir
    else:
        output_dir = base_dir
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, filename)
