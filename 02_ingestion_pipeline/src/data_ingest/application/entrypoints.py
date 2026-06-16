"""Data Ingest application entry-points."""

from data_ingest.application.ingest_service import IngestService
from data_loader.application.entrypoints import run_data_loader
from data_processing.entrypoints import run_data_processing
from shared.utils.logging import info

# Global service instance
_ingest_service = IngestService()


def run_data_ingest(
    run_id: str,
    execution_date: str,
    source: str,
    dest_path: str,
    **kwargs,
) -> dict:
    """
    Entry-point for complete data ingestion pipeline.
    Pure Python — does not know about Airflow or any framework.

    Args:
        run_id: Unique run identifier
        execution_date: Execution date (YYYY-MM-DD)
        source: Source type (google_drive, s3, api)
        dest_path: Local destination directory
        **kwargs: Source-specific parameters forwarded to the data loader
            (e.g. source_path, file_id, folder_name, headers).

    Returns:
        Dictionary with ingestion results
    """
    record = _ingest_service.run(
        run_id=run_id,
        execution_date=execution_date,
        source=source,
        dest_path=dest_path,
        **kwargs,
    )

    return {
        "run_id": record.run_id,
        "status": record.status.value,
        "files_total": record.files_total,
        "files_done": record.files_done,
        "files_failed": record.files_failed,
        "error": record.error_message,
    }


def get_ingest_service() -> IngestService:
    """Get the global IngestService instance."""
    return _ingest_service


def _download_response_to_file(response: object) -> dict:
    """Convert DataLoader DownloadResponse-like object to DataProcessing file dict."""
    if hasattr(response, "_to_doc"):
        return response._to_doc()

    if hasattr(response, "model_dump"):
        response_data = response.model_dump()
    elif isinstance(response, dict):
        response_data = response
    else:
        response_data = vars(response)

    file_id = response_data.get("file_id") or response_data.get("id", "")
    return {
        **response_data,
        "file_id": file_id,
        "local_path": response_data.get("local_path", ""),
    }


def ingest_pipeline(
    run_id: str,
    execution_date: str,
    source: str,
    dest_path: str,
    **kwargs,
) -> dict:
    """
    Run data loader, then pass downloaded files into data processing.

    Args:
        run_id: Unique run identifier.
        execution_date: Execution date (YYYY-MM-DD).
        source: Source type (google_drive, s3, api).
        dest_path: Local destination directory.
        **kwargs: Source-specific params for data loader.

    Returns:
        Dict containing loader result, processing result, and summary status.
    """
    info(f"INGEST PIPELINE RUN: {run_id}")
    info("STEP 1: DATA LOADER")
    load_result = run_data_loader(
        source=source,
        execution_date=execution_date,
        dest_path=dest_path,
        **kwargs,
    )

    files = [_download_response_to_file(response) for response in load_result]

    info("STEP 2: DATA PROCESSING")
    process_result = run_data_processing(
        files=files,
        execution_date=execution_date,
    )

    return {
        "run_id": run_id,
        "status": process_result.get("status", "failed"),
        "loader": {
            "total": len(load_result),
            "files": files,
        },
        "processing": process_result,
    }


def ingest_pipline(
    run_id: str,
    execution_date: str,
    source: str,
    dest_path: str,
    **kwargs,
) -> dict:
    """Backward-compatible alias for the requested ingest_pipline name."""
    return ingest_pipeline(
        run_id=run_id,
        execution_date=execution_date,
        source=source,
        dest_path=dest_path,
        **kwargs,
    )


if __name__ == "__main__":
    request: dict = {
        "file_id": "1xy0tqimy2gM1-0-3ST0jHZLhstW9p9Ys",
    }
    result = ingest_pipline(
        run_id="test_001",
        execution_date="2026-05-03",
        source="google_drive",
        dest_path="/Users/apple/Main/project/sts/STSDataIngestion/tests/data",
        **request,
    )

    info(f"Status: {result['status']}")
    info(
        "Files processed: "
        f"{result['processing'].get('success', 0)}/{result['processing'].get('total', 0)}"
    )

    