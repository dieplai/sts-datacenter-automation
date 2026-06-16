"""One-shot migration: flat `src/config.py` → `src/config/_local.py`.

Safely extracts ONLY user-overridable names (credentials + filters) via the
`ast` module. Computed values (BASE_DIR, OUTPUT_DIR, CHROMEDRIVER_PATH...)
are skipped because the submodules recompute them correctly from the new
file location.

Run once after pulling PR2:

    python scripts/migrate_config_v2.py

Idempotent: safe to re-run.
"""
import ast
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "src" / "config.py"
NEW_DIR = ROOT / "src" / "config"
NEW = NEW_DIR / "_local.py"
BAK = ROOT / "src" / "config.py.bak"

# Names that are SAFE to copy (simple overrides). Derived/computed names
# are intentionally excluded so the new package's settings.py/paths logic
# stays authoritative.
OVERRIDABLE = {
    # auth
    "USERNAME", "PASSWORD", "TARGET_URL", "PRO_LOGIN_URL",
    # proxy
    "PROXY_HOST", "PROXY_PORT", "PROXY_USER", "PROXY_PASS",
    # runtime toggles
    "TEST_MODE", "TEST_SEARCH_CONFIG", "INTERMEDIATE_FORMAT",
    # fast api
    "FAST_API_MODE", "FAST_API_CONCURRENCY", "FAST_API_RATE_LIMIT",
    "FAST_API_RETRIES", "FAST_API_FALLBACK_THRESHOLD", "FAST_API_USE_PROXY",
    # detail filters
    "DETAIL_COUNTRY", "DETAIL_DATA_TYPE",
    "DETAIL_START_DATE", "DETAIL_END_DATE", "DETAIL_EXPECTED_TOTAL",
    "DETAIL_HS_CODE", "DETAIL_PRODUCT", "DETAIL_BILL_NUMBER",
    "DETAIL_SUPPLIER", "DETAIL_BUYER", "DETAIL_BUYER_COUNTRY",
    "DETAIL_POL", "DETAIL_POD", "DETAIL_SHIPPING_METHOD",
    "DETAIL_MIN_QTY", "DETAIL_MAX_QTY",
    "DETAIL_MIN_AMOUNT", "DETAIL_MAX_AMOUNT",
    "DETAIL_MIN_UUSD", "DETAIL_MAX_UUSD",
    "DETAIL_MAX_PAGES", "DETAIL_SUBMODE",
    # batches
    "TRANSACTIONS_BATCH", "ANALYSIS_BATCH",
}


def _extract_overrides(source):
    """Return {name: source_text} for each top-level assignment in
    OVERRIDABLE. Uses ast.get_source_segment to preserve formatting.
    """
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in OVERRIDABLE:
                segment = ast.get_source_segment(source, node)
                if segment is not None:
                    out[target.id] = segment
    return out


def main():
    if not NEW_DIR.is_dir():
        print(f"❌ {NEW_DIR} does not exist — did you pull the PR2 code?")
        sys.exit(1)

    if NEW.exists() and NEW.stat().st_size > 0:
        print(f"ℹ️  {NEW.relative_to(ROOT)} already exists, nothing to do.")
        if OLD.exists():
            print(f"⚠️  Old {OLD.relative_to(ROOT)} still present. To avoid "
                  f"import ambiguity:")
            print(f"      mv {OLD.relative_to(ROOT)} {BAK.relative_to(ROOT)}")
        return

    if not OLD.exists():
        print(f"ℹ️  No old {OLD.relative_to(ROOT)} found. Copy the template:")
        print(f"      cp src/config/_local.example.py src/config/_local.py")
        return

    old_source = OLD.read_text(encoding="utf-8")
    overrides = _extract_overrides(old_source)
    if not overrides:
        print("⚠️  Couldn't extract any override values from the old file.")
        print("    Copy the template and set values manually:")
        print(f"      cp src/config/_local.example.py {NEW.relative_to(ROOT)}")
        sys.exit(1)

    header = (
        '"""Local overrides migrated from src/config.py (legacy layout).\n'
        "\n"
        "Only simple override values are kept; paths and computed constants\n"
        "come from the new submodules (auth.py, proxy.py, settings.py,\n"
        'scrape_filters.py). Edit freely — this file is gitignored."""\n'
        "import os  # old file used os.environ for some defaults\n"
        "\n"
    )
    body = "\n".join(overrides[name] for name in overrides) + "\n"
    NEW.write_text(header + body, encoding="utf-8")
    print(f"✅ Wrote {len(overrides)} override(s) to {NEW.relative_to(ROOT)}: "
          f"{sorted(overrides)[:5]}{'...' if len(overrides) > 5 else ''}")

    shutil.move(str(OLD), str(BAK))
    print(f"📦 Moved {OLD.relative_to(ROOT)} → {BAK.relative_to(ROOT)} (backup)")
    print(f"\n✅ Migration complete. Delete {BAK.relative_to(ROOT)} once you "
          f"confirm `python run.py` works.")


if __name__ == "__main__":
    main()
