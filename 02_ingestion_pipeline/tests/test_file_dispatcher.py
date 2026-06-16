"""Unit tests for DataLoader components."""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from shared.domain import FileSource
from data_loader.domain.models import GoogleDriveFile
from data_loader.domain.services import FileDispatcher


class MockDownloader:
    """Mock downloader for testing."""

    def __init__(self):
        self.last_download_kwargs: dict | None = None
        self.last_list_kwargs: dict | None = None

    def download(self, file, dest_path: str, **kwargs) -> str:
        self.last_download_kwargs = kwargs
        return dest_path

    def list_files(self, **kwargs):
        self.last_list_kwargs = kwargs
        return []


class TestFileDispatcher:
    """Tests for FileDispatcher (Registry pattern)."""

    def test_register_downloader(self):
        """Test registering a downloader."""
        dispatcher = FileDispatcher()
        downloader = MockDownloader()

        dispatcher.register(FileSource.GOOGLE_DRIVE, downloader)

        assert dispatcher.is_registered(FileSource.GOOGLE_DRIVE)

    def test_dispatch_file(self):
        """Test dispatching a file to registered handler."""
        dispatcher = FileDispatcher()
        downloader = MockDownloader()
        dispatcher.register(FileSource.GOOGLE_DRIVE, downloader)

        file = GoogleDriveFile(
            file_id="test_123",
            name="file.pdf",
            date_create=datetime.now(),
            drive_file_id="drive_id",
            mime_type="application/pdf",
        )

        result = dispatcher.download(file, "/tmp/file.pdf")
        assert result == "/tmp/file.pdf"

    def test_dispatch_unregistered_source(self):
        """Test that dispatch raises error for unregistered source."""
        dispatcher = FileDispatcher()

        file = GoogleDriveFile(
            file_id="test_123",
            name="file.pdf",
            date_create=datetime.now(),
            drive_file_id="drive_id",
            mime_type="application/pdf",
        )

        with pytest.raises(ValueError):
            dispatcher.download(file, "/tmp/file.pdf")

    def test_list_files(self):
        """Test listing files from source."""
        dispatcher = FileDispatcher()
        downloader = MockDownloader()
        dispatcher.register(FileSource.GOOGLE_DRIVE, downloader)

        files = dispatcher.list_files(FileSource.GOOGLE_DRIVE, folder_id="folder_id")
        assert isinstance(files, list)
        assert downloader.last_list_kwargs == {"folder_id": "folder_id"}

    def test_dispatch_forwards_kwargs(self):
        """Test that dispatch forwards **kwargs to the downloader."""
        dispatcher = FileDispatcher()
        downloader = MockDownloader()
        dispatcher.register(FileSource.GOOGLE_DRIVE, downloader)

        file = GoogleDriveFile(
            file_id="test_123",
            name="file.pdf",
            date_create=datetime.now(),
            drive_file_id="drive_id",
            mime_type="application/pdf",
        )

        dispatcher.download(file, "/tmp/file.pdf", headers={"X-Auth": "abc"})
        assert downloader.last_download_kwargs == {"headers": {"X-Auth": "abc"}}

    def test_get_registered_sources(self):
        """Test getting list of registered sources."""
        dispatcher = FileDispatcher()
        dispatcher.register(FileSource.GOOGLE_DRIVE, MockDownloader())
        dispatcher.register(FileSource.S3, MockDownloader())

        sources = dispatcher.get_registered_sources()
        assert "google_drive" in sources
        assert "s3" in sources


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
