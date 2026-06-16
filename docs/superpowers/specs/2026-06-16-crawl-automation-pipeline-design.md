# Crawl → Validate → Pipeline Automation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to implement this spec task-by-task.

**Goal:** Automate the full data journey from crawl completion on 2 remote servers → rsync pull → DQ gate → PostgreSQL staging → daily Gold rebuild, with zero manual steps and guaranteed data integrity at every layer.

**Architecture:** Pull-based rsync (this storage machine polls crawl servers every 5 min via Task Scheduler). Post-crawl manifest files provide row count + SHA256 lineage. Per-file DQ gate quarantines bad files without blocking good ones. Gold tables rebuild nightly from a full staging reload.

**Tech Stack:** Python 3.x, PostgreSQL 13 (port 5433, db=sts-dev), Windows Task Scheduler, robocopy (LAN share), psycopg2, pandas, hashlib, smtplib.

---

## Topology

```
Crawl Server 1 (acc1, acc3)          Crawl Server 2 (acc2, acc4)
  output\hs*\*.csv                     output\hs*\*.csv
  output\manifests\*.manifest.json     output\manifests\*.manifest.json
       ▲  robocopy pull (every 5 min)       ▲
       └──────────────────────────────────┘
                     │
         THIS MACHINE (Storage + Automation)
         D:\datacenter\
           bronze\2026\hs*\*.csv       ← immutable after landing
           landing\manifests\pending\  ← new manifests
           landing\manifests\done\     ← processed manifests
           quarantine\YYYY-MM-DD\      ← DQ-failed files
           logs\audit_YYYYMMDD.jsonl   ← structured event log
         PostgreSQL localhost:5433
           crawling_data.hs_raw_import / hs_raw_export
           crawling_data.ingestion_log
           import.Fact_2025 / Fact_2026
           export.Fact_2025 / Fact_2026
```

---

## Data Integrity Chain

Every row is tracked from crawl to gold. No step can fail silently.

```
[Crawl writes CSV]
    → SHA256 + row_count → manifest.json
    → robocopy pull
    → SHA256 re-verify after transfer
    → file stability check (size stable 5s)
    → DQ gate per file (pass or quarantine)
    → COPY to staging (psycopg2 copy_expert)
    → row reconciliation: staged vs manifest (gap ≤ 1%)
    → [3 AM] TRUNCATE + reload Gold from staging
    → FK rate check: buyer_id, date_id, hs2_id ≥ 85%
```

### DQ Gate Rules (per file)

| Rule | Threshold | Fail action |
|---|---|---|
| Row count | ≥ 100 rows | Quarantine |
| HS code prefix match | ≥ 95% rows match filename hs code | Quarantine |
| Date parseability | ≤ 5% unparseable | Warn only |
| Negative amounts | 0 negative values | Quarantine |
| Amount null rate | ≤ 5% null (new format only) | Warn only |
| SHA256 match | Exact match vs manifest | Re-pull, alert |

Files that WARN but not FAIL are loaded normally; warnings are recorded in ingestion_log and the audit JSONL.

### Row Reconciliation

After staging load, compare `ingestion_log.row_count` vs `manifest.files[n].rows_crawled`:
- Gap ≤ 1% → OK (accounts for DQ field-level drops)
- Gap > 1% → email alert, record in audit log. **Do not block** — staging data is already loaded; alert lets operator investigate.

---

## Files To Create

### On Crawl Servers — `01_crawl_tool/`

**`scripts/generate_manifest.py`** (~80 lines)
- Called by `run_supervised.bat` / `run_supervised.sh` after clean exit
- Reads `--account acc1` from CLI (one arg; account name is hardcoded at top of each supervisor bat/sh)
- Auto-detects batch name from `_local.py` (reads `TRANSACTIONS_BATCH[current_index].name` or falls back to `hs{code}_{type}_{YYYYMM}`)
- Scans `output/hs*/` for CSV files modified in the last 24h (catches files from current crawl session)
- For each CSV: counts rows (line count minus header line), computes SHA256 via hashlib
- Creates `output/manifests/` directory if absent
- Writes `output/manifests/manifest_<account>_<YYYYMMDD_HHMMSS>.json`
- Idempotent: if identical SHA256 files already in a manifest, skips re-writing
- Output: manifest JSON file (see format below)

**Manifest JSON format:**
```json
{
  "schema_version": "1.0",
  "account": "acc1",
  "server_hostname": "CRAWL-SERVER-1",
  "batch_name": "52_Import_MAY2026",
  "crawl_completed_at": "2026-06-15T14:30:00",
  "attempt_count": 2,
  "files": [
    {
      "name": "detail_Vietnam_import_hs52_MAY_2026.csv",
      "rows_crawled": 12543,
      "size_bytes": 4521432,
      "sha256": "a3f2b1c8d4e9..."
    }
  ],
  "total_rows_crawled": 12543
}
```

**`run_supervised.bat`** — add 1 line to `on_success:` block (before `goto cleanup_and_exit`):
```batch
if exist scripts\generate_manifest.py (
    "!PY!" scripts\generate_manifest.py --account "acc1" >> "!LOG_FILE!" 2>&1
)
```
`acc1` is the only value that changes per machine — hardcode it at the top of each bat file as `set ACCOUNT_NAME=acc1`.

**`scripts/run_supervised.sh`** — add to on_success block (before `stop_hang_watcher`):
```bash
ACCOUNT_NAME="acc1"   # set at top of script, one value per machine
if [[ -f scripts/generate_manifest.py ]]; then
    "$PY" scripts/generate_manifest.py --account "$ACCOUNT_NAME" \
        2>&1 | tee -a "$LOG_FILE" || true
fi
```

---

### On This Machine — `D:\datacenter\scripts\`

**`sync_servers.py`** (~60 lines)
- Reads server list from `D:\datacenter\config\servers.json`
- For each server: runs robocopy over UNC path (`\\SERVER\bronze$` → `D:\datacenter\bronze\2026\`)
- Also syncs manifests: `\\SERVER\manifests$` → `D:\datacenter\landing\manifests\pending\`
- Returns list of newly-arrived files (compares directory listings before/after)
- Logs sync stats (files copied, bytes transferred, duration)

**`servers.json`** format:
```json
[
  {"name": "CRAWL-SERVER-1", "unc_bronze": "\\\\SERVER1\\bronze$", "unc_manifests": "\\\\SERVER1\\manifests$"},
  {"name": "CRAWL-SERVER-2", "unc_bronze": "\\\\SERVER2\\bronze$", "unc_manifests": "\\\\SERVER2\\manifests$"}
]
```

**`dq_gate.py`** (~120 lines)
- Single public function: `check_file(path: Path) -> DQResult`
- `DQResult` dataclass: `{passed, errors, warnings, row_count, col_count, hs_code, trade_type, checks}`
- Reuses parse logic from `03_data_quality.py` — imports `parse_filename`, `REQUIRED_COLS_NEW`, `REQUIRED_COLS_OLD`
- On FAIL: moves file to `D:\datacenter\quarantine\<YYYY-MM-DD>\<filename>`, writes `<filename>.meta.json` alongside
- Never raises exceptions — all failures captured in DQResult

**`pipeline_watcher.py`** (~200 lines)

```
Entry point: python pipeline_watcher.py [--once] [--no-sync] [--dry-run]

Flow:
  1. Acquire lock (D:\datacenter\.watcher.lock) — exit if locked.
     Stale lock detection: if lock file mtime > 10 minutes ago, delete and proceed
     (guards against crash leaving lock behind).
  2. sync_servers.py (skip if --no-sync)
  3. Discover: rglob bronze/**/*.csv → filter out ingestion_log status='loaded'
  4. Sort by mtime ascending (process oldest first)
  5. Per file loop:
     a. Stability check: stat().st_size same after 5s sleep
     b. SHA256 verify vs manifest if manifest found for this file;
        if no manifest exists for this file, skip SHA256 check and proceed
     c. dq_gate.check_file()
        - PASS  → load_file() from 04_load_staging (imported as function)
                  → reconcile row count vs manifest
        - FAIL  → quarantine already done by dq_gate; write audit event; send alert
     d. Write audit JSONL event
  6. Manifest completion check: all files in manifest loaded → move pending→done
  7. Summary email if any files processed this run
  8. Release lock
```

Flags:
- `--once`: run once and exit (for Task Scheduler and testing)
- `--no-sync`: skip robocopy step (use local files; for testing)
- `--dry-run`: run DQ and reconciliation, do not write to DB

**`gold_rebuild.py`** (~80 lines)
- Captures row counts BEFORE rebuild (SELECT COUNT per Fact table)
- Calls `06_run_gold.py` via subprocess (captures stdout to log)
- Captures row counts AFTER rebuild
- Checks FK rates: `COUNT(buyer_id)/COUNT(*) >= 0.85` for Fact_2026
- Sends email report with: rows before/after per table, FK rates, duration, any errors
- Exit code 0 on success, 1 on any error (Task Scheduler sees failure)

**`test_pipeline.py`** (~100 lines)

```
python test_pipeline.py [--crawl] [--skip-gold]

Steps:
  1. [--crawl] Run mini crawl: set DETAIL_MAX_PAGES=2, hs_code=52, import
     → writes ~60 rows to bronze\2026\hs52\detail_Vietnam_import_hs52_TEST.csv
  2. Create mock manifest pointing to that file (sha256 computed from file)
  3. Run pipeline_watcher.py --once --no-sync --dry-run
     → prints DQ result + reconciliation result; assert all pass
  4. Run pipeline_watcher.py --once --no-sync
     → loads to staging; assert ingestion_log entry exists with status='loaded'
  5. Assert staging row count matches manifest rows_crawled (gap ≤ 1%)
  6. [--skip-gold skips this] Run gold_rebuild.py --dry-run
     → validate SQL compiles; no DB changes
  7. Run verify_all.py → print full health check
  8. Print PASS / FAIL summary
```

**`setup_task_scheduler.ps1`** (~50 lines)
- Creates two Task Scheduler tasks:
  - `STS_PipelineWatcher`: every 5 minutes, `python pipeline_watcher.py --once`, working dir `D:\datacenter\scripts`
  - `STS_GoldRebuild`: daily 03:00 AM, `python gold_rebuild.py`
- Sets task to run whether user logged in or not
- Writes confirmation of both tasks created

---

## Audit Log Format (JSONL)

Every event appended to `D:\datacenter\logs\audit_YYYYMMDD.jsonl`:

```jsonl
{"ts":"2026-06-15T14:25:00","event":"sync_start","servers":["CRAWL-SERVER-1","CRAWL-SERVER-2"]}
{"ts":"2026-06-15T14:25:42","event":"sync_done","files_new":3,"bytes_transferred":9876543}
{"ts":"2026-06-15T14:25:43","event":"sha256_ok","file":"detail_Vietnam_import_hs52_MAY_2026.csv"}
{"ts":"2026-06-15T14:25:44","event":"dq_pass","file":"detail_Vietnam_import_hs52_MAY_2026.csv","rows":12543,"warnings":1}
{"ts":"2026-06-15T14:25:48","event":"staging_loaded","file":"detail_Vietnam_import_hs52_MAY_2026.csv","rows_staged":12543,"duration_s":4.1}
{"ts":"2026-06-15T14:25:48","event":"reconcile_ok","file":"detail_Vietnam_import_hs52_MAY_2026.csv","expected":12543,"staged":12543,"gap_pct":0.0}
{"ts":"2026-06-15T14:25:49","event":"manifest_done","manifest":"manifest_acc1_52_Import_MAY2026_20260615_143000.json"}
{"ts":"2026-06-15T14:25:49","event":"run_summary","files_processed":3,"files_quarantined":0,"rows_total":37629}
```

---

## Implementation Order

Build and test in this sequence so each step is independently verifiable:

1. **`dq_gate.py`** — extract DQ logic, test with existing bronze files
2. **`generate_manifest.py`** — test locally by pointing at existing CSVs
3. **`sync_servers.py`** — test with one server (or localhost as mock)
4. **`pipeline_watcher.py`** — test with `--no-sync --once` against local files
5. **`gold_rebuild.py`** — test against staging data already in DB
6. **`test_pipeline.py`** — runs full local E2E; must pass before any deploy
7. **`setup_task_scheduler.ps1`** — run after E2E passes
8. **Deploy to crawl servers:** copy `generate_manifest.py`, patch `run_supervised.bat/.sh`
9. **Configure robocopy shares** on both crawl servers
10. **First live run:** monitor audit log + email alerts for 1 full crawl cycle

---

## What Does NOT Change

- `03_data_quality.py` — imported as a module by `dq_gate.py`, not modified
- `04_load_staging.py` — `load_file()` function imported directly, not modified
- `06_run_gold.py` — called via subprocess, not modified
- `verify_all.py` — used in test pipeline, not modified
- Bronze file naming convention — unchanged
- PostgreSQL schema — no changes

---

## Success Criteria

- [ ] `test_pipeline.py` exits 0 with all assertions passing on this machine
- [ ] Task Scheduler runs `pipeline_watcher.py` every 5 min without manual intervention
- [ ] After a crawl batch completes on a server, data appears in `hs_raw_import`/`hs_raw_export` within 10 minutes
- [ ] Files that fail DQ never reach staging (verified by querying ingestion_log)
- [ ] Gold tables rebuild nightly; FK rates logged in email report
- [ ] Every event traceable in `audit_YYYYMMDD.jsonl`
- [ ] No manual step required after initial Task Scheduler setup
