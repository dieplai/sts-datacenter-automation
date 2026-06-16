""" Đây là wrapper của export. Đã implement thêm hàm upload_file bên file google_drive_service.py

Mục tiêu là upload những file đã process vào 2 hướng. Hướng 1 cho những file OK -> Postgre. Hướng 2 cho những file cần Valid lại bằng cơm -> Excel đẩy lên gg drive"""

from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pandas as pd
from shared.infrastructure.mongo.repositories.processing_result_repository import ProcessingResultRepository
from shared.infrastructure.service.google_drive_service import google_drive_service
from shared.infrastructure.setting.google_drive_setting import GoogleDriveSetting

def wrap_export_to_ggdrive(**context) -> dict:
    """Đây là hàm để xuất những file cần check lại lên gg drive. Flow như sau:
    # 1. lấy ds
    # 2. đọc folder_id từ GoogleDriveSetting()
    # 3. repo.find_one(run_id=ds) ← đọc từ MongoDB
    # 4. pd.DataFrame(result.summary["multi_address_df"]) nếu summary có dữ liệu export
    # 5. tạo file Excel tạm, export DataFrame vào đó
    # 6. upload lên Google Drive
    # 7. xóa file tạm
    # 8. return {"uploaded_file_id": ..., "run_id": ds}

    Returns:
        dict: _description_
    """
    ds = context["ds"]
    folder_id = GoogleDriveSetting().google_drive_export_folder_id

    repo = ProcessingResultRepository()
    result = repo.find_one(
        run_id = ds
    )
    if result is None:
        raise ValueError(f"Không tìm thấy kết quả cho run_id = {ds}")

    export_rows = result.summary.get("multi_address_df", [])
    if not export_rows:
        raise ValueError(
            "ProcessingResult hiện chỉ lưu result_id, run_id, summary, created_at; "
            f"không có dữ liệu multi_address_df để export cho run_id = {ds}"
        )

    df = pd.DataFrame(export_rows)

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = tmp.name
    df.to_excel(tmp_path, index=False)

    file_id = google_drive_service.upload_file(tmp_path, folder_id)
    os.remove(tmp_path)

    return {
        "uploaded_file_id": file_id,
        "run_id": ds
    }




