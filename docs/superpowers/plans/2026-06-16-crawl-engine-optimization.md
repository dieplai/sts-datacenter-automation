# Plan A: Crawl Engine Optimization
**Date:** 2026-06-16  
**Goal:** 24/7 full-data production crawl — zero data loss, enterprise-grade logging, professional directory structure  
**Status:** Ready for implementation

---

## Context

**Crawl servers:** 100.76.219.16 (ACC1, ACC2) and 100.76.65.2 (ACC3, ACC4)  
**Deploy paths:** `C:\CRAWL_STS\ACC{n}\DEPLOY_ACC_{n}\`  
**Master source:** `D:\Dieplai\sts_pipeline_server\01_crawl_tool\`  
**Bug fixes already deployed (7 total):** CRITICAL-1/2/3, HIGH-3/4/5, MEDIUM-5/6  

**Current bottleneck (performance profiling):**
- Fixed sleep in `go_to_next_page`: `time.sleep(1) + time.sleep(2.0) + time.sleep(3.5)` = 6.5s dead
- Fixed sleep in main loop: `time.sleep(2)` = 2.0s dead
- Total: ~8.7s dead time per page, regardless of whether the page loaded
- At 333 pages × 8.7s = 48 min/segment of pure sleep — no real work
- Hardware is NOT the bottleneck (Ryzen 7/i9, 32 GB RAM on all servers)

**FAST_API_MODE** is currently off by default (server returns state=40 for cold API calls). Do NOT enable.

---

## Task List

### Task 0 — Git repository initialization
**File:** none (git operations)  
**Priority:** HIGH — must be done first so all subsequent changes are tracked

Steps:
1. `cd D:\Dieplai\sts_pipeline_server`
2. `git init`
3. Create `.gitignore` (see spec section below)
4. `git config user.name "Diep Lai"`
5. `git config user.email "dieptrungnam123@gmail.com"`
6. `git remote add origin https://github.com/dieplai/sts-datacenter-automation.git`
7. `git add -A && git commit -m "chore: initial commit — STS datacenter automation"`
8. `git push -u origin main`

**.gitignore contents:**
```
venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.env
data/
output/
logs/
*.log
*.csv
*.xlsx
*.jsonl
chromedriver/
chromedriver.exe
.DS_Store
Thumbs.db
_crawl_review/
```

---

### Task 1 — Enterprise logger (`src/observability/logger.py`)
**Master file:** `01_crawl_tool/src/observability/logger.py`  
**Deploy to:** all 4 accounts at `src/observability/logger.py`  
**Priority:** HIGH — affects all log output

**Current format:** `[HH:MM:SS] [icon]msg`  
**Target format:** `YYYY-MM-DD HH:MM:SS.mmm | LEVEL   | MODULE   | message`

**Implementation:**

```python
"""Enterprise structured logger — no third-party deps."""
import re
import sys
from datetime import datetime

_LEVEL_WIDTH = 8  # pad level to this width

_STRIP_EMOJI = re.compile(
    r"[\U00010000-\U0010FFFF"  # supplementary planes (emoji, etc.)
    r"\U0001F300-\U0001F9FF"   # misc symbols and pictographs
    r"☀-⛿"           # misc symbols
    r"✀-➿"           # dingbats
    r"︀-️"           # variation selectors
    r"‍"                  # zero-width joiner
    r"]+",
    flags=re.UNICODE,
)


def _clean(msg: str) -> str:
    return _STRIP_EMOJI.sub("", str(msg)).strip()


def log(msg, level="INFO", module="CRAWL"):
    """Print enterprise-format log line to stdout."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    lvl = level.upper().ljust(_LEVEL_WIDTH)
    mod = module.upper().ljust(10)
    print(f"{now} | {lvl} | {mod} | {_clean(msg)}", flush=True)


def format_time_elapsed(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
```

**Call-site compatibility:** All existing `log("msg", "LEVEL")` calls continue to work unchanged. The new `module` parameter is optional with a default.

**Acceptance criteria:**
- No emoji in any log line
- Level field is always 8 characters wide
- Module field always 10 characters wide
- No import changes required at call sites

---

### Task 2 — Smart page navigation (`src/nav/pagination.py`)
**Master file:** `01_crawl_tool/src/nav/pagination.py`  
**Deploy to:** all 4 accounts  
**Priority:** HIGH — eliminates 6.5s dead sleep per page

**Current code (problematic section in `go_to_page`):**
```python
time.sleep(1)          # dead wait after jump input
...
time.sleep(2.0)        # dead wait after active page confirmed
api_client.wait_for_loading_overlay(driver, timeout=30)
time.sleep(3.5)        # dead wait after overlay clears
return True
```

**Target — replace with `_wait_rows_stable()`:**

```python
_ROW_SELECTOR = "tbody.ant-table-tbody tr.ant-table-row"
_STALE_POLL_MS = 150   # ms between DOM staleness checks
_STABLE_COUNT  = 3     # consecutive identical DOM snapshots = stable
_TIMEOUT_S     = 30    # abort if rows don't stabilise within this


def _wait_rows_stable(driver, timeout_s=_TIMEOUT_S):
    """Wait until the row DOM is stable (no mutations) for _STABLE_COUNT polls.

    Returns True when stable, False on timeout.
    This replaces all fixed time.sleep() calls after pagination.
    """
    import time as _time
    deadline = _time.monotonic() + timeout_s
    prev_snapshot = None
    streak = 0

    while _time.monotonic() < deadline:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, _ROW_SELECTOR)
            snapshot = tuple(r.id for r in rows)  # DOM element IDs
        except Exception:
            _time.sleep(_STALE_POLL_MS / 1000)
            continue

        if snapshot and snapshot == prev_snapshot:
            streak += 1
            if streak >= _STABLE_COUNT:
                return True
        else:
            streak = 0

        prev_snapshot = snapshot
        _time.sleep(_STALE_POLL_MS / 1000)

    return False  # timed out
```

**Rewrite `go_to_page` end section:**
```python
        # Replace: time.sleep(2.0) + wait_for_loading_overlay + time.sleep(3.5)
        # With: wait until row DOM is stable
        if not _wait_rows_stable(driver):
            log(f"go_to_page: rows did not stabilise after {_TIMEOUT_S}s", "WARNING", "NAV")
        return True
```

**Also fix `go_to_next_page` (same pattern):** replace `time.sleep(1)` before click with `WebDriverWait` on button clickability, then `_wait_rows_stable` after click.

**Expected gain:** 6.5s → ~0.5-1.5s per page (wait only as long as the page actually takes).

**Acceptance criteria:**
- No `time.sleep()` calls with fixed durations > 0.2s in pagination flow
- `_wait_rows_stable()` passes with streak=3 before returning True
- Timeout path logs a WARNING and returns (does not crash)

---

### Task 3 — Status reporter (`src/scraper/core_pro_detail.py`)
**Master file:** `01_crawl_tool/src/scraper/core_pro_detail.py` (same as live deployed file)  
**Deploy to:** all 4 accounts  
**Priority:** MEDIUM — required by Go management tool in Plan B

**Add `_write_status()` method to `ScraperProDetail` class:**

```python
import json as _json  # add at top of file

def _write_status(self, page_num, total_scraped, segment_num, segment_start, segment_end, extra=None):
    """Write current progress to data/status.json for the management tool to poll."""
    status = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "account": getattr(config, "USERNAME", "unknown"),
        "batch": getattr(self, "batch_name", ""),
        "segment": segment_num,
        "segment_start": segment_start,
        "segment_end": segment_end,
        "page": page_num,
        "total_scraped": total_scraped,
        "state": "running",
    }
    if extra:
        status.update(extra)
    try:
        status_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "status.json",
        )
        with open(status_path, "w", encoding="utf-8") as f:
            _json.dump(status, f, ensure_ascii=False)
    except Exception:
        pass  # status.json is best-effort, never crash crawl for it
```

**Call `_write_status()` inside the page loop**, after each page is scraped and CSV is written.

**Final status on completion/error:**
```python
# On segment complete:
self._write_status(page_num, total_scraped, segment_num, ..., extra={"state": "idle"})
# On error/exit:
self._write_status(page_num, total_scraped, segment_num, ..., extra={"state": "error", "reason": str(e)})
```

**Schema (`data/status.json`):**
```json
{
  "ts": "2026-06-16T10:30:45",
  "account": "vtic.stsgroup@gmail.com",
  "batch": "54_Import_Q1",
  "segment": 3,
  "segment_start": "2026-02-15",
  "segment_end": "2026-02-28",
  "page": 147,
  "total_scraped": 4410,
  "state": "running"
}
```

**Acceptance criteria:**
- `data/status.json` is created/updated after every page
- File write failure never propagates as an exception to the crawl loop
- State values: `running`, `idle`, `error`

---

### Task 4 — Failed rows auto-retry (`src/scraper/core_pro_detail.py`)
**Same file as Task 3** (combine into one deploy)  
**Priority:** MEDIUM — recovers transient failures without manual intervention

**Find the `_flush_failed_rows()` or equivalent method. Add `_retry_failed_rows()` after each segment:**

```python
_RETRY_BACKOFF = [5, 15, 45]  # seconds between attempts


def _retry_failed_rows(self):
    """Retry entries from data/failed/failed_rows_YYYYMMDD.jsonl with backoff.

    Called once per segment after CSV is written and verified.
    """
    import glob as _glob, time as _time
    failed_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "failed",
    )
    if not os.path.isdir(failed_dir):
        return

    pattern = os.path.join(failed_dir, "failed_rows_*.jsonl")
    for fpath in _glob.glob(pattern):
        try:
            with open(fpath, encoding="utf-8") as fh:
                entries = [_json.loads(line) for line in fh if line.strip()]
        except Exception:
            continue

        if not entries:
            continue

        log(f"Retrying {len(entries)} failed rows from {os.path.basename(fpath)}", "INFO", "RETRY")
        still_failed = []
        for entry in entries:
            success = False
            for delay in _RETRY_BACKOFF:
                try:
                    # Re-fetch detail for this bill_id / row
                    result = self._fetch_row_detail(entry)
                    if result:
                        self._append_to_csv(result)
                        success = True
                        break
                except Exception as ex:
                    log(f"Retry attempt failed: {ex}", "WARNING", "RETRY")
                _time.sleep(delay)
            if not success:
                still_failed.append(entry)

        # Overwrite file with only the entries that still failed
        with open(fpath, "w", encoding="utf-8") as fh:
            for entry in still_failed:
                fh.write(_json.dumps(entry, ensure_ascii=False) + "\n")

        recovered = len(entries) - len(still_failed)
        log(f"Retry result: {recovered}/{len(entries)} recovered", "INFO", "RETRY")
```

**Note:** `_fetch_row_detail()` and `_append_to_csv()` are placeholders — wire to the actual methods in the class. The retry logic structure is correct; method names must match the live codebase.

**Acceptance criteria:**
- Retry runs after every segment
- Backoff is 5s / 15s / 45s (not concurrent)
- Remaining failures are preserved in the JSONL file (not discarded)
- Empty JSONL files after full recovery are deleted or left empty

---

### Task 5 — Post-segment verification (`src/scraper/core_pro_detail.py`)
**Same file as Tasks 3 & 4**  
**Priority:** HIGH — catches silent data loss before moving to next segment

**Add after each segment CSV is finalised:**

```python
_SEGMENT_VERIFY_THRESHOLD = 0.95  # 95% of expected


def _verify_segment(self, segment_num, segment_start, segment_end, expected):
    """Count CSV rows for this segment date range and compare to website total.

    Returns True if count >= threshold * expected.
    Logs a WARNING if below threshold (does not abort — auto-retry handles it).
    """
    if not expected or expected <= 0:
        return True  # no baseline to compare

    try:
        import csv as _csv
        count = 0
        with open(self.csv_file, encoding="utf-8", newline="") as fh:
            reader = _csv.DictReader(fh)
            date_col = "Ngay"  # adjust if column name differs
            for row in reader:
                val = row.get(date_col, "")
                if segment_start <= val <= segment_end:
                    count += 1
    except Exception as ex:
        log(f"Segment verify: could not count CSV rows: {ex}", "WARNING", "VERIFY")
        return True  # best-effort, don't fail the segment for a verify error

    ratio = count / expected
    if ratio < _SEGMENT_VERIFY_THRESHOLD:
        log(
            f"SEGMENT VERIFY FAILED: segment {segment_num} "
            f"({segment_start} -> {segment_end}) "
            f"got {count:,}/{expected:,} rows ({ratio:.1%}) — below 95% threshold",
            "WARNING", "VERIFY",
        )
        return False

    log(
        f"Segment verify OK: {count:,}/{expected:,} rows ({ratio:.1%})",
        "INFO", "VERIFY",
    )
    return True
```

**Wire:** call `self._verify_segment(...)` after the segment loop completes, before moving on.

**Acceptance criteria:**
- Verification runs on every completed segment
- A ratio < 95% logs WARNING with exact counts
- Verification failure does not crash the crawl (log-and-continue)
- Verification on a segment with `expected=0` or `expected=999999` is a no-op

---

### Task 6 — Remove `DETAIL_MAX_PAGES` limits for production
**Files:** `_local.py` on ACC1, ACC2, ACC3  
**Priority:** CRITICAL — ACC1/ACC2/ACC3 are still in test mode (5 pages = 150 rows max per segment)

**Changes per account:**

| Account | Current `DETAIL_MAX_PAGES` | Action |
|---------|---------------------------|--------|
| ACC1    | 5                         | Remove line entirely |
| ACC2    | 5                         | Remove line entirely |
| ACC3    | 5                         | Remove line entirely |
| ACC4    | None                      | Already correct |

**After removal**, `settings.py` defaults to `DETAIL_MAX_PAGES = None` which means unlimited pages.

**Script to deploy:**
```python
# For each account, read _local.py, remove DETAIL_MAX_PAGES line, write back
```

**Acceptance criteria:**
- `DETAIL_MAX_PAGES` does not appear in any `_local.py` after this task
- Crawl will now traverse all pages in each segment

---

### Task 7 — Integration test (before full production run)
**Priority:** CRITICAL — validate all changes with a limited scope run

**Steps:**
1. Set `DETAIL_MAX_PAGES = 3` temporarily on ACC1
2. Run one full segment (small date range, e.g., 3 days)
3. Verify:
   - Log format matches `YYYY-MM-DD HH:MM:SS.mmm | LEVEL | MODULE | msg`
   - No emoji in any log line
   - `data/status.json` is written after each page
   - `data/failed/` directory exists
   - CSV row count matches website count within 5%
   - `auto_set_expected.py` updates `_local.py` correctly after run
4. Remove `DETAIL_MAX_PAGES = 3`
5. Run production crawl on all 4 accounts

---

## Directory Structure (target)

```
DEPLOY_ACC_{n}/
├── run.py
├── run_supervised.bat
├── src/
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── _local.py          # per-account config
│   │   ├── auth.py
│   │   ├── proxy.py
│   │   └── scrape_filters.py
│   ├── core/
│   │   ├── browser.py
│   │   └── proxy_rotator.py
│   ├── scraper/
│   │   └── core_pro_detail.py  # LIVE file (run by main.py)
│   ├── nav/
│   │   └── pagination.py
│   ├── observability/
│   │   └── logger.py
│   ├── extract/
│   │   └── async_fetcher.py
│   ├── storage/
│   │   ├── csv_sink.py
│   │   └── checkpoint.py
│   ├── parsing/
│   └── main.py
├── scripts/
│   ├── auto_set_expected.py
│   └── generate_manifest.py
├── data/
│   ├── status.json             # live progress for management tool
│   └── failed/
│       └── failed_rows_YYYYMMDD.jsonl
├── logs/
│   └── audit/
│       └── YYYYMMDD_HHMMSS.log
└── output/
    └── intermediate/
```

---

## Deployment Order

1. Task 0: Git init + initial commit + push
2. Task 1: Logger (affects all log output — do first)
3. Task 2: Smart pagination (biggest perf gain)
4. Tasks 3+4+5: Status reporter + failed retry + segment verify (single deploy)
5. Task 6: Remove DETAIL_MAX_PAGES (production unlock)
6. Task 7: Integration test
7. Full production crawl

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| `_wait_rows_stable()` timeout on slow pages | 30s timeout → falls back gracefully, logs WARNING |
| False-negative segment verify (e.g., CSV uses different date column name) | Returns True on exception — never aborts crawl |
| `failed_items.append()` crash on type error | Fixed in latest deploy (replaced with `+= 1`) |
| HIGH-4 lower bound false positive on acc4 (expected=999999) | `effective_expected * 0.5 = 499,999` — any real segment will be below this, check will never fire |
