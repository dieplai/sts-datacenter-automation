"""
auto_set_expected.py — Parse a crawl log, extract actual total-records per batch item,
and update _local.py so the next supervisor restart passes the validator immediately.

Called automatically by run_supervised.bat on every crash:
    python scripts\auto_set_expected.py --log "logs\crawl_YYYYMMDD_HHMMSS.log"

Self-healing workflow:
  1st run  : expected=999999 → validator fails (Got: 117,134, Expected: 999,999)
             → log written → auto_set_expected updates _local.py → expected=117134
  2nd run  : expected=117134 == 117,134 → validator passes → crawl proceeds ✓
"""

import argparse
import glob
import os
import re
import sys


def get_latest_log(logs_dir: str) -> str | None:
    logs = glob.glob(os.path.join(logs_dir, "crawl_*.log"))
    return max(logs, key=os.path.getmtime) if logs else None


def extract_totals(log_path: str) -> dict[str, int]:
    """Return {batch_name: actual_total} found in log.

    Pairs each 'BATCH ITEM [N/M]: name' line with the first
    'Found total records ... : X' that follows it.
    """
    batch_re = re.compile(r'BATCH ITEM \[\d+/\d+\]:\s*(.+)')
    total_re = re.compile(r'Found total records[^:]*:\s*([\d,]+)')

    totals: dict[str, int] = {}
    current_batch: str | None = None

    with open(log_path, "rb") as raw_fh:
        raw = raw_fh.read()
    # PowerShell Tee-Object on PS 5.1 writes UTF-16 LE (BOM = FF FE)
    if raw[:2] == b"\xff\xfe":
        text = raw.decode("utf-16-le", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
            bm = batch_re.search(line)
            if bm:
                current_batch = bm.group(1).strip()

            tm = total_re.search(line)
            if tm and current_batch and current_batch not in totals:
                totals[current_batch] = int(tm.group(1).replace(",", ""))

    return totals


def update_local_py(local_py: str, totals: dict[str, int]) -> list[str]:
    """Rewrite _local.py, replacing expected values for matched batch items.

    Returns list of (batch_name, old, new) change descriptions.
    """
    with open(local_py, encoding="utf-8") as fh:
        content = fh.read()

    changes: list[str] = []

    for batch_name, actual in totals.items():
        # Match the dict entry for this batch item and update "expected"
        # Handles both: "expected":999999  and  "expected": 999999
        pattern = re.compile(
            r"""(['"]name['"]\s*:\s*['"]""" + re.escape(batch_name) + r"""['"][^}]*?['"]expected['"]\s*:\s*)(\d+)""",
            re.DOTALL,
        )
        def replacer(m, actual=actual):
            old = int(m.group(2))
            return m.group(1) + str(actual)

        new_content, n = pattern.subn(replacer, content)
        if n:
            # Extract old value for reporting
            old_match = pattern.search(content)
            old_val = int(old_match.group(2)) if old_match else "?"
            changes.append(f"{batch_name}: {old_val:,} → {actual:,}")
            content = new_content

    if changes:
        with open(local_py, "w", encoding="utf-8") as fh:
            fh.write(content)

    return changes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", help="Path to crawl log file (default: latest in logs/)")
    args = parser.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_py = os.path.join(base, "src", "config", "_local.py")

    log_path = args.log
    if not log_path or not os.path.exists(log_path):
        logs_dir = os.path.join(base, "logs")
        log_path = get_latest_log(logs_dir)

    if not log_path or not os.path.exists(log_path):
        print("[auto_set_expected] No log file found — skipping")
        sys.exit(0)

    print(f"[auto_set_expected] Scanning: {os.path.basename(log_path)}")
    totals = extract_totals(log_path)

    if not totals:
        print("[auto_set_expected] No 'Found total records' lines — nothing to update")
        sys.exit(0)

    for name, total in totals.items():
        print(f"[auto_set_expected]   {name}: actual total = {total:,}")

    changes = update_local_py(local_py, totals)
    if changes:
        for c in changes:
            print(f"[auto_set_expected] Updated expected: {c}")
        print(f"[auto_set_expected] _local.py saved — next restart will pass validator ✓")
    else:
        print("[auto_set_expected] No matching batch items in _local.py — nothing changed")


if __name__ == "__main__":
    main()
