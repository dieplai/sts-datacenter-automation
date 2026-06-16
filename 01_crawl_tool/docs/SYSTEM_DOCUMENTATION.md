# 📚 VIETNAM CUSTOMS DATA SCRAPER - COMPLETE SYSTEM DOCUMENTATION

> **Version**: 3.0.0  
> **Last Updated**: 2026-04-17  
> **Purpose**: Comprehensive reference for system architecture, workflow, and data structure

## 📝 CHANGE LOG

| Date       | Version | Change                                                                                                                                                                                                                                                                                           |
|------------|---------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 2026-04-17 | 3.0.0   | **Streamlined Pipeline**: Deprecated and removed Fast Mode, Analysis Mode, and Legacy codebases to focus entirely on the core Production Workflow (Pro Detail Mode). Updated directories and config documentation to reflect the clean system state.                                             |
| 2026-03-16 | 2.0.0   | **Auto-Restart via OS-level Batch Script**: Removed python-level `while True` to prevent memory leaks. Created `run_forever.bat` to manage restarting and force killing `chrome.exe`.                                                                                                          |
| 2026-02-23 | 1.9.1   | **Test Mode & Performance Benchmarking**: Added `TEST_MODE` to validate logic flow without saving data. Updated Chrome to `version_main=145`.                                                                                                                                                  |
| 2026-02-02 | 1.8.0   | **Batch & Logic Optimization**: Integrated `finalize_pro_detail.py` as the primary finalization tool with smart column merging and equivalence detection.                                                                                                                                        |
| 2026-01-28 | 1.7.2   | **Double Safety & No-Skip**: Implemented 2-Layer Date Integrity Check. "No-Skip" Policy constraints.                                                                                                                                                                                             |

---

## 📑 TABLE OF CONTENTS

1. [System Overview](#-system-overview)
2. [Configuration](#-configuration)
3. [Architecture & Workflow](#-architecture--workflow)
4. [Data Structure](#-data-structure)
5. [Operation / Usage](#-operation--usage)
6. [Codebase Reference](#-codebase-reference)
7. [Troubleshooting](#-troubleshooting)

---

# 🎯 SYSTEM OVERVIEW

## Purpose

Scrape export/import transaction data from [52wmb.com](https://en.52wmb.com) with advanced features for reliability and scale.

## Key Features

- ✅ **Resume-safe**: Can stop and resume at any point (file-based state).
- ✅ **Memory-efficient**: Direct-to-CSV streaming to avoid Out-Of-Memory errors.
- ✅ **Self-healing**: Automatic recovery from network errors and session timeouts.
- ✅ **Segment-aware**: Handles API limits (10k records) by shifting date ranges.
- ✅ **Dynamic Schema**: Auto-expands CSV columns when new data fields appear.
- ✅ **Batch Processing**: Run multiple search configurations sequentially (Single, Multi, Daily modes).

## 🚀 Pro Detail Mode (Primary)

The system is tightly optimized around **Pro Detail Mode** (Market Analysis) to scrape accurate and deep transaction history. The legacy and generic modes have been stripped away for stability.

---

## 🗺️ Pipeline Tổng Quát (Non-Technical) / System Pipeline Overview

1. **Đăng nhập (Login)**: Hệ thống tự động login vào trang `pro.52wmb.com`. (Bypass legacy UI).
2. **Điều hướng (Navigation)**: Truy cập trang Workbenches → Market Analysis → Customs Data.
3. **Form Tìm Kiếm (Search Form)**: Tự động nhập thông tin cấu hình (Country, Import/Export, Date Range, HS Code, v.v.)
4. **Cào Dữ Liệu Từng Trang (Scraping)**: Với mỗi trang kết quả, hệ thống tự động **click vào nút "Details"** của từng dòng. Sau khi click, mã nguồn lập tức bắt (intercept) gói tin trả về từ Request Network API để lấy full data và ghi ngay vào file `CSV`.
5. **Giới hạn 10k Records (Handling Limits)**: Khi website chạm mốc giới hạn, lấy mốc thời gian của record cuối cùng → Cập nhật lại End Date của bộ lọc → Bắt đầu cào tiếp một Segment mới để không sót data.
6. **Output**: File CSV cuối cùng lưu tại mục `output/` có thể được làm sạch hoặc convert sang Excel bằng tool ở ngoài.

---

# 📝 CONFIGURATION

Configuration is located within `src/config.py`.

## 1. Execution Modes

```python
# --- EXECUTION MODE ---
# "single" = use DETAIL_* config variables below
# "multi"  = use TRANSACTIONS_BATCH list
# "daily"  = iterate day-by-day automatically for massive volume pipelines
DETAIL_SUBMODE = "single"  
```

## 2. Single Mode Parameters

Used strictly when `DETAIL_SUBMODE = "single"`:

```python
DETAIL_COUNTRY = "Vietnam"  
DETAIL_DATA_TYPE = "Import data"  # or "Export data"
DETAIL_START_DATE = "2023-01-01"  
DETAIL_END_DATE = "2023-12-31"   
DETAIL_HS_CODE = "55"           
DETAIL_PRODUCT = ""             
DETAIL_BUYER = ""               
DETAIL_SUPPLIER = ""            
```

## 3. Batch Processing (`multi`)

When `DETAIL_SUBMODE = "multi"`, the scraper iterates through predefined dictionaries in `TRANSACTIONS_BATCH`. 

```python
TRANSACTIONS_BATCH = [
    {
        "name": "im_buyer_thaituan_23_26", 
        "hs_code": "", 
        "data_type": "Import data", 
        "start_date": "2023-01-01", 
        "end_date": "2026-12-31", 
        "buyer": "thaituan", 
        "expected": 2417
    }
]
```

## 4. Test Mode

Set to `True` to validate the entire workflow without saving physical datasets (Good for dry runs):

```python
TEST_MODE = False
TEST_SEARCH_CONFIG = { ... }
```

---

# 🏗️ ARCHITECTURE & WORKFLOW

## System Flow Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    CONFIG (config.py)                        │
│   Single Mode or Multi Mode (Batch)                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│            MAIN ENTRY POINTS (core_pro_detail.py)            │
│  1. detect_resume_point() → Read CSV for resume state       │
│  2. Initialize ScraperProDetail                             │
│  3. Login → Navigate → Fill Form → Scrape Loop              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│         SCRAPER CORE (ScraperProDetail.scrape_detail...)     │
│                                                              │
│  🔴 CRITICAL: Data sorted DESCENDING by Transaction Date    │
│     (NEWEST → OLDEST) to allow segmentation.                 │
│                                                              │
│  ┌──────────────────────────────────────────────┐           │
│  │  SEGMENT 1: Pages 1-333 (NEWEST Data)       │           │
│  │  Max: 9,990 records                          │           │
│  └──────────────────────────────────────────────┘           │
│                       │                                      │
│                       │ [Reached Limit]                      │
│                       ▼                                      │
│  ┌──────────────────────────────────────────────┐           │
│  │  SEGMENT 2: Pages 1-333 (OLDER Data)        │           │
│  │  SHIFT: "All Clear" → Fill Boundary Date     │           │
│  │  RESET: Click Page 1 explicitly              │           │
│  └──────────────────────────────────────────────┘           │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              DATA SAVE                                       │
│  - Append to CSV immediately (no buffering)                 │
│  - Auto-expand schema for new columns                       │
└─────────────────────────────────────────────────────────────┘
```

## 🔴 Critical: Segment Boundary Logic

The API inherently caps search responses at roughly ~10,000 items. To bypass this, we use **Reverse Date Segmentation**:
1. **Sort Direction**: Records process backwards (Newest → Oldest).
2. **Boundary Marking**: At record 9,990 (Page 333 limit), the script snags the `Transaction Date`.
3. **Shift Execution**: The `Transaction Date` feeds back into a search form reset as the new `End Date` ceiling.
4. If resuming crashes mid-segment, it reads the boundary dates exclusively from disk state logs.

---

# 📊 DATA STRUCTURE

## Output Source
- **Format**: Core is stored iteratively to `.csv` format during active loops. 
- **Naming**: Generated procedurally via configuration: `detail_{Country}_{BatchName}.csv`

## Field Mapping (Dynamic)
The underlying architecture processes columns dynamically by extracting JSON keys directly from intercepted network packets (`/async/raw/bill/detail`).

| Column Name | Formatted Header | Information Context |
|-------------|------------------|----------------------|
| `date` | Transaction Date | Execution timeframe |
| `hs` | HS Code | Harmonized system standard |
| `buyer` | Buyer / Importer | The target importing entity |
| `amount` | Amount | Extracted gross value (USD/FC) |

_The system typically identifies between 60 to 90 distinct data columns depending dynamically on local regulations._

---

# ⚡ OPERATION / USAGE

## Primary Startup
Configure everything in `src/config.py` and run:

```bash
python run.py
```

## Continuous Endurance Running (`run_forever.bat`)
Always recommended. This invokes the OS-level controller. Should python crash (Out-Of-Memory, Dead Network Socket), the terminal force-kills background processes and begins fresh without losing state.

```bat
.\run_forever.bat
```
_Stopping it safely: Spammed `Ctrl+C` into terminal, hit `Y` for termination when prompted._

---

# 🏗️ CODEBASE REFERENCE

## Directory Structure

```text
scrape_new/
├── src/
│   ├── config.py                 # ⭐ Configuration Parameters
│   ├── main.py                   # Script Launcher Core
│   └── scraper/
│       ├── core_pro_detail.py    # ⭐⭐⭐ PRIMARY JOB: Pagination, Segment Logic, Resume states
│       ├── core_pro_daily.py     # Variant for massive daily-segmented jobs
│       ├── navigator_pro.py      # UI Manipulator (Forms, Login, Dropdowns)
│       └── api_client.py         # Network interception logic
├── tools/
│   ├── finalize_pro_detail.py    # Merges duplicated column schemas and sanitizes entries
│   ├── extract_glass_cullet.py   # Specialized data extraction scripts
│   ├── convert_to_excel.py       # Basic CSV-to-XLSX wrapper
│   └── inspect_conflicts.py      # Output header conflict visualizer
├── output/                       # Result data lands here
├── html_debug/                   # HTML page dumps for failure states
└── data/                         # Intermediate assets
```

---

# 🔧 TROUBLESHOOTING

### 1. "Resuming into Segment > 1 but segment_end_date is None"
- **Cause**: Corrupted saving state. File generated zero rows before crash.
- **Fix**: Scrub target CSV, modify config explicitly to older timeline, or delete file to start from scratch.

### 2. Form Timeout / React Elements Not Loading
- **Cause**: Dead browser socket or IP temporary blockage.
- **Fix**: Leave it alone. The script utilizes **Deep Recovery**, hard-killing the system process level and resetting via proxy connection states. 

### 3. Stability Mechanics Internals
- **Kill-Switches `force_kill_chrome`**: Embedded `taskkill /F /IM chromedriver.exe` purges zombie resources continuously.
- **Fail-Fast Tolerances**: Selenium applies strict 45-second eager load policies to prevent eternal white screen hangs.
- **Data Integrity Safety Check**: Will consistently raise exception to cancel execution if target UI tables report wildly illogical counts against expected.
