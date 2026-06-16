# Pipeline Architecture — Scraper to Data Warehouse

> **Last Updated:** 2026-04-03  
> **Scope:** 4 scraping machines → Lake → DE Pipeline → Warehouse

---

## 1. Bức Tranh Tổng Quan

```
[4 Máy Scraper]                [Lake]              [DE Pipeline]         [Warehouse]
────────────────               ───────             ─────────────         ───────────
Máy 1 ──┐                      S3 /                ValidateSource        PostgreSQL /
Máy 2 ──┤── scrape ──► CSV ──► MinIO /    ──────►  FormatData      ──►  BigQuery /
Máy 3 ──┤   finalize   XLSX    GCS /               SimplePipelineDAG     Snowflake
Máy 4 ──┘   upload             Supabase            (Airflow)             (TBD by DE)
                ↑
         [Job Queue / Control Plane]
         Supabase / Firebase / VPS
```

---

## 2. Phân Chia Trách Nhiệm

| Layer | Owner | Trách nhiệm |
|-------|-------|-------------|
| **Scraping** | Bạn (DS/Scraper) | Cào data, finalize CSV/XLSX, upload lên Lake |
| **Lake** | DE quyết định | Lưu raw files (S3 / MinIO / GCS) |
| **Pipeline** | DE | ValidateSource → FormatData → Airflow DAG |
| **Warehouse** | DE | DB đích, schema, query |
| **Job Control** | Bạn (hoặc chung) | Quản lý job queue cho 4 máy |

---

## 3. Vai Trò Của Từng Layer

### Data Lake
- **Là gì:** Object storage (S3/GCS/MinIO) — lưu file thô, không xử lý
- **Lưu gì:** CSV hoặc XLSX sau khi finalize
- **Tại sao cần:** Backup raw data (18M dòng cào mất nhiều tuần — mất là mất luôn), điểm tập trung cho 4 máy phân tán
- **Không phải:** Server chạy process, không cần query engine
- **Chi phí:** ~$1–2/tháng trên cloud cho 50GB

### Data Warehouse
- **Là gì:** DB có cấu trúc (Postgres / BigQuery / Snowflake) — dùng để query, BI
- **Do DE xây:** Bạn không cần đụng vào
- **Hiện tại:** Chưa có — DE đang build

### Excel / XLSX
- **Giới hạn cứng:** 1,048,576 rows / sheet
- **Kết luận:** Không dùng XLSX cho 18M dòng. CSV hoặc Parquet là format pipeline

### Parquet
- **Ai làm:** DE convert sau khi nhận từ Lake
- **Bạn không cần làm:** Chỉ cần deliver CSV/XLSX sạch

---

## 4. Expected Data Scale

### 4.1 Volume theo HS Chapter (2-digit)

| HS Chapter | Import (rows) | Export (rows) | Chapter Total | Vượt Excel limit? |
|-----------|--------------|--------------|---------------|-------------------|
| 51 | 18,905 | 3,334 | 22,239 | No |
| 52 | 330,589 | 311,356 | 641,945 | No |
| 53 | 19,218 | 8,800 | 28,018 | No |
| 54 | 781,722 | 482,488 | 1,264,210 | **Yes (>1M)** |
| 55 | 442,944 | 192,843 | 635,787 | No |
| 56 | 655,318 | 318,619 | 973,937 | No |
| 57 | 31,392 | 80,514 | 111,906 | No |
| 58 | 1,356,544 | 713,776 | 2,070,320 | **Yes (>1M)** |
| 59 | 696,457 | 334,000 | 1,030,457 | **Yes (>1M)** |
| 60 | 1,868,164 | 1,019,334 | 2,887,498 | **Yes (>1M)** |
| 61 | 812,830 | 3,308,868 | 4,121,698 | **Yes (>1M)** |
| 62 | 514,372 | 2,317,487 | 2,831,859 | **Yes (>1M)** |
| 63 | 627,998 | 1,077,794 | 1,705,792 | **Yes (>1M)** |
| **Tổng** | **8,156,453** | **10,169,213** | **18,325,666** | |

> **7/13 chapters** vượt giới hạn 1,048,576 rows của Excel — không thể dùng XLSX làm format pipeline.

---

### 4.2 File Granularity — Chapter có thể span ra nhiều file

Mỗi HS Chapter (2-digit) thực tế **không phải 1 file duy nhất** — có thể được scrape thành nhiều file nhỏ hơn theo sub-chapter (4/6/8-digit) tùy workload distribution.

**Ví dụ thực tế (Chapter 55 = 442,944 Import rows):**

```
Chapter 55 (Import) — thay vì 1 file → có thể là:
    detail_Vietnam_import_hs5511.csv   (~17,000 rows)
    detail_Vietnam_import_hs5512.csv   (~86,000 rows)
    detail_Vietnam_import_hs5513.csv   (~19,000 rows)
    detail_Vietnam_import_hs5514.csv   (~18,000 rows)
    detail_Vietnam_import_hs5515.csv   (~...)
    detail_Vietnam_import_hs5516.csv   (~26,000 rows)
    ...
```

**Ví dụ với Chapter 60 (1,868,164 Import rows — lớn nhất):**
```
Chapter 60 — bắt buộc phải split vì >1M rows:
    detail_Vietnam_import_hs6001.csv   (~59,922 rows)
    detail_Vietnam_import_hs6002.csv   (~...)
    detail_Vietnam_import_hs6003.csv   (~...)
    detail_Vietnam_import_hs6004.csv   (~...)
    ...
    → Hoặc split theo date range nếu 1 sub-chapter vẫn >333 pages (10K limit/segment)
```

**Quy tắc split:**
- **Theo sub-chapter (4/6-digit HS):** Chia nhỏ search query → mỗi máy scrape 1 sub-chapter
- **Theo date range:** Nếu 1 sub-chapter vẫn quá lớn → segment theo năm/quý
- **Theo filter (buyer/supplier):** Với custom request, 1 company = 1 file riêng

---

### 4.3 Ước tính số file thực tế

| Chapter | Import files (ước tính) | Export files (ước tính) |
|---------|------------------------|------------------------|
| 51 | 1 | 1 |
| 52 | 4–6 (6-digit sub) | 4–6 |
| 53 | 1–2 | 1 |
| 54 | 6–10 | 5–8 |
| 55 | 4–6 | 2–4 |
| 56 | 5–8 | 3–5 |
| 57 | 1–2 | 1–2 |
| 58 | 8–15 | 5–10 |
| 59 | 5–10 | 3–6 |
| 60 | 6–10 | 5–8 |
| 61 | 5–10 | 15–25 |
| 62 | 4–8 | 10–20 |
| 63 | 5–10 | 5–10 |
| **Tổng** | **~55–100 files** | **~60–110 files** |

> **Tổng ước tính: 115–210 CSV files** khi scrape đầy đủ 18M rows.  
> Lake cần handle **nhiều file nhỏ**, không phải 1 file khổng lồ.

---

### 4.4 Storage Estimate

| Format | Estimated Size (18M rows, ~100 cols) |
|--------|--------------------------------------|
| CSV (raw) | 30–60 GB |
| XLSX | **Không khả thi** (>1M rows/sheet limit) |
| Parquet (snappy compress) | 5–12 GB |
| Parquet (zstd compress) | 3–8 GB |

> **Recommendation:** CSV là format scraper output → DE convert sang Parquet trên Lake.

---

## 5. Vấn Đề Hiện Tại (Current State)

```
❌ run_forever.bat   → config hardcode, cần restart để nhận job mới
❌ finalize thủ công → interactive CLI, cần người ngồi chọn
❌ upload thủ công   → tay qua Google Drive
❌ 4 máy rời rạc    → không biết máy nào làm gì
❌ Warehouse chưa có → DE đang build
```

---

## 6. Target State (Automation hoàn toàn)

```
Người quản lý thêm job
    → INSERT vào Job Queue (Supabase / API)
    ↓
4 máy worker (poll mỗi 60 giây)
    → claim job
    → scrape (ScraperProDetail)
    → finalize (finalize_pro_detail core)
    → upload lên Lake (S3 / MinIO / GCS)
    → mark job done
    → (optional) notify DE Airflow webhook
    ↓
DE Pipeline (Airflow, daily schedule)
    → ValidateSource (đọc từ Lake)
    → FormatData (clean Buyer, merge Address)
    → push vào Warehouse DB
```

---

## 7. Không Cần Cùng Mạng

4 máy scraper đã có internet (scrape `pro.52wmb.com`) → dùng cloud services, không cần LAN/VPN.

| Component | Giải pháp không cần cùng mạng |
|-----------|-------------------------------|
| Job Queue | Supabase (free) / Firebase / VPS |
| Lake | S3 / GCS / MinIO cloud |
| Notify DE | HTTP webhook qua internet |

---

## 8. Job Queue — Không Cần Server Riêng

Dùng **Supabase (free tier)** thay server vật lý:

```sql
-- Bảng jobs trên Supabase
CREATE TABLE jobs (
    id          SERIAL PRIMARY KEY,
    hs_code     TEXT,
    data_type   TEXT,     -- 'Import data' / 'Export data'
    start_date  DATE,
    end_date    DATE,
    buyer       TEXT,
    supplier    TEXT,
    expected    INT,
    status      TEXT DEFAULT 'pending',  -- pending / running / done / failed
    machine_id  TEXT,                    -- machine_1 / machine_2 / ...
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    started_at  TIMESTAMPTZ,
    done_at     TIMESTAMPTZ
);
```

**4 máy worker loop:**
```
while True:
    job = claim_next_pending_job()   # atomic SELECT + UPDATE
    if job:
        scrape(job)
        finalize()
        upload_to_lake()
        mark_done(job.id)
    else:
        sleep(60)
```

---

## 9. Phân Chia Việc: Bạn Làm Gì Bây Giờ

### Làm ngay (không cần chờ DE)

| # | Việc | File cần sửa/tạo |
|---|------|------------------|
| 1 | Tách `finalize_pro_detail.py` thành callable (bỏ interactive input) | `tools/finalize_pro_detail.py` |
| 2 | Viết `upload_to_lake(file, config)` — placeholder, implement sau | `tools/upload_lake.py` (mới) |
| 3 | Thêm `machine_id` vào `config.py` | `src/config.py` |
| 4 | Viết `worker.py` — loop poll Supabase + scrape + finalize + upload | `worker.py` (mới) |
| 5 | Setup Supabase project + bảng jobs | External |

### Chờ DE confirm

| Việc | Cần biết |
|------|----------|
| Implement `upload_to_lake()` thật | Lake là S3 / GCS / MinIO? Credentials? |
| Notify DE sau upload | Webhook URL? API endpoint? |
| File format DE nhận | CSV hay XLSX? Naming convention? |
| WH connection (nếu cần) | DB type, host, credentials |

---

## 10. Connect Với DE Pipeline

Theo `README_Pipeline.md`, DE pipeline nhận file qua:
- `ValidateSource(full_path, source_from, file_type)` — đọc từ folder/S3
- `source_from`: `LOCAL`, `S3`, ...

**Bạn chỉ cần:** Upload file đúng format vào đúng path DE config.  
**DE tự xử lý:** Validate → Clean Buyer → push DB.  
**Optional (realtime hơn):** Gọi Airflow REST API trigger DAG ngay sau upload thay vì chờ daily schedule.

---

## 11. Summary Quyết Định Cần Làm

| Quyết định | Ai quyết | Deadline |
|-----------|---------|---------|
| Lake solution (S3 / GCS / MinIO) | DE | Càng sớm càng tốt |
| Warehouse DB type | DE | Càng sớm càng tốt |
| File format & path convention | Cả hai | Cần align ngay |
| Job Queue platform (Supabase?) | Bạn | Bạn quyết |
| Worker process (worker.py) | Bạn | Làm ngay được |
