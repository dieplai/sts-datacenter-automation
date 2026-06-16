# Crawl Automation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully automate the data journey from crawl completion on 2 remote servers → rsync pull → per-file DQ gate → PostgreSQL staging → nightly Gold rebuild, with zero manual steps.

**Architecture:** Pull-based: this storage machine (Windows 11) polls crawl servers every 5 min via Task Scheduler + robocopy over UNC share. Post-crawl manifests provide SHA256 + row counts. Per-file DQ gate quarantines bad files without blocking good ones. Gold tables rebuild nightly at 3 AM via 06_run_gold.py subprocess.

**Tech Stack:** Python 3.x, PostgreSQL 13 (localhost:5433, db=sts-dev), psycopg2, pandas, hashlib, smtplib, Windows Task Scheduler, robocopy.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `D:\datacenter\scripts\dq_gate.py` | **Create** | Per-file DQ with quarantine; mirrors logic from 03_data_quality.py |
| `D:\Dieplai\sts_pipeline_server\01_crawl_tool\scripts\generate_manifest.py` | **Create** | Post-crawl manifest: SHA256 + row counts per CSV |
| `D:\datacenter\config\servers.json` | **Create** | UNC paths for robocopy from crawl servers |
| `D:\datacenter\scripts\sync_servers.py` | **Create** | robocopy pull from both crawl servers |
| `D:\datacenter\scripts\pipeline_watcher.py` | **Create** | Main orchestrator: sync → DQ → staging → reconcile |
| `D:\datacenter\scripts\gold_rebuild.py` | **Create** | Nightly gold rebuild wrapper with email |
| `D:\datacenter\scripts\test_pipeline.py` | **Create** | Local E2E test (runs full pipeline against synthetic data) |
| `D:\datacenter\scripts\setup_task_scheduler.ps1` | **Create** | Register Windows Task Scheduler tasks |
| `D:\Dieplai\sts_pipeline_server\01_crawl_tool\run_supervised.bat` | **Modify** | Add generate_manifest.py call in on_success block |
| `D:\Dieplai\sts_pipeline_server\01_crawl_tool\scripts\run_supervised.sh` | **Modify** | Same for Linux crawl servers |

**Not modified:** 03_data_quality.py, 04_load_staging.py, 06_run_gold.py, verify_all.py, PostgreSQL schema.

---

### Task 1: dq_gate.py — Per-file DQ with quarantine

**Files:**
- Create: `D:\datacenter\scripts\dq_gate.py`

- [ ] **Step 1: Write dq_gate.py**

```python
"""
D:\datacenter\scripts\dq_gate.py
Per-file DQ gate. check_file() returns DQResult and quarantines failing files.
Logic mirrors 03_data_quality.py checks; adds quarantine and dataclass return.
"""

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

QUARANTINE_DIR = Path(r"D:\datacenter\quarantine")

REQUIRED_COLS_NEW = ["Buyer", "Supplier", "HS Code", "Transaction Date", "Amount", "bill_id"]
REQUIRED_COLS_OLD = ["Buyer", "Supplier", "HS Code", "Transaction Date"]
EXPECTED_COLS = {"import": 61, "export": 89}
COL_TOLERANCE = 5
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass
class DQResult:
    file: str
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    checks: dict = field(default_factory=dict)
    quarantined: bool = False
    quarantine_path: Optional[str] = None


def _parse_filename(fname: str) -> Optional[dict]:
    m = re.match(
        r"detail_Vietnam_(import|export)_hs(\d+)_([A-Z]+)(?:_([A-Z]+))?_(\d{4})",
        fname, re.I,
    )
    if not m:
        return None
    start_mon = m.group(3).upper()
    end_mon = m.group(4).upper() if m.group(4) else start_mon
    year = int(m.group(5))
    month_tag = f"{start_mon}_{end_mon}" if end_mon != start_mon else start_mon
    return {"trade": m.group(1).lower(), "hs": m.group(2),
            "month": month_tag, "year": year}


def _quarantine(f: Path, errors: List[str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    dest_dir = QUARANTINE_DIR / today
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f.name
    shutil.move(str(f), str(dest))
    meta = {"file": f.name, "quarantined_at": datetime.now().isoformat(), "errors": errors}
    (dest_dir / f"{f.name}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(dest)


def check_file(f: Path, quarantine: bool = True) -> DQResult:
    """Run DQ checks on a single CSV. Quarantines on hard-fail. Never raises."""
    result = DQResult(file=f.name, passed=True)
    meta = _parse_filename(f.name)
    trade = meta["trade"] if meta else "unknown"
    hs = meta["hs"] if meta else None

    try:
        try:
            df = pd.read_csv(f, dtype=str, encoding="utf-8-sig",
                             on_bad_lines="skip", low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(f, dtype=str, encoding="latin-1",
                             on_bad_lines="skip", low_memory=False)
    except Exception as e:
        result.passed = False
        result.errors.append(f"Cannot read CSV: {e}")
        if quarantine:
            result.quarantine_path = _quarantine(f, result.errors)
            result.quarantined = True
        return result

    result.row_count = len(df)
    result.col_count = len(df.columns)

    # A) Required columns
    is_old = meta and meta["year"] < 2026 and "bill_id" not in df.columns
    req = REQUIRED_COLS_OLD if is_old else REQUIRED_COLS_NEW
    missing = [c for c in req if c not in df.columns]
    result.checks["A_required_cols"] = {"pass": not missing, "missing": missing}
    if missing:
        result.errors.append(f"Missing required cols: {missing}")
        result.passed = False

    # B) Row count >= 100 (hard fail)
    ok_rows = result.row_count >= 100
    result.checks["B_row_count"] = {"pass": ok_rows, "row_count": result.row_count}
    if not ok_rows:
        result.errors.append(f"Row count too low: {result.row_count} (need >= 100)")
        result.passed = False

    # C) HS prefix match >= 95%
    if "HS Code" in df.columns and hs:
        total = df["HS Code"].notna().sum()
        wrong = df[~df["HS Code"].astype(str).str.startswith(hs)]["HS Code"].dropna()
        wrong_pct = round(len(wrong) / total * 100, 2) if total > 0 else 0.0
        result.checks["C_hs_match"] = {"pass": wrong_pct <= 5.0, "wrong_pct": wrong_pct}
        if wrong_pct > 5.0:
            result.errors.append(f"HS prefix mismatch: {wrong_pct:.1f}% > 5%")
            result.passed = False

    # D) Date parseability — warn only
    if "Transaction Date" in df.columns:
        parsed = pd.to_datetime(df["Transaction Date"], errors="coerce")
        bad_pct = round(parsed.isna().mean() * 100, 2)
        result.checks["D_date_parse"] = {
            "pass": bad_pct <= 5.0,
            "unparseable_pct": bad_pct,
            "date_min": str(parsed.dropna().min().date()) if parsed.notna().any() else None,
            "date_max": str(parsed.dropna().max().date()) if parsed.notna().any() else None,
        }
        if bad_pct > 5.0:
            result.warnings.append(f"Date parse failure: {bad_pct}%")

    # E) Amount: no negatives (hard fail), high nulls (warn)
    if "Amount" in df.columns:
        amounts = pd.to_numeric(df["Amount"], errors="coerce")
        neg = int((amounts < 0).sum())
        null_pct = round(amounts.isna().mean() * 100, 2)
        result.checks["E_amount"] = {"pass": neg == 0, "negative": neg, "null_pct": null_pct}
        if neg > 0:
            result.errors.append(f"Negative amounts: {neg} rows")
            result.passed = False
        if null_pct >= 5.0:
            result.warnings.append(f"Amount null rate: {null_pct:.1f}%")

    # F) Key-field null rates — warn only
    for col in ("Buyer", "Supplier", "HS Code"):
        if col in df.columns:
            rate = round(df[col].isna().mean() * 100, 2)
            if rate > 10:
                result.warnings.append(f"High null '{col}': {rate:.1f}%")

    # G) Column count vs expected — warn only
    expected = EXPECTED_COLS.get(trade)
    if expected:
        diff = abs(result.col_count - expected)
        result.checks["G_col_count"] = {
            "pass": diff <= COL_TOLERANCE,
            "expected": expected,
            "actual": result.col_count,
        }
        if diff > COL_TOLERANCE:
            result.warnings.append(
                f"Col count {result.col_count} vs expected {expected} for {trade}"
            )

    if not result.passed and quarantine:
        result.quarantine_path = _quarantine(f, result.errors)
        result.quarantined = True

    return result
```

- [ ] **Step 2: Smoke-test dq_gate on an existing bronze CSV**

```
cd D:\datacenter\scripts
python -c "
from pathlib import Path
from dq_gate import check_file

# pick the first CSV in bronze
csv = next(Path(r'D:\datacenter\bronze').rglob('*.csv'), None)
if not csv:
    print('No CSVs found')
else:
    r = check_file(csv, quarantine=False)
    print('passed:', r.passed)
    print('rows:', r.row_count)
    print('errors:', r.errors)
    print('warnings:', r.warnings)
"
```

Expected: `passed: True` (or False with printed errors for genuinely bad files). No exception.

---

### Task 2: generate_manifest.py — Post-crawl data lineage on crawl servers

**Files:**
- Create: `D:\Dieplai\sts_pipeline_server\01_crawl_tool\scripts\generate_manifest.py`

- [ ] **Step 1: Write generate_manifest.py**

```python
"""
D:\Dieplai\sts_pipeline_server\01_crawl_tool\scripts\generate_manifest.py
Run after each crawl batch to record SHA256 + row counts per CSV.
Usage: python scripts/generate_manifest.py --account acc1
"""

import argparse
import csv
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
MANIFESTS_DIR = OUTPUT_DIR / "manifests"
SENTINEL = OUTPUT_DIR / ".last_manifest_ts"
LOOKBACK_HOURS = 24


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            return max(0, sum(1 for _ in reader) - 1)
    except Exception:
        return 0


def _detect_batch_name(account: str) -> str:
    try:
        cfg = ROOT / "src" / "config" / "_local.py"
        if cfg.is_file():
            ns: dict = {}
            exec(cfg.read_text(encoding="utf-8"), ns)
            batches = ns.get("TRANSACTIONS_BATCH", [])
            if batches:
                return batches[-1].get("name", f"{account}_batch")
    except Exception:
        pass
    return f"{account}_{datetime.now().strftime('%Y%m')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    args = ap.parse_args()

    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - LOOKBACK_HOURS * 3600
    if SENTINEL.is_file():
        cutoff = max(cutoff, SENTINEL.stat().st_mtime)

    csv_files = [
        f for f in OUTPUT_DIR.rglob("*.csv")
        if f.stat().st_mtime >= cutoff
    ]

    if not csv_files:
        print(f"[manifest] No new CSV files since last manifest.", file=sys.stderr)
        return

    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)

    files_meta = []
    total_rows = 0
    for f in sorted(csv_files):
        rows = _count_rows(f)
        sha = _sha256(f)
        files_meta.append({
            "name": f.name,
            "rows_crawled": rows,
            "size_bytes": f.stat().st_size,
            "sha256": sha,
        })
        total_rows += rows
        print(f"[manifest]   {f.name}: {rows:,} rows  sha256={sha[:12]}...")

    batch_name = _detect_batch_name(args.account)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = {
        "schema_version": "1.0",
        "account": args.account,
        "server_hostname": socket.gethostname(),
        "batch_name": batch_name,
        "crawl_completed_at": datetime.now().isoformat(),
        "attempt_count": int(os.environ.get("CRAWL_ATTEMPT", "1")),
        "files": files_meta,
        "total_rows_crawled": total_rows,
    }

    out = MANIFESTS_DIR / f"manifest_{args.account}_{ts}.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[manifest] Written: {out.name}  ({len(files_meta)} files, {total_rows:,} rows)")

    SENTINEL.write_text(ts)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test locally**

```
cd D:\Dieplai\sts_pipeline_server\01_crawl_tool
venv\Scripts\python.exe scripts\generate_manifest.py --account acc5
```

Expected: `[manifest] No new CSV files since last manifest.` (output dir is empty or files are old).

---

### Task 3: servers.json — Crawl server UNC paths

**Files:**
- Create: `D:\datacenter\config\servers.json`

- [ ] **Step 1: Write servers.json**

```json
[
  {
    "name": "CRAWL-SERVER-1",
    "unc_bronze":    "\\\\CRAWL-SERVER-1\\bronze$",
    "unc_manifests": "\\\\CRAWL-SERVER-1\\manifests$"
  },
  {
    "name": "CRAWL-SERVER-2",
    "unc_bronze":    "\\\\CRAWL-SERVER-2\\bronze$",
    "unc_manifests": "\\\\CRAWL-SERVER-2\\manifests$"
  }
]
```

**NOTE:** Replace `CRAWL-SERVER-1` / `CRAWL-SERVER-2` with actual hostnames or IP addresses once the Windows shares are configured on each crawl server. The share names `bronze$` and `manifests$` must match what is actually shared.

---

### Task 4: sync_servers.py — robocopy pull from crawl servers

**Files:**
- Create: `D:\datacenter\scripts\sync_servers.py`

- [ ] **Step 1: Write sync_servers.py**

```python
"""
D:\datacenter\scripts\sync_servers.py
Pull bronze CSVs and manifests from crawl servers via robocopy over UNC share.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

SERVERS_JSON = Path(r"D:\datacenter\config\servers.json")
BRONZE_BASE = Path(r"D:\datacenter\bronze\2026")
MANIFESTS_PENDING = Path(r"D:\datacenter\landing\manifests\pending")


def _robocopy(src: str, dst: Path, label: str) -> dict:
    dst.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    result = subprocess.run(
        [
            "robocopy", src, str(dst),
            "*.csv", "*.json",
            "/E",    # include subdirs
            "/NP",   # no progress %
            "/NDL",  # no dir listing
            "/NFL",  # no file listing
            "/R:2",  # 2 retries
            "/W:5",  # 5s wait between retries
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    duration = round(time.time() - t0, 1)
    # robocopy: rc < 8 = success (0=nothing to do, 1=files copied, etc.)
    ok = result.returncode < 8
    files_copied = 0
    for line in result.stdout.splitlines():
        if "Files :" in line:
            parts = line.split()
            try:
                files_copied = int(parts[1])
            except (IndexError, ValueError):
                pass
    print(f"[sync] {label}: rc={result.returncode} files={files_copied} {duration}s")
    if not ok:
        print(f"[sync] WARN: {result.stderr[:500]}", file=sys.stderr)
    return {"files_copied": files_copied, "duration_s": duration, "ok": ok}


def sync_all() -> list:
    if not SERVERS_JSON.is_file():
        print(f"[sync] ERROR: {SERVERS_JSON} missing — create it first.", file=sys.stderr)
        sys.exit(1)

    servers = json.loads(SERVERS_JSON.read_text(encoding="utf-8"))
    results = []
    for s in servers:
        name = s["name"]
        r_bronze = _robocopy(s["unc_bronze"], BRONZE_BASE, f"{name}/bronze")
        r_mf = _robocopy(s["unc_manifests"], MANIFESTS_PENDING, f"{name}/manifests")
        results.append({"server": name, "bronze": r_bronze, "manifests": r_mf})

    total = sum(r["bronze"]["files_copied"] + r["manifests"]["files_copied"]
                for r in results)
    print(f"[sync] Total files synced: {total}")
    return results


if __name__ == "__main__":
    sync_all()
```

---

### Task 5: pipeline_watcher.py — Main orchestrator

**Files:**
- Create: `D:\datacenter\scripts\pipeline_watcher.py`

- [ ] **Step 1: Write pipeline_watcher.py**

```python
"""
D:\datacenter\scripts\pipeline_watcher.py
Orchestrator: sync → DQ gate → staging load → row reconciliation → audit.

Usage:
  python pipeline_watcher.py           # full run (sync + load)
  python pipeline_watcher.py --once    # same, for Task Scheduler
  python pipeline_watcher.py --no-sync # skip robocopy (test/local mode)
  python pipeline_watcher.py --dry-run # DQ only, no DB writes
"""

import argparse
import hashlib
import json
import os
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import psycopg2

BRONZE_DIR = Path(r"D:\datacenter\bronze")
MANIFESTS_PENDING = Path(r"D:\datacenter\landing\manifests\pending")
MANIFESTS_DONE = Path(r"D:\datacenter\landing\manifests\done")
LOGS_DIR = Path(r"D:\datacenter\logs")
LOCK_FILE = Path(r"D:\datacenter\.watcher.lock")
LOCK_STALE_SECS = 600  # 10 minutes
SCRIPTS = Path(__file__).parent
DB = dict(host="localhost", port=5433, dbname="sts-dev",
          user="dev4", password="IBM@Cognos#")
RECONCILE_GAP = 0.01  # 1%


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _audit(log: Path, event: str, **kw):
    entry = {"ts": _now(), "event": event, **kw}
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    suffix = f"  {kw}" if kw else ""
    print(f"[{entry['ts']}] {event}{suffix}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _send_alert(subject: str, body: str):
    user = os.environ.get("NOTIFY_SMTP_USER", "").strip()
    pwd = os.environ.get("NOTIFY_SMTP_PASS", "").strip()
    to = os.environ.get("NOTIFY_TO_EMAIL", "dieptrungnam123@gmail.com")
    if not user or not pwd:
        print(f"[notify] No SMTP config — skipping: {subject}")
        return
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
        print(f"[notify] Sent: {subject}")
    except Exception as e:
        print(f"[notify] Failed: {e}", file=sys.stderr)


# ── Lock ──────────────────────────────────────────────────────────────────────

def _acquire_lock() -> bool:
    if LOCK_FILE.is_file():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age > LOCK_STALE_SECS:
            print(f"[watcher] Removing stale lock ({age:.0f}s old)")
            LOCK_FILE.unlink()
        else:
            print(f"[watcher] Locked ({age:.0f}s old) — another run active, exiting")
            return False
    LOCK_FILE.write_text(_now())
    return True


def _release_lock():
    LOCK_FILE.unlink(missing_ok=True)


# ── Manifests ─────────────────────────────────────────────────────────────────

def _load_manifests() -> dict:
    """Return {csv_filename: {entry + _manifest_path + _manifest}} for all pending."""
    MANIFESTS_PENDING.mkdir(parents=True, exist_ok=True)
    mapping: dict = {}
    for m_path in MANIFESTS_PENDING.glob("*.json"):
        try:
            m = json.loads(m_path.read_text(encoding="utf-8"))
            for entry in m.get("files", []):
                mapping[entry["name"]] = {**entry,
                                          "_manifest_path": m_path,
                                          "_manifest": m}
        except Exception as e:
            print(f"[watcher] Bad manifest {m_path.name}: {e}")
    return mapping


def _is_loaded(cur, filename: str) -> bool:
    cur.execute(
        "SELECT status FROM crawling_data.ingestion_log WHERE filename = %s",
        (filename,))
    row = cur.fetchone()
    return row is not None and row[0] == "loaded"


def _check_manifest_completion(mapping: dict, conn, audit: Path):
    done: set = set()
    with conn.cursor() as cur:
        for fname, mf in mapping.items():
            m_path = mf["_manifest_path"]
            if m_path in done:
                continue
            m = mf["_manifest"]
            if all(_is_loaded(cur, f["name"]) for f in m.get("files", [])):
                MANIFESTS_DONE.mkdir(parents=True, exist_ok=True)
                m_path.rename(MANIFESTS_DONE / m_path.name)
                _audit(audit, "manifest_done",
                       manifest=m_path.name,
                       account=m.get("account"),
                       batch=m.get("batch_name"))
                done.add(m_path)


# ── Main run ──────────────────────────────────────────────────────────────────

def run(dry_run: bool, no_sync: bool, audit: Path):
    n_processed = n_quarantined = n_rows = 0
    alerts: list = []

    _audit(audit, "run_start", dry_run=dry_run, no_sync=no_sync)

    # 1. Sync
    if not no_sync:
        _audit(audit, "sync_start")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "sync_servers.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        print(r.stdout[-2000:])
        _audit(audit, "sync_done", ok=(r.returncode == 0))
    else:
        print("[watcher] Skipping sync (--no-sync)")

    # 2. Load manifest map
    manifest_map = _load_manifests()

    # 3. Discover new files
    all_csvs = sorted(BRONZE_DIR.rglob("*.csv"), key=lambda p: p.stat().st_mtime)

    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            new_files = (
                all_csvs if dry_run
                else [f for f in all_csvs if not _is_loaded(cur, f.name)]
            )
    finally:
        conn.close()

    print(f"[watcher] {len(new_files)} new file(s) to process")
    if not new_files:
        _audit(audit, "run_summary",
               files_processed=0, files_quarantined=0, rows_total=0, alerts=0)
        return

    # Stability check: wait 5 s, skip files still being written
    sizes_before = {f: f.stat().st_size for f in new_files}
    time.sleep(5)
    stable = [
        f for f in new_files
        if f.is_file() and f.stat().st_size == sizes_before[f]
    ]
    skipped = len(new_files) - len(stable)
    if skipped:
        print(f"[watcher] {skipped} file(s) still writing — next run picks them up")

    # 4. Per-file: SHA256 verify + DQ gate
    sys.path.insert(0, str(SCRIPTS))
    from dq_gate import check_file

    good_files = []
    for f in stable:
        mf = manifest_map.get(f.name)

        # SHA256 check (skipped if no manifest for this file)
        if mf and mf.get("sha256"):
            if _sha256(f) != mf["sha256"]:
                _audit(audit, "sha256_fail", file=f.name)
                alerts.append(f"SHA256 mismatch: {f.name} — re-pull needed")
                continue
            _audit(audit, "sha256_ok", file=f.name)
        else:
            _audit(audit, "no_manifest_sha256", file=f.name)

        dq = check_file(f, quarantine=(not dry_run))
        if not dq.passed:
            n_quarantined += 1
            _audit(audit, "dq_fail", file=f.name,
                   errors=dq.errors, quarantine=dq.quarantine_path)
            alerts.append(f"DQ FAIL {f.name}: {'; '.join(dq.errors)}")
        else:
            if dq.warnings:
                _audit(audit, "dq_warn", file=f.name, warnings=dq.warnings)
            else:
                _audit(audit, "dq_pass", file=f.name, rows=dq.row_count)
            good_files.append(f)

    # 5. Load staging via 04_load_staging.py subprocess
    if not dry_run and good_files:
        t0 = time.time()
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "04_load_staging.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        duration = round(time.time() - t0, 1)
        # Print last 3000 chars to avoid flooding console
        out_tail = result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout
        print(out_tail)
        _audit(audit, "staging_run",
               ok=(result.returncode == 0), duration_s=duration,
               attempted=len(good_files))
        if result.returncode != 0:
            alerts.append(f"04_load_staging.py exited {result.returncode} — check logs")

        # 6. Row reconciliation + manifest completion
        conn2 = psycopg2.connect(**DB)
        try:
            with conn2.cursor() as cur:
                for f in good_files:
                    cur.execute(
                        "SELECT row_count FROM crawling_data.ingestion_log "
                        "WHERE filename = %s AND status = 'loaded'",
                        (f.name,))
                    row = cur.fetchone()
                    if not row:
                        continue
                    staged = row[0]
                    n_rows += staged
                    n_processed += 1
                    _audit(audit, "staging_loaded", file=f.name, rows_staged=staged)

                    mf = manifest_map.get(f.name)
                    if mf and mf.get("rows_crawled"):
                        expected = mf["rows_crawled"]
                        gap = abs(staged - expected) / max(expected, 1)
                        label = "reconcile_ok" if gap <= RECONCILE_GAP else "reconcile_warn"
                        _audit(audit, label, file=f.name,
                               expected=expected, staged=staged,
                               gap_pct=round(gap * 100, 2))
                        if gap > RECONCILE_GAP:
                            alerts.append(
                                f"Row gap {f.name}: expected {expected:,}, "
                                f"got {staged:,} ({gap*100:.1f}%)"
                            )

            _check_manifest_completion(manifest_map, conn2, audit)
        finally:
            conn2.close()

    elif dry_run:
        print(f"[watcher] DRY-RUN: {len(good_files)} file(s) passed DQ, would load to staging")

    # 7. Summary + alert email
    _audit(audit, "run_summary",
           files_processed=n_processed,
           files_quarantined=n_quarantined,
           rows_total=n_rows,
           alerts=len(alerts))

    if n_processed > 0 or n_quarantined > 0 or alerts:
        subject = (
            f"[STS Pipeline] {n_processed} loaded | "
            f"{n_quarantined} quarantined | {n_rows:,} rows"
        )
        body = (
            f"Loaded to staging : {n_processed} files\n"
            f"Quarantined (DQ)  : {n_quarantined} files\n"
            f"Total rows staged : {n_rows:,}\n"
        )
        if alerts:
            body += "\nALERTS:\n" + "\n".join(f"  • {a}" for a in alerts)
        _send_alert(subject, body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="Run once and exit (for Task Scheduler)")
    ap.add_argument("--no-sync", action="store_true",
                    help="Skip robocopy pull (use local files)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run DQ only; no DB writes")
    args = ap.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    audit = LOGS_DIR / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"

    if not _acquire_lock():
        sys.exit(0)
    try:
        run(dry_run=args.dry_run, no_sync=args.no_sync, audit=audit)
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        try:
            _audit(audit, "run_crash", error=str(e))
        except Exception:
            pass
        _send_alert("[STS Pipeline] WATCHER CRASH", err)
        raise
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test dry-run (no DB writes, no sync)**

```
cd D:\datacenter\scripts
python pipeline_watcher.py --no-sync --dry-run
```

Expected output (example):
```
[2026-06-16T...] run_start  {'dry_run': True, 'no_sync': True}
[watcher] Skipping sync (--no-sync)
[watcher] N new file(s) to process
[2026-06-16T...] dq_pass  {'file': '...', 'rows': ...}
[watcher] DRY-RUN: N file(s) passed DQ, would load to staging
[2026-06-16T...] run_summary  {...}
```

No exceptions. Lock file created and deleted.

---

### Task 6: gold_rebuild.py — Nightly gold rebuild wrapper

**Files:**
- Create: `D:\datacenter\scripts\gold_rebuild.py`

- [ ] **Step 1: Write gold_rebuild.py**

```python
"""
D:\datacenter\scripts\gold_rebuild.py
Nightly gold layer rebuild. Run via Task Scheduler at 3 AM.
Calls 06_run_gold.py as subprocess, checks FK rates, sends email report.
"""

import os
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import psycopg2

LOGS_DIR = Path(r"D:\datacenter\logs")
SCRIPTS = Path(__file__).parent
DB = dict(host="localhost", port=5433, dbname="sts-dev",
          user="dev4", password="IBM@Cognos#")
FK_RATE_MIN = 85.0  # %


def _counts(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 'import.Fact_2025', COUNT(*) FROM import."Fact_2025"
            UNION ALL SELECT 'import.Fact_2026', COUNT(*) FROM import."Fact_2026"
            UNION ALL SELECT 'export.Fact_2025', COUNT(*) FROM export."Fact_2025"
            UNION ALL SELECT 'export.Fact_2026', COUNT(*) FROM export."Fact_2026"
        """)
        return {r[0]: r[1] for r in cur.fetchall()}


def _fk_rates(conn) -> dict:
    rates = {}
    with conn.cursor() as cur:
        for yr in (2025, 2026):
            for trade in ("import", "export"):
                tbl = f'{trade}."Fact_{yr}"'
                try:
                    cur.execute(f"""
                        SELECT
                            ROUND(COUNT(buyer_id)::numeric / NULLIF(COUNT(*),0) * 100, 1),
                            ROUND(COUNT(date_id)::numeric  / NULLIF(COUNT(*),0) * 100, 1),
                            ROUND(COUNT(hs2_id)::numeric   / NULLIF(COUNT(*),0) * 100, 1)
                        FROM {tbl}
                    """)
                    r = cur.fetchone()
                    rates[f"{trade}.Fact_{yr}"] = {
                        "buyer_id": float(r[0]) if r[0] is not None else None,
                        "date_id":  float(r[1]) if r[1] is not None else None,
                        "hs2_id":   float(r[2]) if r[2] is not None else None,
                    }
                except Exception:
                    rates[f"{trade}.Fact_{yr}"] = {"error": "table query failed"}
    return rates


def _send(subject: str, body: str):
    user = os.environ.get("NOTIFY_SMTP_USER", "").strip()
    pwd = os.environ.get("NOTIFY_SMTP_PASS", "").strip()
    to = os.environ.get("NOTIFY_TO_EMAIL", "dieptrungnam123@gmail.com")
    if not user or not pwd:
        print(f"[gold] No SMTP config — skipping: {subject}")
        return
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
        print(f"[gold] Email sent: {subject}")
    except Exception as e:
        print(f"[gold] Email failed: {e}", file=sys.stderr)


def main():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"gold_{ts}.log"

    def log(msg: str):
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line)
        with log_file.open("a", encoding="utf-8") as lf:
            lf.write(line + "\n")

    log("=== Gold rebuild START ===")
    conn = psycopg2.connect(**DB)
    before = _counts(conn)
    log(f"Before: { {k: f'{v:,}' for k,v in before.items()} }")

    t0 = time.time()
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "06_run_gold.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    duration = round(time.time() - t0, 1)
    log(f"06_run_gold.py exit={result.returncode}  {duration}s")

    with log_file.open("a", encoding="utf-8") as lf:
        lf.write(result.stdout)
        if result.stderr:
            lf.write(result.stderr)

    if result.returncode != 0:
        log(f"ERROR: gold rebuild failed (rc={result.returncode})")
        _send("[STS Gold] REBUILD FAILED",
              f"rc={result.returncode}\n{result.stderr[-2000:]}")
        conn.close()
        sys.exit(1)

    after = _counts(conn)
    fk = _fk_rates(conn)
    conn.close()

    delta = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    log(f"After:  { {k: f'{v:,}' for k,v in after.items()} }")
    log(f"Delta:  {delta}")
    log(f"FK rates: {fk}")

    # Alert if FK rate below threshold
    alerts = []
    for tbl, rates in fk.items():
        for dim, pct in rates.items():
            if dim == "error":
                alerts.append(f"{tbl}: {rates['error']}")
                continue
            if pct is not None and pct < FK_RATE_MIN:
                alerts.append(f"{tbl}.{dim}={pct}% < {FK_RATE_MIN:.0f}%")

    subject = "[STS Gold] Rebuild OK" + (" (FK alerts)" if alerts else "")
    body = (
        f"Duration: {duration}s\n\n"
        "Row counts before → after:\n" +
        "\n".join(
            f"  {k}: {before.get(k,0):,} → {after.get(k,0):,}  (+{delta.get(k,0):,})"
            for k in sorted(after)
        ) +
        "\n\nFK resolution rates:\n" +
        "\n".join(f"  {tbl}: {rates}" for tbl, rates in fk.items())
    )
    if alerts:
        body += "\n\nALERTS:\n" + "\n".join(f"  • {a}" for a in alerts)

    _send(subject, body)
    log(f"=== Gold rebuild DONE ({duration}s) ===")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify gold_rebuild runs without crash**

```
cd D:\datacenter\scripts
python gold_rebuild.py
```

Expected: logs row counts before/after, exits 0. Email skipped (no SMTP config yet).

---

### Task 7: test_pipeline.py — Local E2E verification

**Files:**
- Create: `D:\datacenter\scripts\test_pipeline.py`

- [ ] **Step 1: Write test_pipeline.py**

```python
"""
D:\datacenter\scripts\test_pipeline.py
Local end-to-end pipeline test. Creates synthetic CSV, runs full pipeline,
verifies staging, then cleans up. All assertions must pass before deploying.

Usage:
  python test_pipeline.py
  python test_pipeline.py --skip-gold   # skip gold_rebuild (faster)
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg2

SCRIPTS = Path(__file__).parent
BRONZE = Path(r"D:\datacenter\bronze\2026\hs52")
LANDING = Path(r"D:\datacenter\landing\manifests\pending")
DB = dict(host="localhost", port=5433, dbname="sts-dev",
          user="dev4", password="IBM@Cognos#")

TEST_CSV_NAME = "detail_Vietnam_import_hs52_JUN_2026_TEST_PIPELINE.csv"
TEST_CSV_PATH = BRONZE / TEST_CSV_NAME

HEADER = (
    "segment,page,stt,Declaration No,Transaction Date,HS Code,"
    "Product Description,Supplier,Buyer,quantity,Quantity unit,"
    "Amount,Currency,Exchange Rate,Import Country,Country of Origin,"
    "Mode of Transport,bill_id"
)


def _make_row(i: int) -> str:
    return (
        f"1,1,{i},DEC{i:06d},2026-06-01,5201.00.00,"
        f"COTTON FIBRE,CHINA COTTON CO LTD,VIET NAM TEXTILE JSC,"
        f"100,KG,{1000+i*10}.00,USD,24000,Vietnam,China,Sea,"
        f"BILL{i:06d}"
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def _db_conn():
    return psycopg2.connect(**DB)


def _assert_staged(filename: str, expected_rows: int):
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT row_count, status FROM crawling_data.ingestion_log "
                "WHERE filename = %s", (filename,))
            row = cur.fetchone()
    finally:
        conn.close()

    assert row is not None, f"FAIL: '{filename}' not in ingestion_log"
    assert row[1] == "loaded", f"FAIL: status='{row[1]}' expected 'loaded'"
    staged = row[0]
    gap = abs(staged - expected_rows) / max(expected_rows, 1)
    assert gap <= 0.01, (
        f"FAIL: row gap {gap*100:.1f}% > 1%  "
        f"(staged={staged:,}, expected={expected_rows:,})"
    )
    print(f"  PASS: staged={staged:,}  expected={expected_rows:,}  gap={gap*100:.2f}%")


def _cleanup(filename: str):
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            # Delete from staging tables
            for tbl in ("crawling_data.hs_raw_import", "crawling_data.hs_raw_export"):
                try:
                    cur.execute(f"DELETE FROM {tbl} WHERE _source_file = %s",
                                (filename,))
                except Exception:
                    conn.rollback()
            cur.execute(
                "DELETE FROM crawling_data.ingestion_log WHERE filename = %s",
                (filename,))
        conn.commit()
        print(f"  Cleanup: removed test data for '{filename}'")
    finally:
        conn.close()

    if TEST_CSV_PATH.is_file():
        TEST_CSV_PATH.unlink()
        print(f"  Cleanup: deleted {TEST_CSV_PATH.name}")

    # Remove test manifest from pending/
    for m in LANDING.glob("*_TEST_PIPELINE_*.json"):
        m.unlink()
        print(f"  Cleanup: deleted manifest {m.name}")


def step(label: str):
    print(f"\n[TEST] {label}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-gold", action="store_true")
    args = ap.parse_args()

    print("\n" + "=" * 60)
    print("STS Pipeline E2E Test")
    print("=" * 60)

    # ── Step 0: cleanup stale test artifact from prior run ────────────────
    step("0. Cleaning up any stale test data from previous runs")
    try:
        _cleanup(TEST_CSV_NAME)
    except Exception as e:
        print(f"  (nothing to clean: {e})")

    # ── Step 1: create synthetic CSV ──────────────────────────────────────
    step("1. Creating synthetic test CSV (150 rows)")
    BRONZE.mkdir(parents=True, exist_ok=True)
    with TEST_CSV_PATH.open("w", encoding="utf-8") as f:
        f.write(HEADER + "\n")
        for i in range(1, 151):
            f.write(_make_row(i) + "\n")
    rows_in_file = _count_rows(TEST_CSV_PATH)
    print(f"  Written: {TEST_CSV_PATH.name}  rows={rows_in_file}")
    assert rows_in_file == 150, f"FAIL: expected 150 rows, got {rows_in_file}"

    # ── Step 2: DQ gate (quarantine=False so test file survives) ─────────
    step("2. Running DQ gate (no-quarantine mode)")
    sys.path.insert(0, str(SCRIPTS))
    from dq_gate import check_file
    dq = check_file(TEST_CSV_PATH, quarantine=False)
    print(f"  passed={dq.passed}  rows={dq.row_count}  errors={dq.errors}")
    assert dq.passed, f"FAIL: DQ gate failed on test file: {dq.errors}"
    print("  PASS: DQ gate")

    # ── Step 3: create mock manifest ──────────────────────────────────────
    step("3. Creating mock manifest")
    LANDING.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = {
        "schema_version": "1.0",
        "account": "test",
        "server_hostname": "LOCAL-TEST",
        "batch_name": "test_pipeline_batch",
        "crawl_completed_at": datetime.now().isoformat(),
        "attempt_count": 1,
        "files": [{
            "name": TEST_CSV_NAME,
            "rows_crawled": rows_in_file,
            "size_bytes": TEST_CSV_PATH.stat().st_size,
            "sha256": _sha256(TEST_CSV_PATH),
        }],
        "total_rows_crawled": rows_in_file,
    }
    m_path = LANDING / f"manifest_test_TEST_PIPELINE_{ts}.json"
    m_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Written: {m_path.name}  rows_crawled={rows_in_file}")

    # ── Step 4: dry-run (DQ + reconcile, no DB write) ─────────────────────
    step("4. pipeline_watcher --no-sync --dry-run")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "pipeline_watcher.py"),
         "--once", "--no-sync", "--dry-run"],
    )
    assert r.returncode == 0, f"FAIL: dry-run exited {r.returncode}"
    print("  PASS: dry-run completed")

    # Remove the lock file if dry-run left it (shouldn't but be safe)
    lock = Path(r"D:\datacenter\.watcher.lock")
    lock.unlink(missing_ok=True)

    # ── Step 5: real run (loads to staging) ───────────────────────────────
    step("5. pipeline_watcher --no-sync (load to staging)")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "pipeline_watcher.py"),
         "--once", "--no-sync"],
    )
    assert r.returncode == 0, f"FAIL: watcher exited {r.returncode}"

    # ── Step 6: assert staging ────────────────────────────────────────────
    step("6. Asserting staging row count vs manifest")
    time.sleep(2)
    _assert_staged(TEST_CSV_NAME, rows_in_file)

    # ── Step 7: gold rebuild ───────────────────────────────────────────────
    if not args.skip_gold:
        step("7. Running gold_rebuild.py")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "gold_rebuild.py")]
        )
        assert r.returncode == 0, f"FAIL: gold_rebuild exited {r.returncode}"
        print("  PASS: gold rebuild")
    else:
        step("7. [SKIPPED] gold rebuild")

    # ── Step 8: verify_all.py ─────────────────────────────────────────────
    step("8. verify_all.py")
    if (SCRIPTS / "verify_all.py").is_file():
        r = subprocess.run([sys.executable, str(SCRIPTS / "verify_all.py")])
        print(f"  verify_all exit={r.returncode}")
    else:
        print("  verify_all.py not found, skipping")

    # ── Cleanup ───────────────────────────────────────────────────────────
    step("9. Cleanup test data")
    _cleanup(TEST_CSV_NAME)

    print("\n" + "=" * 60)
    print("ALL ASSERTIONS PASSED — pipeline is green")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test**

```
cd D:\datacenter\scripts
python test_pipeline.py --skip-gold
```

Expected final output:
```
ALL ASSERTIONS PASSED — pipeline is green
```

---

### Task 8: setup_task_scheduler.ps1 — Task Scheduler automation

**Files:**
- Create: `D:\datacenter\scripts\setup_task_scheduler.ps1`

- [ ] **Step 1: Write setup_task_scheduler.ps1**

```powershell
# D:\datacenter\scripts\setup_task_scheduler.ps1
# Creates two Task Scheduler tasks for the STS pipeline.
# Run as Administrator: powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1

# Python with psycopg2, pandas installed — adjust path if different
$PY = "python"  # use PATH Python; or set full path e.g. "D:\Python311\python.exe"
$SCRIPTS = "D:\datacenter\scripts"

# ── Task 1: pipeline_watcher every 5 minutes ──────────────────────────────
$action1 = New-ScheduledTaskAction `
    -Execute $PY `
    -Argument "pipeline_watcher.py --once" `
    -WorkingDirectory $SCRIPTS

# Repeat every 5 min for 24 hours starting now (Task Scheduler requires a
# start time + repetition interval on a Once trigger)
$trigger1 = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

$settings1 = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
    -MultipleInstances IgnoreNew `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

try {
    Unregister-ScheduledTask -TaskName "STS_PipelineWatcher" -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

Register-ScheduledTask `
    -TaskName "STS_PipelineWatcher" `
    -Action $action1 `
    -Trigger $trigger1 `
    -Settings $settings1 `
    -RunLevel Highest `
    -Force

Write-Host "Created: STS_PipelineWatcher (every 5 min)"

# ── Task 2: gold_rebuild daily at 3 AM ────────────────────────────────────
$action2 = New-ScheduledTaskAction `
    -Execute $PY `
    -Argument "gold_rebuild.py" `
    -WorkingDirectory $SCRIPTS

$trigger2 = New-ScheduledTaskTrigger -Daily -At "03:00"

$settings2 = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 60) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

try {
    Unregister-ScheduledTask -TaskName "STS_GoldRebuild" -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

Register-ScheduledTask `
    -TaskName "STS_GoldRebuild" `
    -Action $action2 `
    -Trigger $trigger2 `
    -Settings $settings2 `
    -RunLevel Highest `
    -Force

Write-Host "Created: STS_GoldRebuild (daily 03:00)"

# Confirm
Write-Host ""
Write-Host "Registered tasks:"
Get-ScheduledTask | Where-Object TaskName -like "STS_*" |
    Select-Object TaskName, State | Format-Table -AutoSize
```

- [ ] **Step 2: Run as Administrator (after test_pipeline.py passes)**

```powershell
powershell -ExecutionPolicy Bypass -File "D:\datacenter\scripts\setup_task_scheduler.ps1"
```

Expected output:
```
Created: STS_PipelineWatcher (every 5 min)
Created: STS_GoldRebuild (daily 03:00)

Registered tasks:
TaskName              State
--------              -----
STS_GoldRebuild       Ready
STS_PipelineWatcher   Ready
```

---

### Task 9: Patch run_supervised.bat — add generate_manifest call

**Files:**
- Modify: `D:\Dieplai\sts_pipeline_server\01_crawl_tool\run_supervised.bat:131-142`

- [ ] **Step 1: Add ACCOUNT_NAME variable and manifest call**

In `run_supervised.bat`, after the line `set RESTART_COOLDOWN=10` (line ~29), add:
```batch
set ACCOUNT_NAME=acc5
```

Then in the `:on_success` block, replace:
```batch
REM Email: complete notification
if exist scripts\notify.py (
    "!PY!" scripts\notify.py --kind complete --reason "clean exit after !ATTEMPT! attempts" --scraper-dir "%CD%" --log "!LOG_FILE!" >> "!LOG_FILE!" 2>&1
)

goto cleanup_and_exit
```

with:
```batch
REM Email: complete notification
if exist scripts\notify.py (
    "!PY!" scripts\notify.py --kind complete --reason "clean exit after !ATTEMPT! attempts" --scraper-dir "%CD%" --log "!LOG_FILE!" >> "!LOG_FILE!" 2>&1
)

REM Generate manifest for post-crawl data lineage
set "CRAWL_ATTEMPT=!ATTEMPT!"
if exist scripts\generate_manifest.py (
    "!PY!" scripts\generate_manifest.py --account "!ACCOUNT_NAME!" >> "!LOG_FILE!" 2>&1
)

goto cleanup_and_exit
```

---

### Task 10: Patch run_supervised.sh — add generate_manifest call

**Files:**
- Modify: `D:\Dieplai\sts_pipeline_server\01_crawl_tool\scripts\run_supervised.sh:172-184`

- [ ] **Step 1: Add generate_manifest call in on_success block**

In the `if [[ $exit_code -eq 0 ]]; then` block, replace:
```bash
    # Email: success notification (so user sees crawl is done).
    if [[ -f scripts/notify.py ]]; then
        "$PY" scripts/notify.py --kind complete \
            --reason "clean exit after $attempt attempts" \
            --scraper-dir "$ROOT_DIR" --log "$LOG_FILE" \
            2>&1 | tee -a "$LOG_FILE" || true
    fi
    stop_hang_watcher
```

with:
```bash
    # Email: success notification (so user sees crawl is done).
    if [[ -f scripts/notify.py ]]; then
        "$PY" scripts/notify.py --kind complete \
            --reason "clean exit after $attempt attempts" \
            --scraper-dir "$ROOT_DIR" --log "$LOG_FILE" \
            2>&1 | tee -a "$LOG_FILE" || true
    fi

    # Generate manifest for post-crawl data lineage
    ACCOUNT_NAME="acc1"   # change per machine: acc1 / acc2 / acc3 / acc4
    export CRAWL_ATTEMPT=$attempt
    if [[ -f scripts/generate_manifest.py ]]; then
        "$PY" scripts/generate_manifest.py --account "$ACCOUNT_NAME" \
            2>&1 | tee -a "$LOG_FILE" || true
    fi

    stop_hang_watcher
```

---

### Task 11: Deploy to crawl servers

- [ ] **Step 1: Copy generate_manifest.py to both crawl servers**

```powershell
# Adjust to actual server UNC paths
$src = "D:\Dieplai\sts_pipeline_server\01_crawl_tool\scripts\generate_manifest.py"
Copy-Item $src "\\CRAWL-SERVER-1\crawl_tool$\scripts\"
Copy-Item $src "\\CRAWL-SERVER-2\crawl_tool$\scripts\"
```

- [ ] **Step 2: On each crawl server, create Windows share for bronze + manifests**

Run on each crawl server (or ask the operator to):
```powershell
# Create bronze share (read-only from storage machine)
New-SmbShare -Name "bronze$" -Path "D:\Dieplai\sts_pipeline_server\01_crawl_tool\output" `
    -FullAccess "DOMAIN\StorageMachine$"

# Create manifests share
New-SmbShare -Name "manifests$" -Path "D:\Dieplai\sts_pipeline_server\01_crawl_tool\output\manifests" `
    -FullAccess "DOMAIN\StorageMachine$"
```

- [ ] **Step 3: Update servers.json with real hostnames**

Edit `D:\datacenter\config\servers.json` with actual server names/IPs.

- [ ] **Step 4: Patch run_supervised.bat/sh on each crawl server**

Each crawl server has its own supervisor. Set `ACCOUNT_NAME` to the account for that machine:
- Crawl Server 1: `ACCOUNT_NAME=acc1` (and `acc3`)
- Crawl Server 2: `ACCOUNT_NAME=acc2` (and `acc4`)

Copy the patched supervisor files or apply the same edits from Task 9/10.

- [ ] **Step 5: First live run — monitor**

```powershell
# On storage machine, watch the audit log live
Get-Content "D:\datacenter\logs\audit_$(Get-Date -Format yyyyMMdd).jsonl" -Wait -Tail 20
```

After a crawl batch completes on a server: within 10 minutes the storage machine's watcher should pick up the files, pass them through DQ, and load to staging.

---

## Success Criteria

- [ ] `test_pipeline.py` exits 0 — pipeline green end-to-end on local data
- [ ] Task Scheduler shows `STS_PipelineWatcher` and `STS_GoldRebuild` in Ready state
- [ ] Within 10 min of a crawl batch completing: data appears in `hs_raw_import`/`hs_raw_export`
- [ ] DQ-failing files are in quarantine, not in staging (verify via `ingestion_log`)
- [ ] Every event traceable in `D:\datacenter\logs\audit_YYYYMMDD.jsonl`
- [ ] Gold tables rebuild nightly; FK rates in email report
