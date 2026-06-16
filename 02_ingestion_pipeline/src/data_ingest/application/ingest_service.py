"""Ingest service — Orchestrator for the complete pipeline."""

from data_ingest.domain.models import IngestionRecord, IngestionStatus
from shared.utils.logging import info

class IngestService:
    """
    Orchestrator service for the complete ingestion pipeline.
    Coordinates DataLoader and DataProcessing modules.
    Does not contain business logic — only orchestration.
    """

    def __init__(self):
        """Initialize the service with in-memory storage."""
        self._records: dict[str, IngestionRecord] = {}

    def run(
        self,
        run_id: str,
        execution_date: str,
        source: str,
        dest_path: str,
        mode: str = "skip",
        **kwargs,
    ) -> IngestionRecord:
        """
        Execute the full ingestion pipeline.

        Delegates to run_ingest_pipeline which coordinates:
            Step 1 — data_loader  (download files)
            Step 2 — data_processing (process files)
            Step 3 — MongoDB save  (persist ProcessingResult)

        Args:
            run_id: Unique run identifier
            execution_date: Execution date (YYYY-MM-DD)
            source: Source type (google_drive, s3, api)
            dest_path: Local destination directory
            mode: Data loader mode. Use "replace" to re-download and replace
                existing local files.
            **kwargs: Source-specific parameters forwarded to the data loader
                (e.g. source_path, file_id, folder_name, headers).

        Returns:
            IngestionRecord with final status
        """
        from data_ingest.application.pipeline import run_ingest_pipeline

        record = run_ingest_pipeline(
            run_id=run_id,
            execution_date=execution_date,
            source=source,
            dest_path=dest_path,
            mode=mode,
            **kwargs,
        )
        self._records[run_id] = record
        return record

    def get_record(self, run_id: str) -> IngestionRecord | None:
        """Get an ingestion record by run_id."""
        return self._records.get(run_id)

    def list_records(self) -> list[IngestionRecord]:
        """Get all ingestion records."""
        return list(self._records.values())

    def get_stats(self) -> dict:
        """Get statistics about all ingestion runs."""
        records = self._records.values()
        total_runs = len(records)
        successful = sum(1 for r in records if r.status == IngestionStatus.DONE)
        failed = sum(1 for r in records if r.status == IngestionStatus.FAILED)
        total_files = sum(r.files_total for r in records)
        processed_files = sum(r.files_done for r in records)

        return {
            "total_runs": total_runs,
            "successful_runs": successful,
            "failed_runs": failed,
            "total_files": total_files,
            "processed_files": processed_files,
            "success_rate": (successful / total_runs * 100) if total_runs > 0 else 0,
        }
