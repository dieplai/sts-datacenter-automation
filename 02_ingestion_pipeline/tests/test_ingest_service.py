"""Unit tests for DataIngest components."""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from data_ingest.domain.models import IngestionRecord, IngestionStatus
from data_ingest.application.ingest_service import IngestService


class TestIngestionRecord:
    """Tests for IngestionRecord aggregate."""

    def test_create_record(self):
        """Test creating an IngestionRecord."""
        record = IngestionRecord(
            run_id="run_123",
            execution_date="2024-01-15",
            source="google_drive",
            source_path="folder_id",
        )

        assert record.run_id == "run_123"
        assert record.status == IngestionStatus.PENDING
        assert record.files_total == 0

    def test_update_record(self):
        """Test updating a record."""
        record = IngestionRecord(
            run_id="run_123",
            execution_date="2024-01-15",
            source="google_drive",
            source_path="folder_id",
        )

        updated = record.model_copy(
            update={
                "status": IngestionStatus.DONE,
                "files_done": 5,
                "files_total": 5,
            }
        )

        assert updated.status == IngestionStatus.DONE
        assert updated.files_done == 5


class TestIngestService:
    """Tests for IngestService."""

    def test_service_creation(self):
        """Test creating IngestService."""
        service = IngestService()
        assert service is not None

    def test_get_record(self):
        """Test retrieving records."""
        service = IngestService()
        record = IngestionRecord(
            run_id="test_run",
            execution_date="2024-01-15",
            source="test",
            source_path="path",
        )

        # Manually store record (normally done by run())
        service._records["test_run"] = record

        retrieved = service.get_record("test_run")
        assert retrieved is not None
        assert retrieved.run_id == "test_run"

    def test_list_records(self):
        """Test listing all records."""
        service = IngestService()

        for i in range(3):
            record = IngestionRecord(
                run_id=f"run_{i}",
                execution_date="2024-01-15",
                source="test",
                source_path="path",
            )
            service._records[f"run_{i}"] = record

        records = service.list_records()
        assert len(records) == 3

    def test_get_stats(self):
        """Test getting service statistics."""
        service = IngestService()

        # Add some records
        for i in range(2):
            record = IngestionRecord(
                run_id=f"run_{i}",
                execution_date="2024-01-15",
                source="test",
                source_path="path",
                status=IngestionStatus.DONE,
                files_total=10,
                files_done=10,
            )
            service._records[f"run_{i}"] = record

        stats = service.get_stats()
        assert stats["total_runs"] == 2
        assert stats["successful_runs"] == 2
        assert stats["total_files"] == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
