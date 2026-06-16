# STS Pipeline Management System — Design Specification

**Date:** 2026-06-16  
**Author:** Engineering  
**Status:** Approved for Implementation  
**Scope:** Crawl engine optimization + Centralized pipeline observability tool

---

## 1. Problem Statement

The STS data pipeline runs across three Windows machines:

| Machine | Role | Specs |
|---------|------|-------|
| Main server (D:\Dieplai\) | Storage, orchestration, pipeline runner | i9-11900KB, 32GB RAM |
| Crawl server .16 | acc1 + acc2 (Selenium Chrome crawl) | Ryzen 7 5700G, 32GB RAM |
| Crawl server .2 | acc3 + acc4 (Selenium Chrome crawl) | Ryzen 7 5700G, 32GB RAM |

Current pain points:

1. **Crawl speed**: 8.7 seconds dead time per page navigation (fixed sleeps in `go_to_next_page()`). For 333 pages per segment, this is 48+ minutes of pure sleeping per segment — before counting actual DOM interaction or network time.
2. **Silent data loss**: `failed_rows.jsonl` accumulates indefinitely with no automatic retry. Rows that fail detail fetch are permanently dropped unless manually recovered.
3. **No segment integrity check**: After a segment completes, there is no verification that the scraped row count matches the website-reported total.
4. **Unprofessional logging**: All log messages contain emoji, breaking grep, log analysis tools, and enterprise log pipelines.
5. **Fragmented observability**: Logs live on 3 separate machines. Checking the state of the pipeline requires opening RustDesk sessions on each crawl server and reading log files manually.
6. **No centralized control**: Config changes, start/stop, and status checks all require manual SSH or RustDesk access to individual machines.

---

## 2. Goals

### Primary (must have)
- No data loss during 24/7 production crawl
- Full pipeline observability from a single interface
- Config management without RustDesk

### Secondary (should have)
- 50%+ improvement in crawl throughput (explicit waits vs fixed sleeps)
- Enterprise-grade structured logging across all stages
- Start/stop control for crawl accounts from single interface

### Out of scope
- Scaling beyond 4 crawl accounts
- Web UI (Go TUI is the chosen interface)
- Database-backed state (JSON files are sufficient at this scale)

---

## 3. System Architecture

```
D:\Dieplai\sts_pipeline_server\
├── tools\
│   └── crawl-manager.exe          ← Go binary: TUI + CLI
│
├── 01_crawl_tool\                 ← Python crawl engine (optimized)
├── 02_ingestion_pipeline\         ← DQ gate
├── 03_pipeline_loader\            ← Staging → Gold
└── 04_ner_enrichment\             ← NER enricher

Crawl servers (SSH from main server via golang.org/x/crypto/ssh):
  100.76.219.16  ← acc1, acc2
  100.76.65.2    ← acc3, acc4
```

### Data flow (unchanged)
```
Crawl (Chrome/Selenium) → CSV (Bronze)
  → Robocopy sync → DQ Gate → Staging → PostgreSQL Gold tables
```

### Observability flow (new)
```
Each pipeline stage writes structured logs
crawl-manager polls all sources via SSH + local file read
→ single TUI dashboard on main server
```

---

## 4. Part A — Crawl Engine Optimization

### A1. Smart Page Navigation (`src/nav/pagination.py`)

**Replace all fixed sleeps in `go_to_next_page()` with staleness-based explicit waits.**

Current implementation has 6.5s of fixed sleeps per call:
- `time.sleep(1)` before click (remove)
- `time.sleep(2.0)` after click (replace)
- `time.sleep(3.5)` after overlay clears (replace)

New implementation:

```python
def go_to_next_page(driver, wait, is_recovery=False, max_retries=3):
    for attempt in range(max_retries):
        try:
            first_row_before = _snapshot_first_row(driver)
            next_btn = _find_next_button(driver)
            human_click(driver, next_btn) if not is_recovery else \
                driver.execute_script("arguments[0].click();", next_btn)

            # Step 1: confirm navigation started (old rows go stale)
            if first_row_before:
                WebDriverWait(driver, 10).until(
                    EC.staleness_of(first_row_before)
                )

            # Step 2: wait for loading overlay (laggy site: 60s timeout)
            wait_for_loading_overlay(driver, timeout=60)

            # Step 3: wait for new rows to be present and stable
            _wait_rows_stable(driver, timeout=30, poll_interval=0.3)

            return True
        except TimeoutException:
            log("go_to_next_page attempt %d/%d timed out", attempt+1, max_retries, level="WARNING")
            if attempt < max_retries - 1:
                handle_popup(driver, wait)
            else:
                return False


def _wait_rows_stable(driver, timeout=30, poll_interval=0.3):
    """Return only when table rows exist and first-row text is unchanged across two polls."""
    deadline = time.monotonic() + timeout
    prev = None
    while time.monotonic() < deadline:
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.ant-table-row")
        if rows:
            curr = rows[0].text
            if curr and curr == prev:
                return
            prev = curr
        time.sleep(poll_interval)
    raise TimeoutException("Table rows did not stabilize within %ds" % timeout)
```

Also remove from `core_pro_detail.py`:
- `time.sleep(2)` at line 1183 (after `go_to_next_page()`)
- Reduce `time.sleep(0.2)` at line 1968 to `time.sleep(0.1)`

**Expected result:** 1.5–3s per page navigation on normal load; self-stretches to 60s on site lag. Estimated saving: 6–7s per page × 333 pages = 33–39 minutes per segment.

### A2. FAST_API Concurrency Tuning

Hardware allows significantly higher concurrency. Website rate limit is 20 req/s.

```python
# src/config/_local.py (all 4 accounts)
FAST_API_CONCURRENCY = 15   # raised from 5 (hardware: 32GB RAM, 16 logical cores)
FAST_API_RATE_LIMIT   = 18  # raised from 20 but with 2 rps headroom for safety
FAST_API_RETRIES      = 3   # unchanged
```

Expected result: detail fetch phase 2–3x faster per page.

### A3. Failed Rows Auto-Retry

At the end of each segment, before advancing to the next, retry all entries in `data/failed/failed_rows_YYYYMMDD.jsonl`.

Retry logic (added to `run_transaction_pipeline` in `core_pro_detail.py`):

```python
def _retry_failed_rows(self, failed_jsonl_path, csv_file):
    if not os.path.exists(failed_jsonl_path):
        return
    entries = [json.loads(l) for l in open(failed_jsonl_path) if l.strip()]
    if not entries:
        return
    log("RETRY | Attempting recovery of %d failed rows", len(entries), level="INFO")
    recovered, still_failed = [], []
    backoff = [5, 15, 45]
    for entry in entries:
        for wait_s in backoff:
            result = self._fetch_single_detail(entry)
            if result:
                recovered.append(result)
                break
            time.sleep(wait_s)
        else:
            still_failed.append(entry)
    if recovered:
        _append_to_csv(csv_file, recovered)
    # Rewrite jsonl with only still-failed entries
    with open(failed_jsonl_path, "w") as f:
        for e in still_failed:
            f.write(json.dumps(e) + "\n")
    log("RETRY | Recovered %d/%d failed rows. %d remain.",
        len(recovered), len(entries), len(still_failed), level="INFO")
```

### A4. Post-Segment Verification

After each segment completes and after failed row retry, verify row count:

```python
def _verify_segment(self, csv_file, segment_date_range, expected_total, segment_num):
    scraped = _count_rows_in_date_range(csv_file, segment_date_range)
    pct = scraped / expected_total * 100 if expected_total else 0
    if scraped >= expected_total * 0.95:
        log("VERIFY | Segment %d: %d/%d records (%.1f%%) - PASS",
            segment_num, scraped, expected_total, pct, level="INFO")
        _write_audit(segment_num, scraped, expected_total, "PASS")
    else:
        log("VERIFY | Segment %d: %d/%d records (%.1f%%) - BELOW THRESHOLD",
            segment_num, scraped, expected_total, pct, level="WARNING")
        _write_audit(segment_num, scraped, expected_total, "BELOW_THRESHOLD")
        # Trigger one automatic re-crawl of segment
        return False
    return True
```

Audit entries written to `logs/audit/segment_audit.log`:
```
2026-06-16 14:23:45.123 | INFO    | VERIFY   | Segment 3: 9,987/9,990 (99.97%) - PASS
2026-06-16 14:23:45.234 | WARNING | VERIFY   | Segment 4: 8,100/9,990 (81.08%) - BELOW_THRESHOLD
```

### A5. Enterprise Logging

Strip all emoji at the `log()` output layer. No changes required to the 4,000+ call sites.

```python
# src/observability/logger.py
import re
from datetime import datetime

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FFFF\U00002600-\U000027FF\U0001F000-\U0001F02F]+",
    flags=re.UNICODE,
)

_LEVEL_WIDTH  = 7
_MODULE_WIDTH = 8

def log(message, level="INFO", module="CRAWLER"):
    clean = _EMOJI_RE.sub("", str(message)).strip()
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(
        f"{ts} | {level.upper().ljust(_LEVEL_WIDTH)} | "
        f"{module.upper().ljust(_MODULE_WIDTH)} | {clean}"
    )
```

**Log format:**
```
2026-06-16 14:23:45.123 | INFO    | BATCH    | Batch item [1/6]: 57_Export_Full - expected 28,698 records
2026-06-16 14:23:47.891 | INFO    | PAGE     | Page 15/333: 30 records scraped (segment total: 450)
2026-06-16 14:23:49.012 | ERROR   | RETRY    | Bill BL-123456 detail fetch failed (attempt 2/3): connection timeout
2026-06-16 14:23:50.100 | WARNING | VERIFY   | Segment 2: 9,987/9,990 (99.97%) - within tolerance
```

### A6. Directory Structure (per crawl account)

```
DEPLOY_AccX/
├── run.py
├── run_supervised.bat
├── src/
│   ├── core/
│   ├── nav/
│   ├── config/
│   └── observability/
│       └── logger.py           ← new: enterprise log formatter
├── output/                     ← UNCHANGED (UNC junction point target)
│   └── detail_Vietnam_*.csv
├── data/
│   └── failed/
│       └── failed_rows_20260616.jsonl   ← moved from output/
├── logs/
│   ├── crawl_20260616_142345.log        ← existing (supervisor tee)
│   └── audit/
│       └── segment_audit.log            ← new: segment verification record
└── scripts/
    ├── auto_set_expected.py
    └── generate_manifest.py
```

**Status file** (new, written by crawler after each page):
```
data/status.json
```
```json
{
  "account": "acc1",
  "batch_item": "54_Import_Q1",
  "segment_current": 3,
  "segment_total": 12,
  "page_current": 145,
  "page_total_estimate": 333,
  "records_scraped": 4350,
  "records_expected": 9990,
  "status": "running",
  "last_update": "2026-06-16T14:23:45",
  "errors_last_hour": 0,
  "failed_rows_pending": 2,
  "uptime_seconds": 14523
}
```

---

## 5. Part B — Go Management Tool (`crawl-manager`)

### B1. Repository Layout

```
D:\Dieplai\sts_pipeline_server\tools\crawl-manager\
├── main.go
├── go.mod
├── go.sum
├── cmd/
│   ├── root.go        ← cobra root, default → TUI
│   ├── status.go      ← crawl-manager status --json
│   ├── logs.go        ← crawl-manager logs acc1 --lines 100
│   ├── config.go      ← crawl-manager config get/set
│   ├── start.go       ← crawl-manager start acc1
│   └── stop.go        ← crawl-manager stop acc1
├── internal/
│   ├── ssh/
│   │   ├── pool.go    ← connection pool (reuse across polls)
│   │   └── client.go  ← SSH + SFTP operations
│   ├── pipeline/
│   │   ├── crawler.go ← poll crawl status.json + tail logs
│   │   ├── dq.go      ← read DQ gate log (local file)
│   │   ├── loader.go  ← read pipeline loader log (local file)
│   │   └── model.go   ← shared StageStatus struct
│   ├── config/
│   │   └── accounts.go ← account definitions, SSH key path
│   └── tui/
│       ├── app.go      ← bubbletea main model
│       ├── dashboard.go ← pipeline overview panel
│       ├── logview.go   ← scrollable log panel
│       └── configedit.go ← config editor form
└── config/
    └── accounts.yaml   ← account + server definitions
```

### B2. Account Configuration (`config/accounts.yaml`)

```yaml
ssh:
  key_path: C:\Users\tanmi\.ssh\id_rsa_sts
  user: pc
  timeout_seconds: 10

accounts:
  - id: acc1
    host: 100.76.219.16
    deploy_dir: C:/CRAWL_STS/ACC1/DEPLOY_ACC_1
    scheduler_task: STS_Crawl_ACC1

  - id: acc2
    host: 100.76.219.16
    deploy_dir: C:/CRAWL_STS/ACC2/DEPLOY_ACC_2
    scheduler_task: STS_Crawl_ACC2

  - id: acc3
    host: 100.76.65.2
    deploy_dir: C:/CRAWL_STS/ACC3/DEPLOY_ACC_3
    scheduler_task: STS_Crawl_ACC3

  - id: acc4
    host: 100.76.65.2
    deploy_dir: C:/CRAWL_STS/ACC4/DEPLOY_ACC_4
    scheduler_task: STS_Crawl_ACC4

pipeline:
  dq_log:      D:\Dieplai\sts_pipeline_server\logs\dq_gate.log
  loader_log:  D:\Dieplai\sts_pipeline_server\logs\pipeline_loader.log
  gold_log:    D:\Dieplai\sts_pipeline_server\logs\gold_tables.log
  audit_log:   D:\Dieplai\sts_pipeline_server\logs\segment_audit.log
```

### B3. TUI Layout

**Full-pipeline view (default tab):**

```
+==================== STS Pipeline Monitor ============================+
|                                           2026-06-16 14:23:45        |
+-- [1] CRAWL -------------------------------------------------------+
| ACC1 [.16]  54_Import_Q1   Seg  3/12  [########--]  4,350  RUNNING  |
| ACC2 [.16]  52_Export      Seg  1/ 8  [##--------]    280  RUNNING  |
| ACC3 [.2 ]  55_Import_Q2   Seg  5/15  [##########]  8,120  RUNNING  |
| ACC4 [.2 ]  57_Export      Seg  2/ 6  ERROR          1,050  RETRY   |
+-- [2] SYNC --------------------------------------------------------+
| Last sync: 14:00:00   Files: 12   Transferred: 2.3 GB   OK          |
+-- [3] DQ GATE -----------------------------------------------------+
| Last run: 13:55:00    Passed: 11/12   Failed: 1     WARNING         |
+-- [4] STAGING LOAD ------------------------------------------------+
| Last run: 13:50:00    Rows loaded: 450,230   Duration: 12m   OK     |
+-- [5] GOLD TABLES -------------------------------------------------+
| Last run: 13:45:00    Tables: 5   Duration: 3m   OK                 |
+-- LOGS [ACC1] ------------------------------------------------------+
| 2026-06-16 14:23:47 | INFO    | PAGE  | Page 16/333: 30 records     |
| 2026-06-16 14:23:49 | INFO    | PAGE  | Page 17/333: 30 records     |
| 2026-06-16 14:23:50 | WARNING | VERIFY| Seg 2: 9,987/9,990 - OK     |
+--------------------------------------------------------------------+
| [Tab] Cycle logs   [C] Config   [S] Start   [X] Stop   [Q] Quit    |
+====================================================================+
```

Navigation:
- `Tab` — cycle log panel between acc1/acc2/acc3/acc4/dq/loader/gold
- `1–5` — jump to stage detail view
- `C` — open config editor for focused crawl account
- `S` — start focused crawl account (via Task Scheduler)
- `X` — stop focused crawl account
- `R` — force refresh now
- `Q` — quit
- `?` — help overlay

### B4. SSH Polling Model

```go
// internal/ssh/pool.go
// One persistent SSH client per host (not per account).
// Two hosts = two persistent connections.
// Each poll: concurrent goroutines per account, share the host connection.
// Poll interval: 10 seconds
// Poll timeout: 5 seconds per account (non-blocking)
// On connection loss: exponential backoff reconnect (1s, 2s, 4s, 8s, max 30s)
```

Per poll, for each crawl account:
1. SFTP read `data/status.json` → parse into `CrawlStatus`
2. SSH exec `Get-Content logs\crawl_*.log -Tail 100` → append to log ring buffer (10,000 lines max per account)

For pipeline stages (local reads, no SSH):
- Read last 100 lines of each log file directly from `D:\Dieplai\sts_pipeline_server\logs\`
- Parse structured log lines into `StageStatus`

### B5. Config Editor

The TUI config editor renders the `TRANSACTIONS_BATCH` list as an editable form. On save:

1. Serialize updated config to `_local.py` format
2. SFTP write to `deploy_dir/src/config/_local.py` on the crawl server
3. Log: `CONFIG | acc1: 54_Import_Q1 expected updated 999999 -> 117134`

Fields editable in TUI: `expected`, `start_date`, `end_date`, `buyer`, `supplier`.  
Fields read-only in TUI: `name`, `hs_code`, `data_type` (structural fields, edit via CLI).

### B6. Start/Stop via Task Scheduler

```go
// Start: SSH exec on crawl server
"schtasks /run /tn STS_Crawl_ACC1"

// Stop: write stop-signal file that supervisor checks
// OR: SSH exec taskkill targeting instance name
"taskkill /f /fi \"WINDOWTITLE eq acc1*\""
```

### B7. CLI Subcommands

```
crawl-manager                                 Default: launch TUI
crawl-manager status                          Print table of all accounts
crawl-manager status --json                   Machine-readable JSON output
crawl-manager logs acc1                       Print last 100 lines
crawl-manager logs acc1 --lines 200           
crawl-manager logs --stage dq                 Print DQ gate log
crawl-manager logs --stage loader             Print pipeline loader log
crawl-manager config get acc1                 Print current _local.py
crawl-manager config set acc1 \
  --item 57_Export_Full --field expected \
  --value 28698                               Update one field, push via SFTP
crawl-manager start acc1                      Trigger Task Scheduler task
crawl-manager stop acc1                       Stop crawl process
```

### B8. Build and Deployment

```
# Cross-compile for Windows from any platform
GOOS=windows GOARCH=amd64 go build -o crawl-manager.exe ./cmd/crawl-manager

# Place binary + config
D:\Dieplai\sts_pipeline_server\tools\crawl-manager.exe
D:\Dieplai\sts_pipeline_server\tools\config\accounts.yaml
```

Single binary, no runtime dependencies. Run from any terminal on the main server.

---

## 6. Dependencies

### Go libraries
```
github.com/charmbracelet/bubbletea   v1.x   TUI framework
github.com/charmbracelet/bubbles     v0.x   Table, viewport, textinput
github.com/charmbracelet/lipgloss    v1.x   Styling
github.com/spf13/cobra               v1.x   CLI subcommands
golang.org/x/crypto/ssh              latest SSH client
gopkg.in/yaml.v3                     v3.x   Config file parsing
```

### Python (crawl engine)
No new dependencies. Changes are within existing code.

---

## 7. Error Handling

| Scenario | Handling |
|----------|----------|
| SSH connection lost during poll | Mark account as UNKNOWN in TUI, reconnect with backoff |
| Crawl account not running | `status.json` stale > 5min → show STOPPED |
| Config push fails | Show error in TUI, do not apply partial write |
| Start/stop command fails | Show stderr output in TUI log panel |
| Segment verification fails twice | Log ERROR to audit log, continue to next segment |
| failed_rows retry exhausted | Entries remain in `failed_rows_YYYYMMDD.jsonl` for manual review |

---

## 8. Testing

### Crawl engine changes
- Unit test `_wait_rows_stable()` with mock DOM states
- Integration test: run acc1 in test mode (`DETAIL_MAX_PAGES=5`), verify no data loss vs current baseline
- Timing benchmark: compare page navigation time before and after (should be 6–7s faster)

### Go management tool
- Unit test SSH pool reconnect logic (mock SSH server)
- Unit test config serializer (round-trip `_local.py` parse → edit → serialize)
- Integration test: connect to real crawl server, read status.json, verify TUI renders correctly
- Manual test: start/stop via TUI on acc1 while acc2 runs unaffected

---

## 9. Rollout Order

1. **A5 (Enterprise logging)** — lowest risk, no logic change, deploy first
2. **A1 (Smart page navigation)** — highest impact on speed, test with `DETAIL_MAX_PAGES=5` before production
3. **A3 + A4 (Failed retry + verification)** — data integrity guards, deploy together
4. **A2 (Concurrency tuning)** — config change only, easy to revert
5. **A6 (Directory restructure)** — update paths, migrate existing `failed_rows.jsonl` files
6. **B (Go management tool)** — build and deploy after crawl changes are stable
