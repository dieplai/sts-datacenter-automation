"""DAG: dag_ingest — Complete ingestion pipeline as a single Airflow task.

Chạy toàn bộ pipeline (download → process → save to MongoDB) trong 1 task duy nhất.
So sánh với dag_pipeline.py (3 tasks riêng biệt):
    dag_ingest   → đơn giản hơn, 1 task, không cần XCom giữa các bước
    dag_pipeline → linh hoạt hơn, retry/monitor từng bước độc lập

Params (truyền khi trigger):
    source     : nguồn dữ liệu — "google_drive" | "s3" | "api"
    dest_path  : thư mục local lưu file tải về
    run_id     : (optional) định danh run, mặc định là execution_date
    folder_id  : (google_drive) id của folder chứa file cần tải
    file_id    : (google_drive) id của file cụ thể — để trống nếu dùng folder_id
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

try:
    from .wrapper.google_drive_sensor import GoogleDriveSensor
    from .wrapper.pipeline_wrapper import wrap_ingest_pipeline, wrap_send_summary_email
    from .utils.notifications import build_gmail_failure_callback
except ImportError:
    from wrapper.google_drive_sensor import GoogleDriveSensor
    from wrapper.pipeline_wrapper import wrap_ingest_pipeline, wrap_send_summary_email
    from utils.notifications import build_gmail_failure_callback

failure_callback = build_gmail_failure_callback()

with DAG(
    dag_id="dag_ingest",
    schedule="@daily",
    start_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
    catchup=False,
    on_failure_callback=failure_callback,
    params={
        "source": "google_drive",
        "dest_path": "/tmp/sts_data_ingestion/",
        "run_id": "",      # để trống → dùng execution_date
        "folder_id": "1O80UyeZUXugNk3QI1IASX2PWWoBfVO82",
        "file_id": "",     # để trống nếu dùng folder_id
    },
    tags=["sts", "ingest"],
) as dag:
    wait_for_google_drive_files = GoogleDriveSensor(
        task_id="wait_for_google_drive_files",
        folder_id="{{ params.folder_id }}",
        execution_date="{{ logical_date.strftime('%Y-%m-%d') }}",
        poke_interval=60,
        timeout=60 * 30,
        mode="reschedule",
    )

    run_ingest_pipeline_task = PythonOperator(
        task_id="run_ingest_pipeline",
        python_callable=wrap_ingest_pipeline,
        on_failure_callback=failure_callback,
    )

    send_summary_email_task = PythonOperator(
        task_id="send_summary_email",
        python_callable=wrap_send_summary_email,
    )

    wait_for_google_drive_files >> run_ingest_pipeline_task >> send_summary_email_task


if __name__ == "__main__":
    dag.test()
