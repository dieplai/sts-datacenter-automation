""" Đây là pipeline_wrapper, nhằm là cầu nối giữa DAG và các nghiệp vụ trong
/src


"""


from __future__ import annotations
import os
import sys
from datetime import date, datetime
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))


from data_loader.application.entrypoints import run_data_loader
from data_processing.entrypoints import run_data_processing
from data_ingest.application.pipeline import run_ingest_pipeline
from shared.domain.processing_result import ProcessingResult
from shared.infrastructure.mongo.repositories.processing_result_repository import ProcessingResultRepository


def _push_failure_error(context: dict[str, Any], error: object) -> None:
    failure_error = str(error)
    context["failure_error"] = failure_error

    task_instance = context.get("ti") or context.get("task_instance")
    if task_instance is not None:
        task_instance.xcom_push(key="failure_error", value=failure_error)


def _raise_if_processing_failed(result: dict[str, Any]) -> None:
    status = str(result.get("status", "")).lower()
    failed_count = int(result.get("failed") or 0)
    errors = result.get("errors") or []

    if status in {"failed", "partial", "error"} or failed_count > 0:
        message = (
            "Data processing failed "
            f"(status={status or 'unknown'}, failed={failed_count})"
        )
        if errors:
            message = f"{message}: {'; '.join(str(error) for error in errors)}"
        raise RuntimeError(message)

def wrap_download_files(**context) -> list[dict]:
    """Hàm này để gọi tới run_data_loader, để download các file về, chưa trong 1 list, đẩy lên XCom cho hàm sau xử lý
    Vì run_data_loader cần 4 tham số: source (nguồn tải), execution_date(ngày chạy), dest_path(đường dẫn tới), **kwargs (keyword argument). Lấy ra 4 tham số đó như code ở dưới

    Returns:
        list[dict]: sẽ đẩy lên XCom để xử lý tiếp
    """
    ds = context.get("ds") or str(date.today())
    params = context["params"]

    source, dest_path = params["source"], params["dest_path"]

    source_kwargs = {k: v for k, v in params.items() if k not in ("source", "dest_path")}

    response = run_data_loader(
        source = source,
        execution_date = ds,
        dest_path = dest_path,
        **source_kwargs
    )

    return [r.model_dump() for r in response]

def wrap_run_pipeline(**context) -> dict:
    """ Hàm này để gọi run_data_processing. Tương tự cần truyền vào 2 tham số. Một danh sách files đã được download, và execution_date. Tương tự

    Pull danh sách download của loader từ XCom về để xử lý

    Returns:
        dict: _description_
    """
    ds = context.get("ds") or str(date.today())
    ti = context["ti"]

    download_file = ti.xcom_pull(task_ids="download_files") or []

    try:
        result = run_data_processing(
            files = download_file,
            execution_date = ds)
        _raise_if_processing_failed(result)
        return result
    except Exception as exc:
        _push_failure_error(context, exc)
        raise

def _to_records(df_or_list) -> list[dict]:
    """Convert DataFrame hoặc list[dict] sang list[dict] để lưu MongoDB.

    MongoDB và XCom chỉ lưu được JSON, không lưu được DataFrame.
    Hàm này xử lý 3 trường hợp: None, DataFrame, list[dict].
    """

    if df_or_list is None: return []
    if hasattr(df_or_list, "to_dict"): return df_or_list.to_dict(orient = "records")
    if isinstance(df_or_list, list): return df_or_list
    return []

def wrap_save_result(**context) -> None:
    """Lưu kết quả pipeline vào MongoDB để dag_export đọc lại sau.

    Pull dict kết quả từ task run_pipeline qua XCom, tạo ProcessingResult
    rồi upsert vào MongoDB theo run_id = execution_date.

    dag_export sẽ dùng run_id này để tìm lại đúng kết quả khi export.

    Returns:
        None — task này không push XCom.
    """

    ds = context.get("ds") or str(date.today())
    ti = context["ti"]

    processing_result = ti.xcom_pull(task_ids = "run_pipeline") or {}
    structured = processing_result.get("structured_data", {})

    result = ProcessingResult(
        run_id = ds,
        summary = structured.get("processing_step", {})
    )

    repo = ProcessingResultRepository()
    repo.upsert_by_run_id(result)


def wrap_ingest_pipeline(**context) -> dict:
    """Single-task Airflow wrapper cho toàn bộ ingest pipeline.

    Thay thế cho chuỗi 3 tasks (download_files → run_pipeline → save_result)
    bằng 1 task duy nhất. Phù hợp khi không cần retry riêng từng bước.

    Flow bên trong:
        Step 1 — run_data_loader   (download files từ source)
        Step 2 — run_data_processing (xử lý files đã download)
        Step 3 — upsert ProcessingResult vào MongoDB

    Context params:
        source     : nguồn dữ liệu (google_drive | s3 | api)
        dest_path  : thư mục local để lưu file tải về
        run_id     : (optional) id cho run, mặc định là execution_date
        **rest     : forwarded thẳng tới data_loader (vd: file_id, folder_id)

    Returns:
        dict: IngestionRecord.model_dump() — đẩy lên XCom cho task sau nếu cần.
    """
    ds = context.get("ds") or str(date.today())
    params = context["params"]

    source = params["source"]
    dest_path = params["dest_path"]
    run_id = params.get("run_id") or ds

    source_kwargs = {
        k: v for k, v in params.items()
        if k not in ("source", "dest_path", "run_id")
    }

    try:
        record = run_ingest_pipeline(
            run_id=run_id,
            execution_date=ds,
            source=source,
            dest_path=dest_path,
            **source_kwargs,
        )

        status = str(getattr(record.status, "value", record.status)).lower()
        files_failed = int(record.files_failed or 0)
        if status in {"failed", "error"} or files_failed > 0:
            error_message = record.error_message or (
                "Ingest pipeline failed "
                f"(status={status or 'unknown'}, files_failed={files_failed})"
            )
            raise RuntimeError(error_message)

        return record.model_dump()
    except Exception as exc:
        _push_failure_error(context, exc)
        raise


def wrap_send_summary_email(**context) -> None:
    """Gửi email tóm tắt kết quả pipeline sau khi run_ingest_pipeline hoàn thành.

    Pull kết quả từ XCom của task run_ingest_pipeline, đọc recipients từ
    Airflow Variable 'pipeline_summary_email' (fallback: 'failure_email'),
    build HTML rồi gửi qua Airflow send_email.
    """
    from html import escape

    from airflow.models import Variable
    from airflow.utils.email import send_email

    ti = context["ti"]
    ds = context.get("ds") or str(date.today())
    sent_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    record_dict = ti.xcom_pull(task_ids="run_ingest_pipeline") or {}

    run_id = record_dict.get("run_id", ds)
    status = record_dict.get("status", "unknown")
    files_total = record_dict.get("files_total", 0)
    files_done = record_dict.get("files_done", 0)
    files_failed = record_dict.get("files_failed", 0)
    meta = record_dict.get("metadata", {})
    rows_inserted = meta.get("rows_inserted", "N/A")
    need_check_rows = meta.get("need_check_rows", "N/A")
    mongo_file_id = meta.get("mongo_file_id")
    file_handling_status = meta.get("file_handling_status", {})
    mongo_rows = rows_inserted
    mongo_need_check_rows = need_check_rows
    mongo_lookup_error = None

    try:
        mongo_result = None
        repo = ProcessingResultRepository()
        if mongo_file_id:
            mongo_result = repo.find_one(id=mongo_file_id)
        if mongo_result is None:
            mongo_result = repo.find_one(run_id=run_id)

        if mongo_result is not None:
            mongo_file_id = mongo_result.result_id or mongo_file_id
    except Exception as exc:
        mongo_lookup_error = str(exc)

    # ── Recipients ────────────────────────────────────────────────────────
    default_recipients = "khoinm0603@gmail.com"
    recipients_raw = Variable.get(
        "pipeline_summary_email",
        default_var=Variable.get("failure_email", default_var=default_recipients),
    )
    recipients = [r.strip() for r in recipients_raw.replace(";", ",").split(",") if r.strip()]

    # ── HTML builders (inline để không phụ thuộc notifications.py) ───────
    def _cell(v) -> str:
        return "N/A" if v is None else escape(str(v))

    def _table(rows: list) -> str:
        trs = "".join(
            "<tr>"
            '<td style="width:200px;padding:10px 12px;border-bottom:1px solid #e2e8f0;'
            'background:#f8fafc;color:#475569;font-size:13px;font-weight:700;">'
            f"{_cell(label)}</td>"
            '<td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;'
            'color:#0f172a;font-size:13px;">'
            f"{_cell(value)}</td>"
            "</tr>"
            for label, value in rows
        )
        return (
            '<table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;'
            'border-radius:8px;overflow:hidden;background:#ffffff;">'
            f"<tbody>{trs}</tbody></table>"
        )

    def _badge(value: str) -> str:
        normalized = str(value or "unknown").lower()
        color = "#16a34a"
        bg = "#dcfce7"
        border = "#86efac"
        if normalized in {"failed", "error"}:
            color = "#b91c1c"
            bg = "#fee2e2"
            border = "#fecaca"
        elif normalized in {"processing", "running", "unknown"}:
            color = "#b45309"
            bg = "#fef3c7"
            border = "#fde68a"

        return (
            f'<span style="display:inline-block;padding:4px 9px;border-radius:999px;'
            f'background:{bg};border:1px solid {border};color:{color};'
            f'font-size:12px;font-weight:700;">{_cell(value)}</span>'
        )

    def _metric(label: str, value) -> str:
        return (
            '<div style="display:inline-block;min-width:120px;margin:0 8px 8px 0;'
            'padding:10px 12px;background:#f8fafc;border:1px solid #e2e8f0;'
            'border-radius:8px;">'
            f'<div style="font-size:11px;color:#64748b;text-transform:uppercase;'
            f'font-weight:700;">{_cell(label)}</div>'
            f'<div style="font-size:18px;color:#0f172a;font-weight:800;margin-top:2px;">'
            f'{_cell(value)}</div></div>'
        )

    def _render_missing_warning(missing_warning: dict) -> str:
        if not isinstance(missing_warning, dict) or not missing_warning:
            return ""

        rows = []
        for col_name, item in missing_warning.items():
            item = item if isinstance(item, dict) else {}
            missing_ratio = item.get("missing_value", 0)
            try:
                missing_ratio = f"{float(missing_ratio) * 100:.2f}%"
            except (TypeError, ValueError):
                missing_ratio = _cell(missing_ratio)
            rows.append(
                "<tr>"
                '<td style="padding:8px 10px;border-bottom:1px solid #fee2e2;'
                'font-size:12px;color:#7f1d1d;font-weight:700;">'
                f"{_cell(item.get('col_name') or col_name)}</td>"
                '<td style="padding:8px 10px;border-bottom:1px solid #fee2e2;'
                'font-size:12px;color:#7f1d1d;text-align:right;">'
                f"{_cell(item.get('missing_count'))}</td>"
                '<td style="padding:8px 10px;border-bottom:1px solid #fee2e2;'
                'font-size:12px;color:#7f1d1d;text-align:right;">'
                f"{_cell(item.get('total'))}</td>"
                '<td style="padding:8px 10px;border-bottom:1px solid #fee2e2;'
                'font-size:12px;color:#7f1d1d;text-align:right;font-weight:700;">'
                f"{missing_ratio}</td>"
                "</tr>"
            )

        return (
            '<div style="margin-top:12px;background:#fff7ed;border:1px solid #fed7aa;'
            'border-radius:8px;overflow:hidden;">'
            '<div style="padding:9px 11px;color:#9a3412;font-size:12px;'
            'font-weight:800;background:#ffedd5;">Missing Value Warning</div>'
            '<table style="width:100%;border-collapse:collapse;">'
            '<thead><tr>'
            '<th style="padding:8px 10px;text-align:left;color:#9a3412;font-size:11px;">Column</th>'
            '<th style="padding:8px 10px;text-align:right;color:#9a3412;font-size:11px;">Missing</th>'
            '<th style="padding:8px 10px;text-align:right;color:#9a3412;font-size:11px;">Total</th>'
            '<th style="padding:8px 10px;text-align:right;color:#9a3412;font-size:11px;">Ratio</th>'
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )

    def _render_file_handling_status(status_map: dict) -> str:
        if not isinstance(status_map, dict) or not status_map:
            return (
                '<div style="padding:12px;border:1px dashed #cbd5e1;border-radius:8px;'
                'color:#64748b;font-size:13px;background:#f8fafc;">No file handling status.</div>'
            )

        cards = []
        for filename, detail in status_map.items():
            detail = detail if isinstance(detail, dict) else {}
            summary = detail.get("summary", {})
            summary = summary if isinstance(summary, dict) else {}
            saving = summary.get("saving_handler", {})
            saving = saving if isinstance(saving, dict) else {}
            validation = summary.get("validation_handler", {})
            validation = validation if isinstance(validation, dict) else {}

            cards.append(
                '<div style="border:1px solid #dbeafe;background:#ffffff;border-radius:10px;'
                'overflow:hidden;margin-bottom:14px;">'
                '<div style="padding:14px 16px;background:#eff6ff;border-bottom:1px solid #dbeafe;">'
                '<div style="font-size:13px;color:#1e40af;font-weight:800;word-break:break-word;">'
                f"{_cell(filename)}</div>"
                '<div style="margin-top:8px;">'
                f"{_badge(detail.get('status'))}"
                f'<span style="display:inline-block;margin-left:8px;color:#475569;font-size:12px;">'
                f"File ID: {_cell(detail.get('file_id'))}</span>"
                "</div></div>"
                '<div style="padding:14px 16px;">'
                + _metric("Rows", detail.get("rows_inserted", 0))
                + _metric("Need Check", detail.get("need_check_rows", 0))
                + _metric("Valid", detail.get("is_valid"))
                + _table([
                    ("Mongo File ID", detail.get("mongo_file_id")),
                    ("Local Path", detail.get("local_path")),
                    ("Saving Total Rows", saving.get("total_rows")),
                    ("Validation Status", validation.get("status")),
                ])
                + _render_missing_warning(validation.get("missing_value_warning", {}))
                + "</div></div>"
            )

        return "".join(cards)

    status_color = "#16a34a" if status == "done" else "#b91c1c"
    status_label = status.upper()

    html_content = (
        '<div style="font-family:Arial,Helvetica,sans-serif;line-height:1.45;'
        'color:#0f172a;background:#f8fafc;padding:24px;">'
        '<div style="max-width:860px;margin:0 auto;">'
        # header
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:22px 24px;margin-bottom:16px;">'
        '<div style="font-size:13px;color:#64748b;margin-bottom:4px;">Airflow — Pipeline Summary</div>'
        '<h1 style="font-size:24px;margin:0;color:#0f172a;">Data Ingestion Report</h1>'
        f'<div style="display:inline-block;margin-top:12px;padding:5px 10px;border-radius:999px;'
        f'border:1px solid {status_color};color:{status_color};font-size:12px;font-weight:700;">'
        f"{status_label}</div></div>"
        # run info
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:18px 20px;margin-bottom:16px;">'
        '<h2 style="font-size:16px;margin:0 0 12px;color:#0f172a;">Run Info</h2>'
        + _table([
            ("Run ID", run_id),
            ("Execution Date", sent_at),
            ("Status", status),
        ])
        + "</div>"
        # file stats
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:18px 20px;margin-bottom:16px;">'
        '<h2 style="font-size:16px;margin:0 0 12px;color:#0f172a;">File Stats</h2>'
        + _table([
            ("Files Found", files_total),
            ("Files Processed", files_done),
            ("Files Failed", files_failed),
        ])
        + "</div>"
        # data stats
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:18px 20px;margin-bottom:16px;">'
        '<h2 style="font-size:16px;margin:0 0 12px;color:#0f172a;">Data Stats</h2>'
        + _table([
            ("Rows Inserted", rows_inserted),
            ("Rows Need Check", need_check_rows),
        ])
        + "</div>"
        # mongo result
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:18px 20px;margin-bottom:16px;">'
        '<h2 style="font-size:16px;margin:0 0 12px;color:#0f172a;">Mongo Result</h2>'
        + _table([
            ("Mongo File ID", mongo_file_id or "N/A"),
            ("Mongo Rows", mongo_rows),
            ("Mongo Need Check Rows", mongo_need_check_rows),
        ])
        + "</div>"
        # file handling status
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:18px 20px;margin-bottom:16px;">'
        '<h2 style="font-size:16px;margin:0 0 12px;color:#0f172a;">File Handling Status</h2>'
        + (
            '<div style="padding:10px 12px;border:1px solid #fecaca;background:#fef2f2;'
            'border-radius:8px;color:#991b1b;font-size:13px;margin-bottom:12px;">'
            f"Mongo lookup error: {_cell(mongo_lookup_error)}</div>"
            if mongo_lookup_error
            else ""
        )
        + _render_file_handling_status(file_handling_status)
        + "</div>"
        '<div style="font-size:12px;color:#64748b;margin-top:12px;">'
        "Generated by Airflow DAG dag_ingest.</div>"
        "</div></div>"
    )

    send_email(
        to=recipients,
        subject=f"[Airflow] dag_ingest — {ds}",
        html_content=html_content,
    )
