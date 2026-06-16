"""DAG: send_email_dag — Test DAG để verify SMTP config gửi mail được không.

Trigger thủ công, gửi 1 email test tới địa chỉ cấu hình trong Airflow Variable
'pipeline_summary_email' (fallback: dangquockhanh2k5@gmail.com).

Dùng để kiểm tra:
    - SMTP config trong .env (AIRFLOW__SMTP__*) đã đúng chưa
    - Airflow Variable 'pipeline_summary_email' đã set chưa
    - Email có vào inbox không (check spam nếu không thấy)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))


def _send_test_email(**context) -> None:
    from airflow.models import Variable
    from airflow.utils.email import send_email

    ds = context["ds"]

    default_recipients = "khoinm0603@gmail.com"
    recipients_raw = Variable.get(
        "pipeline_summary_email",
        default_var=Variable.get("failure_email", default_var=default_recipients),
    )
    recipients = [r.strip() for r in recipients_raw.replace(";", ",").split(",") if r.strip()]

    html_content = (
        '<div style="font-family:Arial,Helvetica,sans-serif;padding:24px;background:#f8fafc;">'
        '<div style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;'
        'border-radius:10px;padding:24px;">'
        '<h2 style="color:#0f172a;margin-top:0;">Airflow SMTP Test</h2>'
        '<p style="color:#475569;">Email này xác nhận SMTP config đã hoạt động đúng.</p>'
        f'<p style="color:#64748b;font-size:13px;">Gửi lúc: {ds} — DAG: send_email_dag</p>'
        "</div></div>"
    )

    send_email(
        to=recipients,
        subject=f"[Airflow][TEST] SMTP Test — {ds}",
        html_content=html_content,
    )


with DAG(
    dag_id="send_email_dag",
    schedule=None,  # trigger thủ công
    start_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
    catchup=False,
    tags=["sts", "test", "email"],
) as dag:
    PythonOperator(
        task_id="send_test_email",
        python_callable=_send_test_email,
    )
