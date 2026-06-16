# STS Pipeline Server — Context Document
> Viết cho Claude instance trên sts-1. Đọc file này TRƯỚC KHI làm bất cứ việc gì.
> Author: Claude Sonnet 4.6 | Date: 2026-06-15

---

## 1. Mục tiêu hệ thống

Xây dựng **automation pipeline hoàn chỉnh** trên máy server sts-1:

```
[Máy 1 / Máy 3]          [sts-1 (100.121.146.104)]        [PostgreSQL sts-dev]
 4 crawl accounts   SSH   /data/raw/acc{1-4}/*.csv   →    hs_raw_data (staging)
 pro.52wmb.com  ─────────→  pipeline_loader.py       →    import.Fact_YYYY
 output/*.csv         rsync  ner_enricher.py          →    export.Fact_YYYY
                             watch_and_ingest.sh              ↓
                              └── cron every 2h         Google Drive sync
```

**Không làm:** Forecasting (OLS/ARIMA/NBEATS). Chỉ tập trung data pipeline.

---

## 2. Infrastructure

### Machines
| Tên | IP (Tailscale) | Role | Credentials |
|---|---|---|---|
| **sts-1** | `100.121.146.104` | Server chính (bạn đang ở đây) | Win login: `20232023` |
| **Máy 1** | `100.76.219.16` | Crawl ACC1+ACC2 (Import) | SSH: `pc@IP` (key auth, no password) |
| **Máy 3** | `100.76.65.2` | Crawl ACC3+ACC4 (Export) | SSH: `pc@IP` (key auth, no password) |

### sts-1 Software (pre-installed)
- Python 3.x ✅
- Docker ✅
- Claude Code ✅
- **Không có admin** (không thể cài thêm system packages qua apt/chocolatey/winget)

### PostgreSQL
- Database: `sts-dev` (204 GB, dữ liệu 2012–2024)
- Chạy trong Docker trên sts-1 HOẶC là remote DB (cần verify khi setup)
- Staging table: `hs_raw_data` (hoặc `crawling_data.temp` — xem phần 5)
- Fact tables: `import.Fact_YYYY` / `export.Fact_YYYY`

### SSH Keys
- Từ sts-1 vào Máy 1/3: dùng key-based auth (user `pc`), không cần password
- Nếu SSH chưa setup: file key có thể ở `/data/ssh/` hoặc cần generate mới

---

## 3. Crawl Accounts

| Account | Email | Machine | Type | Current Batch |
|---|---|---|---|---|
| ACC1 | `vtic.stsgroup@gmail.com` | Máy 1 | Import | hs54,60,52,53 (ETA ~17/06) |
| ACC2 | `no.vo@stsgroup.org.vn` | Máy 1 | Import | hs55,56,57,58 (ETA ~14/06) |
| ACC3 | `kay.nguyen@stsgroup.org.vn` | Máy 3 | Export | hs52,54,53,55 (ETA ~15/06) |
| ACC4 | `nguyenkhanhtailscale@gmail.com` | Máy 3 | Export | hs57,58,60,61 (ETA ~30/06) |

**Passwords cho 52wmb.com:**
- ACC1: `Vtic@2024!`
- ACC2: (xem `01_crawl_tool/configs/_local_acc2.py`)
- ACC3: `khanh009500`
- ACC4: (xem `01_crawl_tool/configs/_local_acc4.py`)

**Output path trên Windows machines:**
```
C:\Crawl\acc{N}\crawl_w52_sts\output\detail_Vietnam_{import|export}_hs{NN}_{MON}_{YEAR}.csv
```

### Crawl Status (as of 15/06/2026)
- **Drive có 77 files CSV, 2,182,636 rows** tổng cộng
- HS codes đang crawl: 52, 53, 54, 55, 56, 57, 58, 60, 61
- Thời gian: DEC 2025 – APR 2026 (MAY 2026 chưa có data trên website)

### ⚠️ File sai đã biết
- `detail_Vietnam_import_hs54_FEB_2026.csv` trên ACC1 → **sai data** (71 cols, HS codes khác 1902/2209/3004). Chưa upload lên Drive. Cần crawl lại.

---

## 4. Data Schema

### CSV Headers (Import — 61 cols)
Raw CSV có header từ `src/parsing/field_mapping.py`:
```python
FIELD_MAPPING = {
    'date':                    'Transaction Date',
    'bill_no':                 'Declaration No',
    'hs':                      'HS Code',
    'descript':                'Product Description',
    'product_desc_en':         'Product Desc(EN)',
    'seller':                  'Supplier',
    'buyer':                   'Buyer',
    'qty':                     'quantity',
    'qty_unit':                'Quantity unit',
    'uusd':                    'Unit Price(USD)',
    'unit_value_in_fc':        'Unit Price(Currency)',
    'total_value_in_fc':       'Total Price(Currency)',
    'amount':                  'Amount',
    'exchange_rate':           'Exchange Rate',
    'incoterms':               'Incoterms',
    'payment_method':          'Payment Method',
    'buyer_country':           'Import Country',
    'trans':                   'Mode of Transport',
    'origin_country':          'Country of Origin',
    'customs_br_code_1':       'Customs Br Code',
    'customs_br_code_2':       'Customs Br Name',
    'bill_id':                 'Bill of Lading ID',
    ...  # (+ segment, page, stt, address fields, etc.)
}
```

### Column Mapping CSV → DB
Definitive mapping (từ `STSDataIngestion/src/data_processing/.../validation_handler.py`):
```python
COLUMN_IMP_MAPPING = {
    "Declaration No":        "declaration_number",
    "Transaction Date":      "transaction_date",
    "HS Code":               "hs_code",
    "Product Description":   "product_description",
    "Product Desc(EN)":      "product_description_en",
    "Supplier":              "supplier_name",
    "Buyer":                 "buyer_name",
    "quantity":              "quantity",
    "Quantity unit":         "quantity_unit",
    "Unit Price(USD)":       "unit_price_usd",
    "Unit Price(Currency)":  "unit_price_foreign_currency",
    "Total Price(Currency)": "total_price_foreign_currency",
    "Amount":                "total_amount_usd",
    "Exchange Rate":         "exchange_rate",
    "Incoterms":             "incoterms",
    "Payment Method":        "payment_method",
    "Import Country":        "import_country",
    "Mode of Transport":     "transport_mode",
    "Country of Origin":     "country_of_origin",
    "Customs Br Code":       "customs_branch_code",
    "Customs Br Name":       "customs_branch_name",
    "bill_id":               "bill_id",
    "buyer_country":         "buyer_country",
    "customs_branch_code_2": "customs_branch_code_secondary",
    "date":                  "date",
    "exporter_country":      "exporter_country",
    "foreign_currency":      "foreign_currency",
    "importer_address_vn":   "importer_address_vn",
    "importer_name_en":      "importer_name_en",
    "importer_tel":          "importer_tel",
    "type_of_import":        "import_type",
}
```

### DB Tables

**Staging (raw insert):** `hs_raw_data`
- 31 raw columns (từ CSV) + `need_check`, `data_source`, `mongo_file_id`
- Là `crawling_data.temp` equivalent — **cần verify**: query `information_schema.columns` để xác nhận tên bảng thực trên sts-dev

```sql
-- Verify staging table:
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name IN ('hs_raw_data', 'temp')
  AND table_schema IN ('public', 'crawling_data');

-- Verify columns:
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'hs_raw_data'   -- hoặc 'temp'
ORDER BY ordinal_position;
```

**Fact tables:** `import.Fact_2025`, `import.Fact_2026`, `export.Fact_2025`, `export.Fact_2026`
- 54 cols = 33 raw + 21 FK IDs (lookup sau khi insert staging)
- FK IDs được fill bởi ETL sau (stored procedure hoặc script riêng)

**⚠️ Action required:** Trước khi chạy pipeline_loader.py, xác nhận:
1. Tên bảng staging (`hs_raw_data` hay `crawling_data.temp`)
2. Nếu staging table chưa tồn tại → chạy `02_ingestion_pipeline/scripts/init-dbs.sql`

---

## 5. Package Structure

```
sts_pipeline_server/
├── CONTEXT.md                      ← ĐÂY (đọc trước)
│
├── 01_crawl_tool/                  ← Scraper cho Windows machines
│   ├── src/                        ← Core source code (Selenium + API)
│   ├── scripts/
│   │   ├── upload_to_drive.py      ← Upload output CSV → Google Drive
│   │   └── notify.py               ← Telegram notification (optional)
│   ├── tools/                      ← Maintenance scripts
│   │   ├── check_latest_data.py    ← Verify dữ liệu mới nhất
│   │   ├── convert_to_excel.py     ← CSV → XLSX conversion
│   │   ├── filter_by_hscode.py     ← Filter data by HS code
│   │   └── merge_daily_pro.py      ← Merge daily segments
│   ├── configs/
│   │   ├── _local_acc1.py          ← ACC1 config (username/password/batch) ⚠️ SENSITIVE
│   │   ├── _local_acc2.py          ← ACC2 config ⚠️ SENSITIVE
│   │   ├── _local_acc3.py          ← ACC3 config ⚠️ SENSITIVE
│   │   ├── _local_acc4.py          ← ACC4 config ⚠️ SENSITIVE
│   │   └── _local_template.py      ← Template for new accounts
│   ├── plugin/
│   │   └── proxy_auth_plugin.zip   ← Chrome extension for proxy auth
│   ├── run.py                      ← Main entry point
│   ├── run_forever.bat             ← Windows auto-restart runner
│   ├── setup.bat                   ← First-time setup (pip install, etc.)
│   └── requirements.txt
│
├── 02_ingestion_pipeline/          ← Airflow pipeline (Drive → PostgreSQL)
│   ├── src/                        ← Clean Architecture: data_loader, data_processing
│   │   ├── data_loader/            ← Download from Google Drive / S3 / API
│   │   ├── data_processing/        ← Validate, normalize, enrich
│   │   └── shared/                 ← PG repo, Mongo repo, settings
│   ├── dags/
│   │   ├── dag_ingest.py           ← Daily DAG: Drive sensor → download → PG insert
│   │   ├── dag_export.py           ← Export DAG
│   │   └── wrapper/pipeline_wrapper.py  ← Core orchestration logic
│   ├── docker-compose.yml          ← Airflow + PostgreSQL + MongoDB
│   ├── Dockerfile
│   ├── .env.example                ← Copy → .env, fill credentials
│   ├── scripts/
│   │   ├── init-dbs.sql            ← DB schema init (run once)
│   │   └── google_drive_auth.py   ← OAuth token setup (run once)
│   └── pyproject.toml
│
├── 03_pipeline_loader/             ← Lightweight alternative to Airflow
│   ├── pipeline_loader.py          ← CSV → hs_raw_data (no Airflow dependency)
│   └── watch_and_ingest.sh         ← Cron: SSH pull → load → (NER)
│
└── 04_ner_enrichment/              ← Phase 2: NER enrichment
    └── ner_enricher.py             ← xlm-roberta → product_name_clean / fabric_pct / item_condition
```

---

## 6. Setup Instructions (Priority Order)

### Phase 1: Get data flowing into PostgreSQL

**Step 1: Verify DB connection**
```bash
export PG_HOST=localhost  # hoặc IP của DB container
export PG_PASS=<password>
psql -h $PG_HOST -U postgres -d sts-dev -c "\dt crawling_data.*"
psql -h $PG_HOST -U postgres -d sts-dev -c "\dt public.hs_raw_data"
```

**Step 2: Create staging table nếu chưa có**
```bash
psql -h $PG_HOST -U postgres -d sts-dev -f 02_ingestion_pipeline/scripts/init-dbs.sql
```

**Step 3: Verify SSH access to crawl machines**
```bash
ssh pc@100.76.219.16 "dir C:\\Crawl\\acc1\\crawl_w52_sts\\output" 2>&1 | head -5
ssh pc@100.76.65.2   "dir C:\\Crawl\\acc3\\crawl_w52_sts\\output" 2>&1 | head -5
```

**Step 4: Test pull + load on 1 file**
```bash
mkdir -p /data/raw/acc1
rsync -av pc@100.76.219.16:"C:/Crawl/acc1/crawl_w52_sts/output/detail_Vietnam_import_hs52_JAN_2026.csv" /data/raw/acc1/
python3 03_pipeline_loader/pipeline_loader.py --file /data/raw/acc1/detail_Vietnam_import_hs52_JAN_2026.csv --dry-run
# Nếu dry-run ok → bỏ --dry-run để insert thật
```

**Step 5: Setup cron (every 2 hours)**
```bash
chmod +x 03_pipeline_loader/watch_and_ingest.sh
crontab -e
# Thêm dòng:
# 0 */2 * * * /opt/sts/03_pipeline_loader/watch_and_ingest.sh >> /data/logs/cron.log 2>&1
```

### Phase 2: Airflow (nếu cần orchestration nâng cao)
```bash
cd 02_ingestion_pipeline
cp .env.example .env
# Edit .env: POSTGRES_HOST, GOOGLE_CREDENTIALS_PATH, MONGO_HOST
python scripts/google_drive_auth.py  # One-time OAuth setup
docker compose up -d
# Airflow UI: http://localhost:8080 (user: admin, pass: from .env)
```

### Phase 3: NER enrichment (sau khi Phase 1 stable)
```bash
# Install NER dependencies
pip install transformers torch tqdm

# Edit ner_enricher.py: replace <HF_USERNAME> với HuggingFace username thật
# Test dry run:
python3 04_ner_enrichment/ner_enricher.py --dry-run --limit 20

# Chạy full:
python3 04_ner_enrichment/ner_enricher.py --batch-size 200
```

---

## 7. Google Drive Structure

```
STS/2026/
├── hs52/ → detail_Vietnam_{import|export}_hs52_{MON}_2026.{csv,xlsx}
├── hs53/ → ...
├── hs54/ → ...
├── hs55/ → ...
├── hs56/ → ...
├── hs57/ → ...
├── hs58/ → ...
├── hs60/ → ...
└── hs61/ → ...
```

**Drive folder ID (dag_ingest.py):** `1O80UyeZUXugNk3QI1IASX2PWWoBfVO82`

**Setup rclone (for Drive sync):**
```bash
rclone config  # tạo remote "mydrive" với Google Drive OAuth
# Test:
rclone ls mydrive:STS/2026/hs52/ | head -5
```

---

## 8. Known Issues & Gotchas

1. **hs54 Import FEB 2026 sai data**: File trên ACC1 machine có 71 cols, HS codes sai (1902, 2209, 3004 thay vì 54xx). Đừng upload file này. Cần crawl lại.

2. **hs55 Export APR 2026 partial**: Chỉ có 3,627 rows (dừng ở page 88/X). Cần crawl completion.

3. **APR 2026 data thưa**: hs56/58 APR chỉ vài nghìn rows (website chưa publish đủ vào lúc crawl tháng 5/2026). Không phải lỗi crawl.

4. **Crontab đã xóa**: Cron sweep cũ (`drive_folder_sweep.sh`) đã bị remove sau khi sửa bug Drive folder tháng 6/2026. Không cần restore.

5. **Windows path trong rsync**: Dùng forward slash khi rsync qua SSH vào Windows:
   ```bash
   rsync pc@IP:"C:/Crawl/acc1/..."  # đúng
   rsync pc@IP:"C:\\Crawl\\acc1\\..."  # sai trên bash
   ```

6. **Staging table name**: Cần verify xem DB dùng `hs_raw_data` (tên trong STSDataIngestion) hay `crawling_data.temp` (tên user đề cập). Query `information_schema` trước khi insert.

7. **NER model path**: `<HF_USERNAME>` trong `ner_enricher.py` chưa được fill — cần replace bằng HuggingFace username thật trước khi chạy Phase 2.

8. **ACC4 bottleneck**: Dự kiến xong 30/06/2026 (hs60, hs61 Export rất nhiều data).

---

## 9. Contacts & Credentials Summary

| Item | Value |
|---|---|
| sts-1 Windows login | `20232023` |
| sts-1 Tailscale IP | `100.121.146.104` |
| Máy 1 IP | `100.76.219.16` |
| Máy 3 IP | `100.76.65.2` |
| SSH to Máy 1/3 | `ssh pc@<IP>` (key auth) |
| DB name | `sts-dev` |
| Drive folder root | `STS/2026/` |
| Drive folder ID | `1O80UyeZUXugNk3QI1IASX2PWWoBfVO82` |
| Crawl site | `https://pro.52wmb.com` |

---

## 10. Quick Reference Commands

```bash
# Xem trạng thái crawl trên machines
ssh pc@100.76.219.16 "dir C:\\Crawl\\acc1\\crawl_w52_sts\\output"
ssh pc@100.76.219.16 "dir C:\\Crawl\\acc2\\crawl_w52_sts\\output"
ssh pc@100.76.65.2 "dir C:\\Crawl\\acc3\\crawl_w52_sts\\output"
ssh pc@100.76.65.2 "dir C:\\Crawl\\acc4\\crawl_w52_sts\\output"

# Đếm rows trong staging table
psql -d sts-dev -c "SELECT COUNT(*) FROM hs_raw_data;"

# Kiểm tra data mới nhất
psql -d sts-dev -c "SELECT MAX(transaction_date), COUNT(*) FROM hs_raw_data GROUP BY data_source;"

# Manual run pipeline
python3 /opt/sts/03_pipeline_loader/pipeline_loader.py --dir /data/raw/acc1

# Check Drive content
rclone ls "mydrive:STS/2026/" --include "*.csv" | wc -l
```
