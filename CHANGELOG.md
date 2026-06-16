# CHANGELOG

## [1.0.0] — 2026-06-16

> **STS Data Warehouse — Automated Medallion Pipeline**
> Đưa hệ thống từ thủ công hoàn toàn sang pipeline tự động end-to-end:
> crawl → DQ gate → staging → Gold, không cần thao tác tay sau khi crawl xong.

---

## 2026-06-15

### 12:49 — Khởi tạo 2 module cuối

| File | Mô tả |
|---|---|
| `03_pipeline_loader/pipeline_loader.py` | Loader nhẹ CSV→PostgreSQL, độc lập với Airflow, chạy qua cron |
| `04_ner_enrichment/ner_enricher.py` | Enricher XLM-RoBERTa (F1=0.9923) — NER nhãn textile: `product_name_clean`, `fabric_pct`, `item_condition` |
| `CONTEXT.md` | Tài liệu tổng quan toàn bộ 4 module pipeline |

---

### 15:10 — Thiết kế kiến trúc data warehouse

Brainstorm session → spec `docs/superpowers/specs/2026-06-15-datacenter-pipeline-design.md`

**Quyết định kiến trúc chốt:**
- **Medallion Architecture**: Bronze (immutable) → Silver (validated) → Gold (Fact tables)
- **PostgreSQL giữ nguyên là Windows service** — không chuyển vào Docker, tránh migrate 204 GB
- **Tablespace `sts_new` trên D drive** — tách data 2025/2026 khỏi data lịch sử 2012–2024
- **Idempotency** qua `UNIQUE (DeclarationNO, HSCode, TradeDate)` + `ON CONFLICT DO NOTHING`
- **Audit trail** mỗi file: `crawling_data.ingestion_log` ghi đầy đủ trạng thái

**Schema mới được thiết kế:**
- `crawling_data.ingestion_log` — audit log per file
- `crawling_data.hs_raw_data` — staging table chuẩn với FK stubs
- `import.Fact_2025`, `import.Fact_2026`, `export.Fact_2025`, `export.Fact_2026`

---

### 15:50 — Kế hoạch triển khai staging & data pull

Spec `docs/superpowers/plans/2026-06-15-staging-tables-and-data-pull.md`

---

### 15:56 — PostgreSQL setup

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\01_setup_pg.sql` | Tạo tablespace `sts_new`, tất cả bảng mới, indexes, constraints |

---

### 16:31 — Gold layer SQL

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\05_build_gold.sql` | SQL populate `import/export.Fact_2025/2026` từ `hs_raw_data` qua FK resolution |

---

### 17:05 — Gold runner & monitoring scripts

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\06_run_gold.py` | Runner chính cho Gold layer build — gọi từ pipeline |
| `D:\datacenter\scripts\06b_resume_gold.py` | Resume Gold build từ điểm dừng (chạy lại partial) |
| `D:\datacenter\scripts\check_progress.py` | Theo dõi tiến độ load theo thời gian thực |
| `D:\datacenter\scripts\verify_gold.py` | Xác minh row count + FK rate sau Gold build |
| `D:\datacenter\scripts\s7_masterdata.py` | Populate/update MasterData dimension tables |
| `D:\datacenter\scripts\pg_activity.py` | Xem query đang chạy trong PostgreSQL |
| `D:\datacenter\scripts\pg_locks.py` | Xem lock conflicts |
| `D:\datacenter\scripts\pg_check8596.py` | Kiểm tra health theo port 8596 |
| `D:\datacenter\scripts\pg_kill.py` | Kill query/connection cụ thể |
| `D:\datacenter\scripts\pg_roles.py` | Kiểm tra roles & permissions |

---

### 17:56 — Crawl config multi-account

| File | Mô tả |
|---|---|
| `01_crawl_tool/_local_template.py` | Template config chung |
| `01_crawl_tool/_local_acc1.py` | Config riêng ACC1 — Máy 1 (100.76.219.16) |
| `01_crawl_tool/_local_acc2.py` | Config riêng ACC2 — Máy 1 |
| `01_crawl_tool/_local_acc3.py` | Config riêng ACC3 — Máy 3 (100.76.65.2) |
| `01_crawl_tool/_local_acc4.py` | Config riêng ACC4 — Máy 3 |

---

### 18:44 — Google Drive pull script

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\02_pull_gdrive.ps1` | Pull toàn bộ CSV từ Google Drive folder `1O80UyeZUXugNk3QI1IASX2PWWoBfVO82` về `D:\datacenter\bronze\` |

---

### 21:26 — Converter dữ liệu lịch sử 2025

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\02b_convert_2025_xlsx.py` | Convert file XLSX 2025 sang CSV chuẩn — đồng nhất format với 2026 |

---

### 22:02 — Data quality validation

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\03_data_quality.py` | Kiểm tra 5 rules per file: required cols, row count ≥ 100, HS prefix match, duplicate check, date range |

**DQ rules:**

| Rule | Ngưỡng | Action |
|---|---|---|
| Required columns | Buyer, Supplier, HSCode, TradeDate, TotalValue_USD | Reject |
| Row count | ≥ 100 rows | Reject |
| HS code prefix | ≥ 95% rows khớp prefix từ filename | Reject |
| Duplicate file | filename chưa có trong ingestion_log | Skip (idempotent) |
| Date range | ≥ 95% ngày nằm đúng month/year của file | Warn only |

---

### 22:35 — Staging loader

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\04_load_staging.py` | Load CSV đã validated vào `crawling_data.hs_raw_data` — dùng `psycopg2.copy_expert`, idempotent qua `ON CONFLICT DO NOTHING` |

---

### 23:06 — Historical reload

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\06c_reload_2025.py` | Reload toàn bộ data 2025 từ đầu — truncate staging 2025 rồi load lại |

---

## 2026-06-16

### 00:06 — End-to-end verification

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\verify_all.py` | Health check toàn pipeline: row counts per table, FK rates, file count vs ingestion_log, quarantine status |

---

### 00:40 — Crawl tool refactor

| File | Mô tả |
|---|---|
| `01_crawl_tool/navigator_pro.py` | Refactor navigation layer cho pro.52wmb.com — tách khỏi core crawler |
| `01_crawl_tool/core_pro_detail.py` | Refactor detail capture — pagination + retry riêng biệt |
| `01_crawl_tool/settings.py` | Centralize toàn bộ settings vào một nơi |

---

### 01:05 — Thiết kế automation pipeline

Spec `docs/superpowers/specs/2026-06-16-crawl-automation-pipeline-design.md`

**Kiến trúc pull-based chốt:**
- Storage machine poll 2 crawl server mỗi **5 phút** qua Task Scheduler + robocopy qua UNC share
- Post-crawl: crawl server tự generate manifest (SHA256 + row counts) sau mỗi batch xong
- Per-file DQ gate: file xấu vào quarantine, file tốt load bình thường — không block nhau
- Gold rebuild nightly 3 AM: TRUNCATE + reload từ staging, kiểm tra FK rate, gửi email báo cáo

**Data integrity chain:**
```
Crawl writes CSV
  → SHA256 + row_count → manifest.json
  → robocopy pull
  → SHA256 re-verify sau transfer
  → stability check (size stable 5s)
  → DQ gate per file
  → COPY to staging
  → row reconciliation vs manifest (gap ≤ 1%)
  → [3 AM] TRUNCATE + reload Gold
  → FK rate check ≥ 85%
```

---

### 01:19 — Implementation plan

Plan `docs/superpowers/plans/2026-06-16-crawl-automation-pipeline.md`

---

### 01:20 — Automation scripts (core)

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\dq_gate.py` | DQ gate module: `check_file(path) -> DQResult` — quarantine tự động file lỗi, không raise exception |
| `D:\datacenter\scripts\sync_servers.py` | Robocopy pull từ 2 crawl servers — đọc config từ `D:\datacenter\config\servers.json` |
| `01_crawl_tool/scripts/generate_manifest.py` | Chạy on-success trên crawl server: scan output CSV, tính SHA256 + row count, ghi `manifest_<account>_<timestamp>.json` |

**DQ gate rules (hard fail → quarantine):**

| Rule | Threshold |
|---|---|
| Row count | < 100 rows |
| HS code prefix mismatch | > 5% rows |
| Negative amounts | bất kỳ giá trị âm |
| SHA256 mismatch vs manifest | re-pull + alert |

**DQ warn only (load bình thường):**

| Rule | Threshold |
|---|---|
| Date parse failure | ≤ 5% unparseable |
| Amount null rate | ≤ 5% null |

---

### 01:21 — Main orchestrator

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\pipeline_watcher.py` | Orchestrator chính — flags: `--once`, `--no-sync`, `--dry-run`; acquire lock, sync, DQ, load, reconcile, release lock |

**Flow:**
1. Acquire lock (`D:\datacenter\.watcher.lock`) — stale lock > 10 min tự xóa
2. `sync_servers.py` (skip nếu `--no-sync`)
3. Discover CSV mới trong bronze chưa có trong ingestion_log
4. Per file: stability check → SHA256 verify → DQ gate → load staging → reconcile
5. Manifest completion check → move `pending/` → `done/`
6. Summary email nếu có file được xử lý
7. Release lock

---

### 01:22 — Nightly Gold rebuild & E2E test

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\gold_rebuild.py` | Wrapper nightly: row counts before/after, gọi `06_run_gold.py`, FK rate check, gửi email báo cáo |
| `D:\datacenter\scripts\test_pipeline.py` | E2E test: tạo CSV tổng hợp → mock manifest → `pipeline_watcher --dry-run` → `pipeline_watcher` thật → assert ingestion_log → dọn dẹp |

---

### 08:51 — Deploy to Task Scheduler

| File | Mô tả |
|---|---|
| `D:\datacenter\scripts\setup_task_scheduler.ps1` | Đăng ký 2 Windows Task Scheduler tasks |

**Tasks đã đăng ký:**

| Task | Schedule | Command |
|---|---|---|
| `STS_PipelineWatcher` | Mỗi 5 phút | `python pipeline_watcher.py --once` |
| `STS_GoldRebuild` | Hàng ngày 03:00 | `python gold_rebuild.py` |

Cả 2 task chạy dù user không đăng nhập.

---

## Audit & Observability

Mọi event được ghi vào `D:\datacenter\logs\audit_YYYYMMDD.jsonl`:

```jsonl
{"ts":"...","event":"sync_start","servers":["CRAWL-SERVER-1","CRAWL-SERVER-2"]}
{"ts":"...","event":"dq_pass","file":"detail_Vietnam_import_hs52_MAY_2026.csv","rows":12543,"warnings":1}
{"ts":"...","event":"staging_loaded","file":"...","rows_staged":12543,"duration_s":4.1}
{"ts":"...","event":"reconcile_ok","file":"...","gap_pct":0.0}
{"ts":"...","event":"run_summary","files_processed":3,"files_quarantined":0}
```

Gold rebuild logs: `D:\datacenter\logs\gold_*.log`
Staging load logs: `D:\datacenter\logs\load_*.log`

---

## Pending (cần làm trước live deploy)

- [ ] `D:\datacenter\config\servers.json` — điền hostname/IP thật của 2 crawl server
- [ ] Tạo Windows shares trên mỗi crawl server: `bronze$` và `manifests$`
- [ ] Set `ACCOUNT_NAME` trong `run_supervised.bat/.sh` của từng server (acc1/acc2/acc3/acc4)
- [ ] `generate_manifest.py` — deploy lên cả 2 crawl server
- [ ] Chạy `test_pipeline.py` lần cuối sau khi config xong
- [ ] Monitor audit log + email alert qua 1 crawl cycle đầu tiên live
- [ ] `04_ner_enrichment/ner_enricher.py` — thay `<HF_USERNAME>` bằng model ID thật trước khi deploy NER phase
