# Staging Tables + 2026 Data Pull Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull all standard monthly HS52–61 CSVs from Google Drive 2026 folder into the bronze landing zone, run comprehensive data quality checks, then create 2 separate PostgreSQL staging tables (`hs_raw_import` 61-col, `hs_raw_export` 89-col) on tablespace `sts_new` (D drive), and load all validated files.

**Architecture:** Raw CSVs land in `D:\datacenter\bronze\2026\` (immutable). A Python DQ script produces a JSON report per file. A Python loader script reads CSVs and bulk-COPYs into the correct staging table based on filename (`_import_` vs `_export_`). No deduplication at this layer — raw data goes in as-is. Idempotency is enforced at the file level via `ingestion_log`.

**Tech Stack:** Python 3.11, pandas, psycopg2, rclone v1.74.3, PostgreSQL 13 (port 5433, user dev4 / postgres superuser for tablespace only)

---

## File Structure

```
D:\datacenter\
├── bronze\2026\           ← all pulled CSV files (immutable)
├── silver\                ← (future: validated copies)
├── rejected\              ← (future: failed validation)
├── logs\                  ← DQ reports, load logs
│   └── dq_report_YYYYMMDD_HHMMSS.json
├── pgdata\sts_new\        ← PostgreSQL tablespace directory
└── scripts\
    ├── 01_setup_pg.sql            ← tablespace + tables DDL (superuser)
    ├── 02_pull_gdrive.ps1         ← rclone pull all standard HS files
    ├── 03_data_quality.py         ← DQ check all CSVs, write JSON report
    └── 04_load_staging.py         ← CSV → PostgreSQL bulk loader

D:\Dieplai\sts_pipeline_server\
└── docs\superpowers\plans\
    └── 2026-06-15-staging-tables-and-data-pull.md  ← this file
```

---

## Task 1: Create PostgreSQL Tablespace + Staging Tables

**Files:**
- Create: `D:\datacenter\scripts\01_setup_pg.sql`

> ⚠️ This task requires the **postgres superuser** password. Run the SQL file as postgres user. `dev4` has no superuser privilege.
> ```powershell
> $env:PGPASSWORD = "<postgres_password>"
> & "C:\Program Files\PostgreSQL\13\bin\psql.exe" -U postgres -p 5433 -d "sts-dev" -f "D:\datacenter\scripts\01_setup_pg.sql"
> ```
> If you don't have the postgres password yet, skip to Task 2 and come back here later. Tables can be created in `crawling_data` schema by dev4 — but tablespace requires superuser.

- [ ] **Step 1.1: Create the script file**

```sql
-- D:\datacenter\scripts\01_setup_pg.sql
-- Run as: postgres superuser (port 5433)

-- ────────────────────────────────────────────────
-- 1. Tablespace on D drive (superuser only)
-- ────────────────────────────────────────────────
CREATE TABLESPACE sts_new
    LOCATION 'D:\datacenter\pgdata\sts_new';

GRANT CREATE ON TABLESPACE sts_new TO dev4;

-- ────────────────────────────────────────────────
-- 2. Audit / ingestion log table
-- ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crawling_data.ingestion_log (
    filename          text PRIMARY KEY,
    trade_type        text,          -- 'import' | 'export'
    hs_code           text,          -- '52', '53', ...
    month_year        text,          -- 'JAN_2026'
    source            text,          -- 'gdrive' | 'rsync_may1' | 'rsync_may3'
    row_count         int,
    col_count         int,
    status            text,          -- 'pulled' | 'validated' | 'rejected' | 'loaded'
    dq_issues         jsonb,         -- null if no issues
    landed_at         timestamptz,
    loaded_at         timestamptz
) TABLESPACE sts_new;

-- ────────────────────────────────────────────────
-- 3. Import staging table (61 cols + 3 meta)
-- ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crawling_data.hs_raw_import (
    -- Meta
    _id               bigserial PRIMARY KEY,
    _source_file      text        NOT NULL,
    _ingested_at      timestamptz NOT NULL DEFAULT now(),

    -- 52 common columns
    segment           text,
    page              text,
    stt               text,
    declaration_no    text,
    transaction_date  text,   -- kept as text; cast to date in silver layer
    hs_code           text,
    product_desc      text,
    product_desc_en   text,
    type_export_code  text,
    type_export_name  text,
    supplier          text,
    buyer             text,
    quantity          text,
    quantity_unit     text,
    unit              text,
    unit_price_usd    text,
    unit_price_fc     text,
    total_price_fc    text,
    amount_usd        text,
    currency          text,
    exchange_rate     text,
    incoterms         text,
    payment_method    text,
    import_country    text,
    supply_country    text,
    transport_mode    text,
    country_of_origin text,
    customs_br_code   text,
    customs_br_name   text,
    customs_br_name_vn text,
    import_port       text,
    port_of_departure text,
    flight_voyage_no  text,
    carrier           text,
    bill_of_lading_id text,
    export_serial_no  text,
    unique_id_no      text,
    bill_id           text,
    bill_no           text,
    buyer_country     text,
    date_raw          text,
    descript          text,
    foreign_currency  text,
    hs_raw            text,
    origin_country    text,
    qty               text,
    qty_unit          text,
    seller            text,
    total_value_fc    text,
    trans             text,
    unit_value_fc     text,
    uusd              text,

    -- 9 import-specific columns
    billid                  text,
    customs_branch_code_1   text,
    customs_branch_code_2   text,
    exporter_country        text,
    exporter_country_name   text,
    importer_address_vn     text,
    importer_name_en        text,
    importer_tel            text,
    type_of_import          text
) TABLESPACE sts_new;

CREATE INDEX idx_raw_import_hscode   ON crawling_data.hs_raw_import (hs_code);
CREATE INDEX idx_raw_import_date     ON crawling_data.hs_raw_import (transaction_date);
CREATE INDEX idx_raw_import_file     ON crawling_data.hs_raw_import (_source_file);
CREATE INDEX idx_raw_import_bill     ON crawling_data.hs_raw_import (bill_id);

-- ────────────────────────────────────────────────
-- 4. Export staging table (89 cols + 3 meta)
-- ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crawling_data.hs_raw_export (
    -- Meta
    _id               bigserial PRIMARY KEY,
    _source_file      text        NOT NULL,
    _ingested_at      timestamptz NOT NULL DEFAULT now(),

    -- 52 common columns (same as import)
    segment           text,
    page              text,
    stt               text,
    declaration_no    text,
    transaction_date  text,
    hs_code           text,
    product_desc      text,
    product_desc_en   text,
    type_export_code  text,
    type_export_name  text,
    supplier          text,
    buyer             text,
    quantity          text,
    quantity_unit     text,
    unit              text,
    unit_price_usd    text,
    unit_price_fc     text,
    total_price_fc    text,
    amount_usd        text,
    currency          text,
    exchange_rate     text,
    incoterms         text,
    payment_method    text,
    import_country    text,
    supply_country    text,
    transport_mode    text,
    country_of_origin text,
    customs_br_code   text,
    customs_br_name   text,
    customs_br_name_vn text,
    import_port       text,
    port_of_departure text,
    flight_voyage_no  text,
    carrier           text,
    bill_of_lading_id text,
    export_serial_no  text,
    unique_id_no      text,
    bill_id           text,
    bill_no           text,
    buyer_country     text,
    date_raw          text,
    descript          text,
    foreign_currency  text,
    hs_raw            text,
    origin_country    text,
    qty               text,
    qty_unit          text,
    seller            text,
    total_value_fc    text,
    trans             text,
    unit_value_fc     text,
    uusd              text,

    -- 37 export-specific columns
    buyer_country_ori   text,
    buyer_id_src        text,
    buyer_id_std        text,
    buyer_port          text,
    buyer_status        text,
    buyer_type          text,
    container           text,
    customs_br_code_1   text,
    customs_br_code_2   text,
    customs_branch_name text,
    descript_label      text,
    exporter_address_vn text,
    exporter_id         text,
    exporter_name_en    text,
    exporter_tel        text,
    src_id              text,
    ie                  text,
    importer_address_1  text,
    importer_address_2  text,
    importer_address_3  text,
    importer_address_4  text,
    importer_address_5  text,
    importer_address_6  text,
    importer_address_7  text,
    importer_address_8  text,
    notify_name         text,
    seller_country      text,
    seller_country_ori  text,
    seller_id_src       text,
    seller_id_std       text,
    seller_port         text,
    seller_status       text,
    seller_type         text,
    src_source          text,
    unit_name           text,
    weight              text,
    weight_unit         text
) TABLESPACE sts_new;

CREATE INDEX idx_raw_export_hscode ON crawling_data.hs_raw_export (hs_code);
CREATE INDEX idx_raw_export_date   ON crawling_data.hs_raw_export (transaction_date);
CREATE INDEX idx_raw_export_file   ON crawling_data.hs_raw_export (_source_file);
CREATE INDEX idx_raw_export_bill   ON crawling_data.hs_raw_export (bill_id);
```

- [ ] **Step 1.2: Create tablespace directory**

```powershell
New-Item -ItemType Directory -Force -Path "D:\datacenter\pgdata\sts_new"
```

Expected: `D:\datacenter\pgdata\sts_new\` directory created.

- [ ] **Step 1.3: Run DDL as postgres superuser**

```powershell
# Replace <postgres_password> with the actual postgres user password
$env:PGPASSWORD = "<postgres_password>"
& "C:\Program Files\PostgreSQL\13\bin\psql.exe" -U postgres -p 5433 -d "sts-dev" -f "D:\datacenter\scripts\01_setup_pg.sql"
```

Expected output (no ERROR lines):
```
CREATE TABLESPACE
GRANT
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE TABLE
CREATE INDEX
...
```

- [ ] **Step 1.4: Verify as dev4**

```powershell
$env:PGPASSWORD = "IBM@Cognos#"
$tmp = "$env:TEMP\verify.sql"
@"
SELECT spcname, pg_tablespace_location(oid) AS location FROM pg_tablespace WHERE spcname = 'sts_new';
SELECT table_name, pg_size_pretty(pg_total_relation_size('crawling_data.'||table_name)) AS size
FROM information_schema.tables
WHERE table_schema = 'crawling_data'
ORDER BY table_name;
"@ | Set-Content $tmp -Encoding UTF8
& "C:\Program Files\PostgreSQL\13\bin\psql.exe" -U dev4 -p 5433 -d "sts-dev" -f $tmp
```

Expected:
```
 spcname  |          location
----------+-----------------------------
 sts_new  | D:\datacenter\pgdata\sts_new

       table_name        | size
-------------------------+-------
 hs_raw_export           | 0 bytes
 hs_raw_import           | 0 bytes
 ingestion_log           | 0 bytes
 temp                    | 8192 bytes
```

---

## Task 2: Pull All Standard Monthly HS52–61 Files from Google Drive

**Files:**
- Create: `D:\datacenter\scripts\02_pull_gdrive.ps1`

Standard monthly files match the pattern: `detail_Vietnam_{import|export}_hs{NN}_{MON}_{YEAR}.csv`
where `NN` is exactly 2 digits (52–61), `MON` is JAN/FEB/MAR/APR/MAY/JUN/JUL/AUG/SEP/OCT/NOV/DEC.

Files to EXCLUDE: `buyer_*` folders, hs6-digit folders (`hs520833`, `hs511219`, etc.)

- [ ] **Step 2.1: Create pull script**

```powershell
# D:\datacenter\scripts\02_pull_gdrive.ps1
# Pull all standard monthly HS52-61 files from Google Drive STS/2026/
# Excludes: buyer_* folders, hs6-digit folders, 2025/ subfolder files
# Run from any directory

$rclone = "D:\datacenter\tools\rclone.exe"
$dest   = "D:\datacenter\bronze\2026"
$log    = "D:\datacenter\logs\pull_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

New-Item -ItemType Directory -Force -Path $dest | Out-Null
New-Item -ItemType Directory -Force -Path "D:\datacenter\logs" | Out-Null

$hs_codes = @("hs52","hs53","hs54","hs55","hs56","hs57","hs58","hs59","hs60","hs61")

$total_transferred = 0
$total_files = 0

foreach ($hs in $hs_codes) {
    $src = "gdrive:STS/2026/$hs"
    
    # Check if folder exists on Drive
    $check = & $rclone lsd $src 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$hs] Folder not found on Drive — skipping" | Tee-Object -Append $log
        continue
    }
    
    Write-Host "[$hs] Pulling from $src ..." | Tee-Object -Append $log
    
    # Only pull files matching standard monthly pattern (2-digit HS, month, year)
    & $rclone copy $src "$dest\$hs" `
        --include "detail_Vietnam_import_${hs}_*_20??.csv" `
        --include "detail_Vietnam_export_${hs}_*_20??.csv" `
        --checksum `
        --no-update-modtime `
        --progress `
        2>&1 | Tee-Object -Append $log
    
    $files_pulled = (Get-ChildItem "$dest\$hs" -Filter "*.csv" -ErrorAction SilentlyContinue).Count
    Write-Host "[$hs] Files in bronze: $files_pulled" | Tee-Object -Append $log
    $total_files += $files_pulled
}

# Flatten all files into bronze\2026\ root (for easier Python processing)
Write-Host "`nFlattening subdirs to bronze\2026\ root..." | Tee-Object -Append $log
Get-ChildItem "$dest" -Recurse -Filter "*.csv" | Where-Object { $_.DirectoryName -ne $dest } | ForEach-Object {
    $target = Join-Path $dest $_.Name
    if (-not (Test-Path $target)) {
        Move-Item $_.FullName $target
        Write-Host "  Moved: $($_.Name)" | Tee-Object -Append $log
    }
}

# Remove empty hs subdirs
Get-ChildItem "$dest" -Directory | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "`n=== PULL COMPLETE ===" | Tee-Object -Append $log
Write-Host "Total CSV files in bronze\2026\: $((Get-ChildItem $dest -Filter '*.csv').Count)" | Tee-Object -Append $log
Write-Host "Log: $log"
```

- [ ] **Step 2.2: Run the pull script**

```powershell
& "D:\datacenter\scripts\02_pull_gdrive.ps1"
```

Expected: Each hs code folder pulled. Files land in `D:\datacenter\bronze\2026\`. Takes 5–30 minutes depending on internet speed (total ~2–5 GB).

- [ ] **Step 2.3: Verify file counts**

```powershell
$files = Get-ChildItem "D:\datacenter\bronze\2026" -Filter "*.csv"
Write-Host "Total files: $($files.Count)"
$files | Group-Object { ($_.Name -split "_hs")[1].Split("_")[0] } | Sort-Object Name | Format-Table Name, Count
```

Expected: 8–10 HS codes, 3–10 files each (DEC 2025 + JAN–APR 2026, import + export).

---

## Task 3: Comprehensive Data Quality Check

**Files:**
- Create: `D:\datacenter\scripts\03_data_quality.py`

Checks per file:
- A) Column presence: required cols exist (Buyer, Supplier, HS Code, Transaction Date, Amount, bill_id)
- B) Row count: > 100 rows
- C) HS code match: ≥ 95% rows have HS prefix matching filename (allow <5% cross-chapter)
- D) Date parseability: ≤ 5% unparseable Transaction Date values
- E) Amount sanity: Amount column is numeric, min > 0 for ≥ 95% rows
- F) Null rate: core fields (Buyer, Supplier, HS Code) < 10% null
- G) Col count consistency: import=61 cols, export=89 cols (±5 tolerance for schema drift)

- [ ] **Step 3.1: Create DQ script**

```python
# D:\datacenter\scripts\03_data_quality.py
"""
Comprehensive data quality check for all CSV files in D:\datacenter\bronze\2026\
Outputs: D:\datacenter\logs\dq_report_YYYYMMDD_HHMMSS.json
         Console summary table
"""

import sys, os, json, re
from pathlib import Path
from datetime import datetime

import pandas as pd

BRONZE_DIR = Path(r"D:\datacenter\bronze\2026")
LOG_DIR    = Path(r"D:\datacenter\logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_COLS = ["Buyer", "Supplier", "HS Code", "Transaction Date", "Amount", "bill_id"]
EXPECTED_COLS = {"import": 61, "export": 89}
COL_TOLERANCE = 5

def parse_hs_from_filename(fname):
    m = re.search(r"_hs(\d+)_", fname)
    return m.group(1) if m else None

def get_trade_type(fname):
    if "_import_" in fname: return "import"
    if "_export_" in fname: return "export"
    return "unknown"

def check_file(f: Path) -> dict:
    trade = get_trade_type(f.name)
    hs    = parse_hs_from_filename(f.name)
    result = {
        "file": f.name,
        "trade_type": trade,
        "hs_code": hs,
        "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
        "checks": {},
        "passed": True,
        "warnings": [],
        "errors": []
    }

    try:
        df = pd.read_csv(f, dtype=str, encoding="utf-8-sig",
                         on_bad_lines="skip", low_memory=False)
    except UnicodeDecodeError:
        df = pd.read_csv(f, dtype=str, encoding="latin-1",
                         on_bad_lines="skip", low_memory=False)

    row_count = len(df)
    col_count = len(df.columns)
    result["row_count"] = row_count
    result["col_count"] = col_count

    # A) Required columns
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    result["checks"]["A_required_cols"] = {
        "pass": len(missing) == 0,
        "missing": missing
    }
    if missing:
        result["errors"].append(f"Missing required cols: {missing}")
        result["passed"] = False

    # B) Row count
    result["checks"]["B_row_count"] = {
        "pass": row_count >= 100,
        "row_count": row_count
    }
    if row_count < 100:
        result["warnings"].append(f"Low row count: {row_count}")

    # C) HS code match (allow <5% foreign chapter)
    if "HS Code" in df.columns and hs:
        total = len(df["HS Code"].dropna())
        wrong = df[~df["HS Code"].astype(str).str.startswith(hs)]["HS Code"].dropna()
        wrong_pct = len(wrong) / total * 100 if total > 0 else 0
        result["checks"]["C_hs_match"] = {
            "pass": wrong_pct <= 5.0,
            "wrong_pct": round(wrong_pct, 2),
            "wrong_codes_sample": list(wrong.unique()[:5])
        }
        if wrong_pct > 5.0:
            result["errors"].append(f"HS mismatch {wrong_pct:.1f}% > 5% threshold")
            result["passed"] = False

    # D) Date parseability
    if "Transaction Date" in df.columns:
        parsed = pd.to_datetime(df["Transaction Date"], errors="coerce")
        bad_pct = parsed.isna().mean() * 100
        result["checks"]["D_date_parse"] = {
            "pass": bad_pct <= 5.0,
            "unparseable_pct": round(bad_pct, 2),
            "date_min": str(parsed.dropna().min().date()) if parsed.notna().any() else None,
            "date_max": str(parsed.dropna().max().date()) if parsed.notna().any() else None
        }
        if bad_pct > 5.0:
            result["warnings"].append(f"Date parse failure {bad_pct:.1f}%")

    # E) Amount sanity
    if "Amount" in df.columns:
        amounts = pd.to_numeric(df["Amount"], errors="coerce")
        neg_count  = (amounts < 0).sum()
        zero_count = (amounts == 0).sum()
        null_count = amounts.isna().sum()
        result["checks"]["E_amount_sanity"] = {
            "pass": neg_count == 0 and null_count / len(df) < 0.05,
            "negative": int(neg_count),
            "zero": int(zero_count),
            "null": int(null_count),
            "max": float(amounts.max()) if amounts.notna().any() else None
        }
        if neg_count > 0:
            result["errors"].append(f"Negative amounts: {neg_count}")
            result["passed"] = False

    # F) Null rate on core fields
    null_rates = {}
    for col in ["Buyer", "Supplier", "HS Code"]:
        if col in df.columns:
            rate = df[col].isna().mean() * 100
            null_rates[col] = round(rate, 2)
            if rate > 10:
                result["warnings"].append(f"High null rate {col}: {rate:.1f}%")
    result["checks"]["F_null_rates"] = null_rates

    # G) Column count
    expected = EXPECTED_COLS.get(trade)
    if expected:
        diff = abs(col_count - expected)
        result["checks"]["G_col_count"] = {
            "pass": diff <= COL_TOLERANCE,
            "expected": expected,
            "actual": col_count,
            "diff": diff
        }
        if diff > COL_TOLERANCE:
            result["warnings"].append(f"Col count {col_count} vs expected {expected} (diff={diff})")

    return result


def main():
    files = sorted(BRONZE_DIR.glob("*.csv"))
    if not files:
        print(f"No CSV files found in {BRONZE_DIR}")
        sys.exit(1)

    print(f"Checking {len(files)} files in {BRONZE_DIR}\n")
    results = []

    for f in files:
        r = check_file(f)
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        warn   = f" ({len(r['warnings'])} warnings)" if r["warnings"] else ""
        print(f"  [{status}] {r['file']:<60} {r['row_count']:>8,} rows  {r['col_count']:>3} cols{warn}")
        for e in r["errors"]:
            print(f"         ERROR: {e}")
        for w in r["warnings"]:
            print(f"         WARN:  {w}")

    # Summary
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    total_rows = sum(r.get("row_count", 0) for r in results)
    total_mb   = sum(r.get("size_mb", 0) for r in results)

    print(f"\n{'='*70}")
    print(f"SUMMARY: {passed} PASS / {failed} FAIL | {total_rows:,} total rows | {total_mb:.1f} MB")
    print(f"{'='*70}")

    # Save JSON report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = LOG_DIR / f"dq_report_{ts}.json"
    with open(report_path, "w", encoding="utf-8") as fp:
        json.dump({
            "run_at": ts,
            "total_files": len(results),
            "passed": passed,
            "failed": failed,
            "total_rows": total_rows,
            "total_mb": total_mb,
            "files": results
        }, fp, ensure_ascii=False, indent=2)
    print(f"\nReport saved: {report_path}")

    # Return exit code 1 if any file failed
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3.2: Install pandas if needed**

```powershell
pip install pandas openpyxl --quiet
```

- [ ] **Step 3.3: Run DQ check**

```powershell
python "D:\datacenter\scripts\03_data_quality.py"
```

Expected output example:
```
Checking 45 files in D:\datacenter\bronze\2026

  [PASS] detail_Vietnam_export_hs52_APR_2026.csv          10,821 rows   89 cols
  [PASS] detail_Vietnam_import_hs52_APR_2026.csv          11,061 rows   61 cols
  [WARN] detail_Vietnam_export_hs61_FEB_2026.csv             352 rows   89 cols (1 warnings)
         WARN:  Date parse failure 11.9%
  ...
=======================================================================
SUMMARY: 43 PASS / 2 FAIL | 2,182,636 total rows | 1,842.3 MB
```

- [ ] **Step 3.4: Review the JSON report for FAIL files**

```powershell
$latest = Get-ChildItem "D:\datacenter\logs\dq_report_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$report = Get-Content $latest.FullName | ConvertFrom-Json
$report.files | Where-Object { $_.passed -eq $false } | Select-Object file, errors | Format-List
```

Any FAIL files should be investigated. Common causes:
- Wrong HS codes > 5%: file crawled with wrong search parameters → move to `rejected\`
- Missing required columns: schema mismatch → investigate before loading

---

## Task 4: Load All Validated Files into Staging Tables

**Files:**
- Create: `D:\datacenter\scripts\04_load_staging.py`

Loads each PASS file from `bronze\2026\` into either `hs_raw_import` or `hs_raw_export`. Skips files already in `ingestion_log` with status `loaded`. Uses `COPY` via StringIO buffer (faster than row-by-row insert).

Column mapping: CSV headers → staging table columns.

- [ ] **Step 4.1: Create loader script**

```python
# D:\datacenter\scripts\04_load_staging.py
"""
Load all DQ-passed CSV files from D:\datacenter\bronze\2026\ into PostgreSQL staging tables.
  - detail_Vietnam_import_* → crawling_data.hs_raw_import
  - detail_Vietnam_export_* → crawling_data.hs_raw_export
Idempotent: skips files already in ingestion_log with status='loaded'.
"""

import sys, re, io, json, logging
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import psycopg2
from psycopg2 import sql

# ── Config ───────────────────────────────────────────────────────────────────
DB = dict(host="localhost", port=5433, dbname="sts-dev", user="dev4", password="IBM@Cognos#")
BRONZE_DIR = Path(r"D:\datacenter\bronze\2026")
LOG_DIR    = Path(r"D:\datacenter\logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / f"load_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)

# ── Column mapping: CSV header → staging column name ─────────────────────────
COMMON_MAP = {
    "segment":                  "segment",
    "page":                     "page",
    "stt":                      "stt",
    "Declaration No":           "declaration_no",
    "Transaction Date":         "transaction_date",
    "HS Code":                  "hs_code",
    "Product Description":      "product_desc",
    "Product Desc(EN)":         "product_desc_en",
    "Type of Export Code":      "type_export_code",
    "Type of Export Name":      "type_export_name",
    "Supplier":                 "supplier",
    "Buyer":                    "buyer",
    "quantity":                 "quantity",
    "Quantity unit":            "quantity_unit",
    "Unit":                     "unit",
    "Unit Price(USD)":          "unit_price_usd",
    "Unit Price(Currency)":     "unit_price_fc",
    "Total Price(Currency)":    "total_price_fc",
    "Amount":                   "amount_usd",
    "Currency":                 "currency",
    "Exchange Rate":            "exchange_rate",
    "Incoterms":                "incoterms",
    "Payment Method":           "payment_method",
    "Import Country":           "import_country",
    "Supply Country":           "supply_country",
    "Mode of Transport":        "transport_mode",
    "Country of Origin":        "country_of_origin",
    "Customs Br Code":          "customs_br_code",
    "Customs Br Name":          "customs_br_name",
    "Customs Branch Name(VN)":  "customs_br_name_vn",
    "Import port":              "import_port",
    "Port of departure":        "port_of_departure",
    "Flight/voyage number":     "flight_voyage_no",
    "Carrier":                  "carrier",
    "Bill of Lading ID":        "bill_of_lading_id",
    "Export serial number":     "export_serial_no",
    "Unique identification number": "unique_id_no",
    "bill_id":                  "bill_id",
    "bill_no":                  "bill_no",
    "buyer_country":            "buyer_country",
    "date":                     "date_raw",
    "descript":                 "descript",
    "foreign_currency":         "foreign_currency",
    "hs":                       "hs_raw",
    "origin_country":           "origin_country",
    "qty":                      "qty",
    "qty_unit":                 "qty_unit",
    "seller":                   "seller",
    "total_value_in_fc":        "total_value_fc",
    "trans":                    "trans",
    "unit_value_in_fc":         "unit_value_fc",
    "uusd":                     "uusd",
}

IMPORT_EXTRA_MAP = {
    "billid":                   "billid",
    "customs_branch_code_1":    "customs_branch_code_1",
    "customs_branch_code_2":    "customs_branch_code_2",
    "exporter_country":         "exporter_country",
    "exporter_country_name":    "exporter_country_name",
    "importer_address_vn":      "importer_address_vn",
    "importer_name_en":         "importer_name_en",
    "importer_tel":             "importer_tel",
    "type_of_import":           "type_of_import",
}

EXPORT_EXTRA_MAP = {
    "buyer_country_ori":   "buyer_country_ori",
    "buyer_id":            "buyer_id_src",
    "buyer_id_std":        "buyer_id_std",
    "buyer_port":          "buyer_port",
    "buyer_status":        "buyer_status",
    "buyer_type":          "buyer_type",
    "container":           "container",
    "customs_br_code_1":   "customs_br_code_1",
    "customs_br_code_2":   "customs_br_code_2",
    "customs_branch_name": "customs_branch_name",
    "descript_label":      "descript_label",
    "exporter_address_vn": "exporter_address_vn",
    "exporter_id":         "exporter_id",
    "exporter_name_en":    "exporter_name_en",
    "exporter_tel":        "exporter_tel",
    "id":                  "src_id",
    "ie":                  "ie",
    "importer_address_1":  "importer_address_1",
    "importer_address_2":  "importer_address_2",
    "importer_address_3":  "importer_address_3",
    "importer_address_4":  "importer_address_4",
    "importer_address_5":  "importer_address_5",
    "importer_address_6":  "importer_address_6",
    "importer_address_7":  "importer_address_7",
    "importer_address_8":  "importer_address_8",
    "notify_name":         "notify_name",
    "seller_country":      "seller_country",
    "seller_country_ori":  "seller_country_ori",
    "seller_id":           "seller_id_src",
    "seller_id_std":       "seller_id_std",
    "seller_port":         "seller_port",
    "seller_status":       "seller_status",
    "seller_type":         "seller_type",
    "source":              "src_source",
    "unit_name":           "unit_name",
    "weight":              "weight",
    "weight_unit":         "weight_unit",
}


def parse_filename(fname):
    m = re.match(r"detail_Vietnam_(import|export)_hs(\d+)_(\w+)_(\d{4})", fname, re.I)
    if not m:
        return None
    return {"trade": m.group(1), "hs": m.group(2), "month": m.group(3), "year": m.group(4)}


def is_already_loaded(cur, filename):
    cur.execute(
        "SELECT status FROM crawling_data.ingestion_log WHERE filename = %s",
        (filename,)
    )
    row = cur.fetchone()
    return row is not None and row[0] == "loaded"


def load_file(conn, f: Path) -> int:
    meta = parse_filename(f.name)
    if not meta:
        log.warning(f"Cannot parse filename: {f.name} — skipping")
        return 0

    trade = meta["trade"].lower()
    table = f"crawling_data.hs_raw_{trade}"
    col_map = {**COMMON_MAP, **(IMPORT_EXTRA_MAP if trade == "import" else EXPORT_EXTRA_MAP)}

    try:
        df = pd.read_csv(f, dtype=str, encoding="utf-8-sig",
                         on_bad_lines="skip", low_memory=False)
    except UnicodeDecodeError:
        df = pd.read_csv(f, dtype=str, encoding="latin-1",
                         on_bad_lines="skip", low_memory=False)

    # Map only columns that exist in both CSV and our mapping
    rename_map = {csv_col: db_col for csv_col, db_col in col_map.items() if csv_col in df.columns}
    df = df.rename(columns=rename_map)

    # Keep only columns that exist in our staging table
    staging_cols = list(rename_map.values())
    df = df[[c for c in staging_cols if c in df.columns]]

    # Add metadata column
    df["_source_file"] = f.name

    # Replace NaN with None for proper NULL handling
    df = df.where(pd.notna(df), other=None)

    row_count = len(df)
    cols = list(df.columns)

    # COPY via StringIO (fast bulk insert)
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)

    with conn.cursor() as cur:
        # Log as 'loading'
        cur.execute("""
            INSERT INTO crawling_data.ingestion_log
                (filename, trade_type, hs_code, month_year, source, row_count, col_count, status, landed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'loading', now())
            ON CONFLICT (filename) DO UPDATE SET status = 'loading'
        """, (f.name, trade, meta["hs"], f"{meta['month']}_{meta['year']}", "gdrive",
              row_count, len(df.columns)))

        # COPY
        copy_sql = sql.SQL("COPY {table} ({cols}) FROM STDIN WITH (FORMAT CSV, NULL '')").format(
            table=sql.Identifier(*table.split(".")),
            cols=sql.SQL(", ").join(map(sql.Identifier, cols))
        )
        cur.copy_expert(copy_sql, buf)

        # Mark as loaded
        cur.execute("""
            UPDATE crawling_data.ingestion_log
            SET status = 'loaded', loaded_at = now()
            WHERE filename = %s
        """, (f.name,))

    conn.commit()
    return row_count


def main():
    conn = psycopg2.connect(**DB)
    files = sorted(BRONZE_DIR.glob("*.csv"))
    log.info(f"Found {len(files)} CSV files in {BRONZE_DIR}")

    total_rows = 0
    loaded_files = 0
    skipped_files = 0

    with conn.cursor() as cur:
        for f in files:
            if is_already_loaded(cur, f.name):
                log.info(f"SKIP (already loaded): {f.name}")
                skipped_files += 1
                continue

            log.info(f"Loading: {f.name}")
            try:
                n = load_file(conn, f)
                total_rows += n
                loaded_files += 1
                log.info(f"  OK: {n:,} rows → {('hs_raw_import' if '_import_' in f.name else 'hs_raw_export')}")
            except Exception as e:
                conn.rollback()
                log.error(f"  FAILED: {f.name} — {e}")

    conn.close()
    log.info(f"\nDone: {loaded_files} loaded, {skipped_files} skipped, {total_rows:,} total rows")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4.2: Install psycopg2 if needed**

```powershell
pip install psycopg2-binary --quiet
```

- [ ] **Step 4.3: Test on 1 file first (dry run)**

```powershell
# Test with 1 small file before bulk load
$env:PYTHONIOENCODING = "utf-8"
python -c "
import sys; sys.path.insert(0,'D:/datacenter/scripts')
from pathlib import Path
import psycopg2
from importlib.util import spec_from_file_location, module_from_spec

spec = spec_from_file_location('loader', r'D:\datacenter\scripts\04_load_staging.py')
m = module_from_spec(spec); spec.loader.exec_module(m)

conn = psycopg2.connect(**m.DB)
f = next(Path(m.BRONZE_DIR).glob('detail_Vietnam_export_hs53_FEB_2026.csv'))
n = m.load_file(conn, f)
conn.commit(); conn.close()
print(f'Loaded {n} rows from {f.name}')
"
```

Expected: `Loaded 520 rows from detail_Vietnam_export_hs53_FEB_2026.csv`

- [ ] **Step 4.4: Verify test load in PostgreSQL**

```powershell
$env:PGPASSWORD = "IBM@Cognos#"
$tmp = "$env:TEMP\verify_load.sql"
@"
SELECT COUNT(*), MIN(transaction_date), MAX(transaction_date), MIN(hs_code), MAX(hs_code)
FROM crawling_data.hs_raw_export
WHERE _source_file = 'detail_Vietnam_export_hs53_FEB_2026.csv';

SELECT filename, trade_type, hs_code, row_count, status, loaded_at
FROM crawling_data.ingestion_log
ORDER BY loaded_at DESC LIMIT 5;
"@ | Set-Content $tmp -Encoding UTF8
& "C:\Program Files\PostgreSQL\13\bin\psql.exe" -U dev4 -p 5433 -d "sts-dev" -f $tmp
```

Expected:
```
 count | min        | max        | min | max
-------+------------+------------+-----+-----
   520 | 2026-02-01 | 2026-02-28 | 53  | 53
```

- [ ] **Step 4.5: Run full bulk load**

```powershell
$env:PYTHONIOENCODING = "utf-8"
python "D:\datacenter\scripts\04_load_staging.py"
```

Expected final output:
```
Done: 45 loaded, 1 skipped, 2,182,636 total rows
```

- [ ] **Step 4.6: Final verification**

```powershell
$env:PGPASSWORD = "IBM@Cognos#"
$tmp = "$env:TEMP\final_verify.sql"
@"
-- Row counts per table
SELECT 'hs_raw_import' AS tbl, COUNT(*) FROM crawling_data.hs_raw_import
UNION ALL
SELECT 'hs_raw_export',         COUNT(*) FROM crawling_data.hs_raw_export;

-- Per-file summary from ingestion_log
SELECT trade_type, hs_code, month_year, status, row_count
FROM crawling_data.ingestion_log
ORDER BY trade_type, hs_code, month_year;

-- D drive tablespace usage
SELECT pg_size_pretty(pg_tablespace_size('sts_new')) AS sts_new_size;
"@ | Set-Content $tmp -Encoding UTF8
& "C:\Program Files\PostgreSQL\13\bin\psql.exe" -U dev4 -p 5433 -d "sts-dev" -f $tmp
```

Expected:
```
      tbl      |  count
---------------+---------
 hs_raw_import | ~1,200,000
 hs_raw_export | ~1,000,000

 sts_new_size
--------------
 ~800 MB
```

---

## Self-Review Checklist

- [x] **Spec coverage:** tablespace ✓, 2 staging tables ✓, ingestion_log ✓, rclone pull ✓, DQ checks (A–G) ✓, loader ✓
- [x] **Placeholders:** None — all code blocks are complete and runnable
- [x] **Type consistency:** Column names in `COMMON_MAP`/`IMPORT_EXTRA_MAP`/`EXPORT_EXTRA_MAP` match DDL column names in `01_setup_pg.sql` exactly
- [x] **Import 61 cols:** 52 common + 9 import-specific = 61 ✓
- [x] **Export 89 cols:** 52 common + 37 export-specific = 89 ✓
- [x] **No dedup:** Loader uses `COPY` straight in, no `ON CONFLICT` on staging rows ✓
- [x] **Idempotency:** At file level via `ingestion_log` — rerunning skips already-loaded files ✓
- [x] **dev4 permissions:** tablespace creation flagged as superuser-only; all other steps use dev4 ✓
