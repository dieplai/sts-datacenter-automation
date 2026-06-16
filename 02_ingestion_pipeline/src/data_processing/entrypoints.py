"""Data Processing application entry-points."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_processing.domain.models import ProcessedData, ProcessingStatus


def _to_file_dict(file_info: Any) -> dict:
    """Normalize DataLoader DownloadResponse/dict/object into processing file dict."""
    if hasattr(file_info, "_to_doc"):
        file_data = file_info._to_doc()
    elif hasattr(file_info, "model_dump"):
        file_data = file_info.model_dump()
    elif isinstance(file_info, dict):
        file_data = dict(file_info)
    else:
        file_data = vars(file_info)

    file_id = file_data.get("file_id") or file_data.get("id", "")
    local_path = file_data.get("local_path") or file_data.get("file_path", "")

    return {
        **file_data,
        "file_id": file_id,
        "local_path": local_path,
        "file_path": local_path,
    }


def run_data_processing(
    files: list[Any],
    execution_date: str,
) -> dict:
    """
    Entry-point for Data Processing.
    Pure Python — does not know about Airflow or any framework.

    Args:
        files: List of file dictionaries from DataLoader (must contain 'file_id', 'local_path')
        execution_date: Execution date string (YYYY-MM-DD)
        use_minimal_pipeline: If True, use minimal pipeline instead of default

    Returns:
        Result dictionary with processing statistics
    """
    try:
        from data_processing.application.pipeline_factory import build_hscode_pipeline

        hs_code_pipeline = build_hscode_pipeline()
        from shared.utils.logging import info
        info(f"Starting data processing @ {execution_date}")
        info(f"Files to process: {len(files)}")
        info(f"Pipeline: {hs_code_pipeline}")

        results = []
        errors = []
        success_count = 0
        failed_count = 0
        processed_frames = []
        need_check_frames = []
        processing_step_summary = {}

        # Process each file
        for i, file_info in enumerate(files, 1):
            try:
                file_data = _to_file_dict(file_info)
                file_id = file_data.get("file_id") or f"file_{i}"
                local_path = file_data.get("local_path", "")

                from shared.utils.logging import log_progress
                log_progress(i, len(files), f"Processing {file_id}")

                initial_data = ProcessedData(
                    file_id=file_id,
                    structured_data={
                        "file_path": local_path,
                        "local_path": local_path,
                        "execution_date": execution_date,
                        "loader_file": file_data,
                    },
                    processed_at=datetime.now(),
                    status=ProcessingStatus.PROCESSING,
                )

                # Run through pipeline
                processed_data = hs_code_pipeline.handle(initial_data)
                structured_data = processed_data.structured_data
                source_file_name = (
                    file_data.get("name")
                    or Path(local_path).name
                    or file_id
                )
                dataframe = structured_data.get("dataframe")
                if isinstance(dataframe, pd.DataFrame):
                    dataframe = dataframe.copy()
                    dataframe["source_file_id"] = file_id
                    dataframe["source_file_name"] = source_file_name
                    processed_frames.append(dataframe)

                need_check_dataframe = structured_data.get("saving_export_dataframe")
                if isinstance(need_check_dataframe, pd.DataFrame):
                    need_check_dataframe = need_check_dataframe.copy()
                    need_check_dataframe["source_file_id"] = file_id
                    need_check_dataframe["source_file_name"] = source_file_name
                    need_check_frames.append(need_check_dataframe)

                processing_step_summary[file_id] = structured_data.get(
                    "processing_step",
                    {},
                )

                results.append(
                    {
                        "file_id": file_id,
                        "local_path": local_path,
                        "status": processed_data.status.value,
                        "is_valid": processed_data.is_valid,
                        "word_count": processed_data.structured_data.get("word_count", 0),
                        "processing_steps": processed_data.processing_steps,
                        "saving_result": processed_data.structured_data.get(
                            "saving_result",
                            {},
                        ),
                        "errors": processed_data.errors,
                    }
                )

                if processed_data.is_valid:
                    success_count += 1
                else:
                    failed_count += 1

                from shared.utils.logging import log_success
                log_success(f"Processed {file_id}: {processed_data.status.value}")

            except Exception as e:
                error_msg = f"Failed to process file: {str(e)}"
                errors.append(error_msg)
                failed_count += 1
                file_data = _to_file_dict(file_info)
                results.append(
                    {
                        "file_id": file_data.get("file_id") or f"file_{i}",
                        "local_path": file_data.get("local_path", ""),
                        "status": ProcessingStatus.FAILED.value,
                        "error": str(e),
                    }
                )
                from shared.utils.logging import log_error
                log_error(error_msg)

        from shared.utils.logging import log_success, warning
        log_success("Data processing completed")
        info(f"Successful: {success_count}/{len(files)}")
        if errors:
            warning(f"Failed: {failed_count}")

        structured_result = {
            "dataframe": (
                pd.concat(processed_frames, ignore_index=True)
                if processed_frames
                else pd.DataFrame()
            ),
            "saving_export_dataframe": (
                pd.concat(need_check_frames, ignore_index=True)
                if need_check_frames
                else pd.DataFrame()
            ),
            "processing_step": processing_step_summary,
        }

        return {
            "status": "success" if not errors else "partial",
            "success": success_count,
            "failed": failed_count,
            "total": len(files),
            "files": results,
            "errors": errors,
            "structured_data": structured_result,
        }

    except Exception as e:
        error_msg = f"Data processor failed: {str(e)}"
        from shared.utils.logging import log_error
        log_error(error_msg)
        return {
            "status": "failed",
            "error": error_msg,
            "success": 0,
            "failed": 0,
            "total": 0,
            "files": [],
            "errors": [error_msg],
        }
