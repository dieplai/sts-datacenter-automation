```markdown

---

## 📦 Các Module Chính

### 1. **ValidateSource.py** - Xác Thực Nguồn Dữ Liệu

**Chức Năng:**
- Xác thực tính hợp lệ của thư mục/file dữ liệu
- Kiểm tra định dạng file (EXCEL, CSV, v.v.)
- Trả về danh sách các file hợp lệ

- `validate_source(full_path, source_type, file_type)` - API chính
  - `source_from`: LOCAL , S3 , ....
  - `source_type`: EXCEL, CSV (FileFormat enum)

**Output:**
```python : dict
{
    "status": "success",
    "message": "Success",
    "value": ["file1.xlsx", "file2.xlsx", ...]
}
```

---

### 2. [**FormatData.py**](http://formatdata.py/) - Định Dạng Dữ Liệu

**Chức Năng:**

- Nhận kết quả từ `validate_source`
- Clean Buyer
- Return
    - Buyer Cleaned ghi vào DB
    - Buyer UnCleaned ghi vào file bao gồm các cột [’Buyer Cleaned’, ’Buyer Address’, ‘Buyer’

---

### 3. [**SimplePipelineDag.py**](http://simplepipelinedag.py/) - Orchestration (Airflow DAG)

**Chức Năng:**

- Orchestrate toàn bộ pipeline
- Quản lý dependency giữa các task
- Lập lịch tự động chạy hàng ngày

**Pipeline Flow:**

```
load_data → process_data → save_data
```

**Chi Tiết:**

- **load_data()**: Gọi `validate_source` để lấy danh sách file từ thư mục Export
- **process_data()**: Nhận output từ load_data (stage handling_data)
- **save_data()**: Lưu dữ liệu đã xử lý

**Cấu Hình:**

- Chạy hàng ngày (schedule_interval=timedelta(days=1))
- Retry tối đa 1 lần với delay 5 phút
- Tags: `['simple_pipeline']`

---

## 🔄 Format Data Pipeline (handling_data Stage)

Dựa trên `clean_buyer.ipynb`, stage **handling_data** bao gồm các bước sau:

### Flow Diagram

```

[2] Buyer Address Combination
    ├─ Merge 8 cột Buyer Address thành 1 cột
    └─ Output: 'Buyer Address' column
    ↓
[3] Buyer Mapping
    ├─ Load mapping từ buyer_mapping_full.json
    └─ Map giá trị 'Buyer' → 'Buyer Cleaned'
    ↓
[4] Buyer Address Mapping ( để validate lại Buyer)
    ├─ Load mapping từ address_mappingV3.json
    ├─ Map giá trị 'Buyer Address'
    └─ Handle null values (fallback to original)
    ↓
[5] Data Validation
    ├─ Group by 'Buyer Cleaned'
    ├─ Extract unique pairs (Buyer Address, Buyer)
    ├─ case : 
    └─ case : 1 Buyer - 1 Address -> push into db 
    ↓
[6] Data Export
    ├─ Export unique buyers
    ├─ Export processed pairs
    └─ CSV/Excel format
```