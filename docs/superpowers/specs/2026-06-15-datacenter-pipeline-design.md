# STS Data Warehouse — Pipeline Design Spec
**Date:** 2026-06-15  
**Author:** Claude Sonnet 4.6 (brainstorming session)  
**Status:** Approved by user

---

## 1. Objective

Build a production-grade data warehouse pipeline for Vietnam customs trade data (import/export, HS codes 52–61) on the `sts-1` storage server. The system must:

- Ingest crawled CSV data into PostgreSQL without touching existing 204GB historical data
- Provide full audit trail per file (validated, rejected with reason, loaded)
- Be maintainable by DA team without DevOps knowledge
- Scale to ongoing crawl from 2 machines (4 accounts) after Phase 2

---

## 2. Architecture

### Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Orchestration | Apache Airflow 2.9 (Docker) | Schedule, retry, alert, lineage |
| Transformation | dbt-core (runs inside Airflow) | SQL models, data tests, docs |
| Data Warehouse | PostgreSQL 13 (Windows service, port 5433) | Storage — existing + new |
| File Transfer Phase 1 | rclone (one-time) | Bulk pull from Google Drive |
| File Transfer Phase 2 | rsync | Ongoing from 2 crawl machines |
| Monitoring | Grafana + Prometheus + postgres_exporter | DB metrics, DA dashboards |

### Key Design Decisions

- **PostgreSQL stays as Windows service** — not moved to Docker. Avoids migrating 204GB. Airflow connects via `host.docker.internal:5433`.
- **Tablespace `sts_new` on D drive** — all new data (2025+) goes to D drive, C drive not touched.
- **Existing data untouched** — `import/export.Fact_2012–2024`, `MasterData`, `csdv` schemas stay on default tablespace.
- **Medallion Architecture** — bronze (raw) → silver (validated) → gold (PostgreSQL Fact tables).

---

## 3. Directory Structure

```
D:\datacenter\
├── bronze\                  ← Raw files from source — IMMUTABLE, never delete
│   ├── 2025\
│   │   ├── hs52\
│   │   ├── hs53\
│   │   └── ...
│   └── 2026\
│       ├── hs52\
│       └── ...
│
├── silver\                  ← Passed all 5 validation checks, ready to load
│   └── (mirrors bronze structure)
│
├── rejected\                ← Failed validation
│   ├── detail_Vietnam_import_hs54_FEB_2026.csv
│   └── detail_Vietnam_import_hs54_FEB_2026.reason.json
│
├── loaded\                  ← Successfully inserted into PostgreSQL
│   └── (mirrors bronze structure)
│
├── pgdata\
│   └── sts_new\             ← PostgreSQL TABLESPACE sts_new
│
├── docker\                  ← Docker volumes
│   ├── airflow\
│   │   ├── dags\            ← mounted from repo 02_ingestion_pipeline/dags/
│   │   ├── logs\
│   │   └── plugins\
│   ├── grafana\
│   └── prometheus\
│
└── logs\
    ├── rclone\
    ├── ingest\
    └── dbt\
```

---

## 4. PostgreSQL Schema Changes

### New Tablespace (D drive)
```sql
CREATE TABLESPACE sts_new LOCATION 'D:\datacenter\pgdata\sts_new';
```

### New Tables (all TABLESPACE sts_new)

```sql
-- Audit trail for every file processed
CREATE TABLE crawling_data.ingestion_log (
    filename        text PRIMARY KEY,
    trade_type      text,        -- 'import' | 'export'
    hs_code         text,        -- '52', '53', ...
    month_year      text,        -- 'JAN_2026'
    source          text,        -- 'gdrive' | 'rsync_may1' | 'rsync_may3'
    row_count       int,
    status          text,        -- 'validated' | 'rejected' | 'loaded'
    reject_reason   jsonb,
    landed_at       timestamptz,
    loaded_at       timestamptz
) TABLESPACE sts_new;

-- New staging table (replaces crawling_data.temp for new data)
-- crawling_data.temp stays untouched for historical reference
CREATE TABLE crawling_data.hs_raw_data (
    id                          bigserial PRIMARY KEY,
    "Buyer"                     text,
    "Supplier"                  text,
    "TotalValue_USD"            double precision,
    "Products"                  text,
    "TradeDate"                 date,
    "UnitPrice_Currency"        double precision,
    "Currency"                  text,
    "SupplierAddress"           text,
    "ExchangeRate"              double precision,
    "BondedWarehouseVNPort"     text,
    "DeclarationNO"             text,
    "CountryOfOrigin"           text,
    "HSCode"                    text,
    "DeparturePort"             text,
    "Quantity"                  double precision,
    "QuantityUnit"              text,
    "Incoterms"                 text,
    "TaxIdentificationNumber"   text,
    "TotalValue_Currency"       double precision,
    "PaymentMethod"             text,
    "BuyerAddress"              text,
    "ImportTax"                 double precision,
    "DestinationPort"           text,
    "GrossWeight_KG"            double precision,
    "DestinationCountry"        text,
    "FOB_USD"                   double precision,
    "CIF_USD"                   double precision,
    "Transportation"            text,
    "LoadingPort"               text,
    "TypeTransaction"           text,
    "CityProvince"              text,
    "Zone"                      text,
    -- FK IDs (populated by resolve_foreign_keys task)
    supplier_id                 bigint,
    buyer_id                    bigint,
    hs2_id                      bigint,
    hs4_id                      bigint,
    hs6_id                      bigint,
    date_id                     bigint,
    currency_id                 bigint,
    country_id                  bigint,
    payment_method_id           bigint,
    transportation_id           bigint,
    -- Pipeline metadata
    source_file                 text,
    ingested_at                 timestamptz DEFAULT now()
) TABLESPACE sts_new;

-- Unique constraint for idempotency
ALTER TABLE crawling_data.hs_raw_data
ADD CONSTRAINT uq_raw_declaration UNIQUE ("DeclarationNO", "HSCode", "TradeDate");

-- Indexes
CREATE INDEX idx_raw_hscode    ON crawling_data.hs_raw_data ("HSCode");
CREATE INDEX idx_raw_tradedate ON crawling_data.hs_raw_data ("TradeDate");
CREATE INDEX idx_raw_source    ON crawling_data.hs_raw_data (source_file);
```

### New Fact Tables for 2025/2026 (TABLESPACE sts_new)
```sql
CREATE TABLE import."Fact_2025" (LIKE import."Fact_2024" INCLUDING ALL) TABLESPACE sts_new;
CREATE TABLE import."Fact_2026" (LIKE import."Fact_2024" INCLUDING ALL) TABLESPACE sts_new;
CREATE TABLE export."Fact_2025" (LIKE export."Fact_2024" INCLUDING ALL) TABLESPACE sts_new;
CREATE TABLE export."Fact_2026" (LIKE export."Fact_2024" INCLUDING ALL) TABLESPACE sts_new;
```

---

## 5. Airflow DAGs

### DAG 1: `sts_bronze_ingest`

**Phase 1 (bootstrap):** One-time rclone pull from Google Drive  
**Phase 2 (ongoing):** Replaced by rsync watcher from crawl machines — crawl code updated to push directly to `D:\datacenter\bronze\`

```
rclone_pull_gdrive
└─ rclone copy "gdrive:STS/" D:\datacenter\bronze\ --checksum --no-overwrite

detect_new_files
└─ scan bronze\ vs ingestion_log → queue new files for DAG 2
```

### DAG 2: `sts_silver_validate` (triggered per file)

5 checks run in parallel per file:

| Check | Logic | On Fail |
|---|---|---|
| `check_columns` | Required cols present: Buyer, Supplier, HSCode, TradeDate, TotalValue_USD | reject |
| `check_rowcount` | row_count > 100 | reject |
| `check_hscode` | All HSCode values start with filename HS prefix | reject |
| `check_duplicate` | filename not in ingestion_log with status='loaded' | skip (idempotent) |
| `check_daterange` | 95%+ of TradeDates fall in file's month/year | warn (not reject) |

```
validate_[all 5 checks in parallel]
└─ route_file:
   PASS → copy to silver\ + ingestion_log status='validated'
   FAIL → copy to rejected\ + write reason.json + ingestion_log status='rejected'
```

### DAG 3: `sts_gold_load` (triggered after DAG 2)

```
load_to_staging
└─ COPY silver\<file> → crawling_data.hs_raw_data
   ON CONFLICT (DeclarationNO, HSCode, TradeDate) DO NOTHING

resolve_foreign_keys
└─ UPDATE hs_raw_data SET
     buyer_id    = (SELECT buyer_id FROM "MasterData".company_im  WHERE lower(buyer)    = lower("Buyer")),
     supplier_id = (SELECT buyer_id FROM "MasterData".company_ex  WHERE lower(buyer)    = lower("Supplier")),
     hs2_id      = (SELECT hs2_id   FROM "MasterData".o_hs2       WHERE hs2_code        = LEFT("HSCode",2)::bigint),
     hs4_id      = (SELECT hs4_id   FROM "MasterData".o_hs4       WHERE hs4_code        = LEFT("HSCode",4)::bigint),
     hs6_id      = (SELECT hs6_id   FROM "MasterData".o_hs6       WHERE hs6_code        = LEFT("HSCode",6)::bigint),
     date_id     = (SELECT date_key FROM "MasterData".o_date       WHERE full_date       = "TradeDate")
   WHERE source_file = :filename AND supplier_id IS NULL

load_fact_table
└─ INSERT INTO import."Fact_YYYY" / export."Fact_YYYY"
   SELECT * FROM crawling_data.hs_raw_data WHERE source_file = :filename
   ON CONFLICT (unique_id) DO NOTHING

update_audit_log
└─ UPDATE ingestion_log SET status='loaded', loaded_at=now(), row_count=:n
   WHERE filename = :filename

move_to_loaded
└─ move file silver\ → loaded\
```

### DAG 4: `sts_dbt_run` (daily 02:00 AM)

```
dbt_test  → run data quality tests (not null, unique, FK relationships)
dbt_run   → refresh csdv.fact_full_import / fact_full_export views
dbt_docs  → generate data catalog (browsable by DA team)
```

---

## 6. Docker Compose Services

**File:** `D:\datacenter\docker\docker-compose.yml`

```yaml
services:
  airflow-webserver:     port 8080   # DA team: monitor DAGs
  airflow-scheduler:     (internal)
  airflow-worker:        (internal)
  airflow-init:          (bootstrap only)
  grafana:               port 3000   # DA team: data dashboards
  prometheus:            port 9090   # metrics collector
  postgres-exporter:     (internal)  # scrapes PG13 metrics
```

PostgreSQL 13 connects via `host.docker.internal:5433` — NOT in Docker.

---

## 7. Grafana Dashboards

| Dashboard | Panels |
|---|---|
| **Ingestion Overview** | Files loaded today/week/total, rows per HS code per month |
| **Data Freshness** | Latest TradeDate per HS code (data mới nhất đến đâu) |
| **Pipeline Health** | DAG success/fail rate, rejected files + reasons, last run per DAG |
| **Database Size** | Fact table size per year, D drive usage trend, row count growth |

---

## 8. Two-Phase Rollout

### Phase 1 — Bootstrap (now)
1. Create D:\datacenter\ structure
2. Create PostgreSQL tablespace sts_new on D drive
3. Create new DB tables (ingestion_log, hs_raw_data, Fact_2025/2026)
4. Run rclone ONE-TIME pull from Google Drive → bronze\
5. Validate all 77 existing CSVs — check data quality
6. Load validated files into PostgreSQL
7. Deploy Airflow + Grafana via Docker Compose
8. Verify DA team can query data

### Phase 2 — Full Automation (after Phase 1 stable)
1. Update crawl code to push directly to `D:\datacenter\bronze\` via rsync
2. DAG 1 becomes rsync watcher (no more Google Drive dependency)
3. Remove rclone from pipeline

---

## 9. Out of Scope

- Forecasting (OLS/ARIMA/NBEATS) — separate project
- Real-time streaming — batch ingestion only
- NER enrichment — Phase 3, after pipeline stable
