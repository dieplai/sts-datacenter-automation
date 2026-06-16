"""Unit tests for shared domain models."""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from shared.domain import BaseFileModel, FileSource
from data_loader.domain.models import GoogleDriveFile, S3File, ApiFile


class TestBaseFileModel:
    """Tests for BaseFileModel."""

    def test_base_file_model_creation(self):
        """Test creating a BaseFileModel."""
        file = BaseFileModel(
            file_id="test_123",
            name="document.pdf",
            date_create=datetime.now(),
            original=FileSource.GOOGLE_DRIVE,
        )
        assert file.file_id == "test_123"
        assert file.name == "document.pdf"
        assert file.original == FileSource.GOOGLE_DRIVE

    def test_base_file_model_immutability(self):
        """Test that BaseFileModel is immutable."""
        file = BaseFileModel(
            file_id="test_123",
            name="document.pdf",
            date_create=datetime.now(),
            original=FileSource.GOOGLE_DRIVE,
        )
        with pytest.raises(Exception):  # Frozen model should raise
            file.file_id = "new_id"


class TestGoogleDriveFile:
    """Tests for GoogleDriveFile model."""

    def test_google_drive_file_creation(self):
        """Test creating a GoogleDriveFile."""
        file = GoogleDriveFile(
            file_id="gd_123",
            name="sheet.csv",
            date_create=datetime.now(),
            drive_file_id="folder_abc",
            mime_type="text/csv",
        )
        assert file.file_id == "gd_123"
        assert file.original == FileSource.GOOGLE_DRIVE
        assert file.mime_type == "text/csv"


class TestS3File:
    """Tests for S3File model."""

    def test_s3_file_creation(self):
        """Test creating an S3File."""
        file = S3File(
            file_id="s3_123",
            name="data.json",
            date_create=datetime.now(),
            bucket="my-bucket",
            key="data/file.json",
        )
        assert file.file_id == "s3_123"
        assert file.original == FileSource.S3
        assert file.bucket == "my-bucket"


class TestApiFile:
    """Tests for ApiFile model."""

    def test_api_file_creation(self):
        """Test creating an ApiFile."""
        file = ApiFile(
            file_id="api_123",
            name="response.json",
            date_create=datetime.now(),
            endpoint_url="https://api.example.com/data",
            content_type="application/json",
        )
        assert file.file_id == "api_123"
        assert file.original == FileSource.API
        assert file.content_type == "application/json"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
