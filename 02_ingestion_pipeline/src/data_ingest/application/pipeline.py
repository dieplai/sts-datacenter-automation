"""Complete data ingestion pipeline orchestrator.

Coordinates three sequential steps:
    1. DATA LOADING   — download files from source via data_loader
    2. DATA PROCESSING — process files via data_processing
    3. SAVE RESULTS   — persist processing output to MongoDB (shared.ProcessingResult)

Usage (pure Python, no Airflow needed):
    from data_ingest.application.pipeline import run_ingest_pipeline

    record = run_ingest_pipeline(
        run_id="2026-05-27",
        execution_date="2026-05-27",
        source="google_drive",
        dest_path="/tmp/sts/",
        file_id="<google_drive_file_id>",
    )
    print(record.status)  # IngestionStatus.DONE

The Airflow DAG wrapper (dags/wrapper/pipeline_wrapper.wrap_ingest_pipeline)
calls this function directly and pushes the resulting IngestionRecord to XCom.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_ingest.domain.models import IngestionRecord, IngestionStatus
from data_loader.application import run_data_loader
from data_processing.application import run_data_processing
from shared.domain.processing_result import ProcessingResult
from shared.infrastructure.mongo.repositories.processing_result_repository import (
    ProcessingResultRepository,
)
from shared.infrastructure.postgres.repositories import (
    ProcessingResultPgRepository,
    HsRawDataPgRepository,
)
from shared.utils.logging import info, log_error, log_success


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _responses_to_file_dicts(responses: list) -> list[dict]:
    """Convert DownloadResponse objects to plain dicts expected by data_processing."""
    files: list[dict] = []
    for r in responses:
        if hasattr(r, "model_dump"):
            files.append(r.model_dump())
        elif hasattr(r, "_to_doc"):
            files.append(r._to_doc())
        elif isinstance(r, dict):
            files.append(r)
        else:
            files.append(vars(r))
    return files


def _to_records(df_or_list) -> list[dict]:
    """Normalize a DataFrame or list to list[dict] for MongoDB storage."""
    if df_or_list is None:
        return []
    if hasattr(df_or_list, "to_dict"):
        return df_or_list.to_dict(orient="records")
    if isinstance(df_or_list, list):
        return df_or_list
    return []


def _build_file_handling_status(
    mongo_result: ProcessingResult,
    result_rows: list[dict[str, Any]],
    process_result: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build per-file handling status from the saved Mongo ProcessingResult."""
    process_files_by_name: dict[str, dict[str, Any]] = {}
    for file_result in process_result.get("files", []):
        local_path = file_result.get("local_path", "")
        filename = file_result.get("name") or Path(local_path).name or file_result.get("file_id")
        if not filename:
            continue
        process_files_by_name[str(filename)] = file_result

    rows_by_filename: dict[str, list[dict[str, Any]]] = {}
    for row in result_rows:
        filename = (
            row.get("source_file_name")
            or row.get("file_name")
            or row.get("filename")
        )
        if not filename:
            continue
        rows_by_filename.setdefault(str(filename), []).append(row)

    file_names = sorted(set(process_files_by_name) | set(rows_by_filename))
    file_status: dict[str, dict[str, Any]] = {}
    for filename in file_names:
        file_result = process_files_by_name.get(filename, {})
        rows = rows_by_filename.get(filename, [])
        file_id = (
            file_result.get("file_id")
            or file_result.get("id")
            or next((row.get("source_file_id") for row in rows if row.get("source_file_id")), None)
        )
        summary = {}
        if isinstance(mongo_result.summary, dict):
            summary = (
                mongo_result.summary.get(str(file_id), {})
                or mongo_result.summary.get(filename, {})
            )

        file_status[filename] = {
            "mongo_file_id": mongo_result.result_id,
            "run_id": mongo_result.run_id,
            "file_id": file_id,
            "local_path": file_result.get("local_path"),
            "status": file_result.get("status", "success" if rows else "unknown"),
            "is_valid": file_result.get("is_valid"),
            "rows_inserted": len(rows),
            "need_check_rows": sum(1 for row in rows if row.get("need_check") == 1),
            "summary": summary,
        }

    return file_status


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def run_ingest_pipeline(
    run_id: str,
    execution_date: str,
    source: str,
    dest_path: str,
    **kwargs,
) -> IngestionRecord:
    """Execute the full ingestion pipeline and persist results to MongoDB.

    Args:
        run_id:          Unique run identifier (also used as key in MongoDB).
                         Defaults to execution_date when not provided explicitly.
        execution_date:  Execution date string (YYYY-MM-DD).
        source:          Data source type — "google_drive" | "s3" | "api".
        dest_path:       Local directory to save downloaded files.
        **kwargs:        Source-specific params forwarded to data_loader
                         (e.g. file_id, folder_id, headers, source_path).

    Returns:
        IngestionRecord with final status, file counts, and any error details.
        Status is IngestionStatus.DONE on success, IngestionStatus.FAILED on error.
    """
    record = IngestionRecord(
        run_id=run_id,
        execution_date=execution_date,
        source=source,
        source_path=kwargs.get("source_path", ""),
        status=IngestionStatus.LOADING,
        started_at=datetime.now(timezone.utc),
    )

    info("=" * 60)
    info(f"INGEST PIPELINE START  run_id={run_id}  date={execution_date}")
    info("=" * 60)

    try:
        # ── Step 1: Download files ───────────────────────────────────────────
        info("STEP 1 — DATA LOADING")
        info("-" * 60)

        load_responses = run_data_loader(
            source=source,
            execution_date=execution_date,
            dest_path=dest_path,
            **kwargs,
        )
        files = _responses_to_file_dicts(load_responses)

        record = record.model_copy(
            update={
                "status": IngestionStatus.PROCESSING,
                "files_total": len(files),
            }
        )
        info(f"Downloaded {len(files)} file(s)")

        # ── Step 2: Process files ────────────────────────────────────────────
        info("STEP 2 — DATA PROCESSING")
        info("-" * 60)

        process_result = run_data_processing(
            files=files,
            execution_date=execution_date,
        )

        # ── Step 3: Persist to MongoDB ───────────────────────────────────────
        info("STEP 3 — SAVING RESULTS")
        info("-" * 60)

        structured = process_result.get("structured_data", {})
        processed_records = _to_records(structured.get("dataframe"))
        mongo_result = ProcessingResult(
            run_id=execution_date,
            summary=structured.get("processing_step", {}),
        )
        processing_result_repo = ProcessingResultRepository()
        processing_result_repo.upsert_by_run_id(mongo_result)

        saved_mongo_result = processing_result_repo.find_one(run_id=execution_date)
        mongo_file_id = saved_mongo_result.result_id if saved_mongo_result else None
        if mongo_file_id:
            info(f"Mongo ProcessingResult saved  mongo_file_id={mongo_file_id}")
            mongo_result_by_id = processing_result_repo.find_one(id=mongo_file_id)
            if mongo_result_by_id:
                mongo_result = mongo_result_by_id
                info(
                    "Loaded ProcessingResult from Mongo by mongo_file_id="
                    f"{mongo_file_id}"
                )
            else:
                info(
                    "ProcessingResult not found when loading by "
                    f"mongo_file_id={mongo_file_id}; using in-memory result"
                )
        else:
            info("Mongo ProcessingResult saved but mongo_file_id was not found")

        # ── Step 4: Persist to PostgreSQL ───────────────────────────────────
        info("STEP 4 — SAVING RESULTS TO POSTGRESQL")
        info("-" * 60)

        pg_records = [
            {
                **row,
                "data_source": source,
                "mongo_file_id": mongo_file_id,
            }
            for row in processed_records
        ]
        HsRawDataPgRepository().bulk_insert(pg_records)

        # ── Finalize record ──────────────────────────────────────────────────
        file_handling_status = _build_file_handling_status(
            mongo_result=mongo_result,
            result_rows=processed_records,
            process_result=process_result,
        )
        final_record = record.model_copy(
            update={
                "status": IngestionStatus.DONE,
                "files_done": process_result.get("success", 0),
                "files_failed": process_result.get("failed", 0),
                "completed_at": datetime.now(timezone.utc),
                "metadata": {
                    "rows_inserted": len(processed_records),
                    "need_check_rows": sum(
                        1 for r in processed_records if r.get("need_check") == 1
                    ),
                    "mongo_file_id": mongo_file_id,
                    "summary": mongo_result.summary,
                    "file_handling_status": file_handling_status,
                },
            }
        )

        log_success(f"INGEST PIPELINE COMPLETED  run_id={run_id}")
        info("=" * 60)
        return final_record

    except Exception as exc:
        failed_record = record.model_copy(
            update={
                "status": IngestionStatus.FAILED,
                "error_message": str(exc),
                "completed_at": datetime.now(timezone.utc),
            }
        )
        log_error(f"INGEST PIPELINE FAILED  run_id={run_id}: {exc}")
        info("=" * 60)
        return failed_record
