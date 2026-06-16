"""Unit tests for data loader entrypoints."""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from data_loader.application import entrypoints
from data_loader.domain.models.google_drive_file import GoogleDriveFile


TEST_FILE_ID = "1s65CZOPLT-WMGxbxMTKXl72aIBf14Kqn"
TEST_DEST_PATH = "/test/data"
TEST_EXECUTION_DATE = "2024-01-15"


def ensure(condition: bool, message: str) -> None:
    """Fail the test by raising an exception when a condition is false."""
    if not condition:
        raise RuntimeError(message)


def build_google_drive_file(
    file_id: str,
    name: str = "report.csv",
    mime_type: str = "text/csv",
) -> GoogleDriveFile:
    return GoogleDriveFile(
        file_id=file_id,
        name=name,
        date_create=datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
        original="google_drive",
        drive_file_id=file_id,
        mime_type=mime_type,
        parent_folder=None,
        size_bytes=128,
    )


class FakeDispatcher:
    """Test double for FileDispatcher."""

    def __init__(
        self,
        files: list[GoogleDriveFile] | None = None,
        download_outputs: dict[str, str] | None = None,
        list_error: Exception | None = None,
        download_errors: dict[str, Exception] | None = None,
    ):
        self.files = files or []
        self.download_outputs = download_outputs or {}
        self.list_error = list_error
        self.download_errors = download_errors or {}
        self.registered_sources: list[str] = []
        self.list_calls: list[dict] = []
        self.download_calls: list[dict] = []

    def register(self, source, downloader) -> None:
        self.registered_sources.append(source.value)

    def list_files(self, source, **kwargs):
        self.list_calls.append({"source": source.value, "kwargs": kwargs})
        if self.list_error is not None:
            raise self.list_error
        return self.files

    def download(self, file, dest_path: str, **kwargs) -> str:
        self.download_calls.append(
            {"file_id": file.file_id, "dest_path": dest_path, "kwargs": kwargs}
        )
        if file.file_id in self.download_errors:
            raise self.download_errors[file.file_id]
        return self.download_outputs.get(file.file_id, f"{dest_path}/{file.name}")


class FakeRepository:
    """Test double for GoogleDriveFileRepository."""

    def __init__(self, save_errors: dict[str, Exception] | None = None):
        self.save_errors = save_errors or {}
        self.saved_files: list[GoogleDriveFile] = []

    def save(self, file) -> str:
        if file.file_id in self.save_errors:
            raise self.save_errors[file.file_id]
        self.saved_files.append(file)
        return file.file_id


class DummyDownloader:
    """Placeholder downloader for dependency wiring."""


def patch_loader_dependencies(monkeypatch, dispatcher: FakeDispatcher, repo: FakeRepository) -> None:
    monkeypatch.setattr(entrypoints, "FileDispatcher", lambda: dispatcher)
    monkeypatch.setattr(entrypoints, "GoogleDriveFileRepository", lambda: repo)
    monkeypatch.setattr(entrypoints, "GoogleDriveDownloader", DummyDownloader)
    monkeypatch.setattr(entrypoints, "S3Downloader", DummyDownloader)
    monkeypatch.setattr(entrypoints, "ApiDownloader", DummyDownloader)


def test_run_data_loader_success_single_google_drive_file(monkeypatch):
    file = build_google_drive_file(TEST_FILE_ID)
    dispatcher = FakeDispatcher(
        files=[file],
        download_outputs={TEST_FILE_ID: f"{TEST_DEST_PATH}/report.csv"},
    )
    repo = FakeRepository()
    patch_loader_dependencies(monkeypatch, dispatcher, repo)

    result = entrypoints.run_data_loader(
        source="google_drive",
        execution_date=TEST_EXECUTION_DATE,
        dest_path=TEST_DEST_PATH,
        file_id=TEST_FILE_ID,
    )

    ensure(result["status"] == "success", "Expected success status for single file")
    ensure(result["downloaded"] == 1, "Expected one successful download")
    ensure(result["failed"] == 0, "Expected zero failed downloads")
    ensure(result["total"] == 1, "Expected total files to be one")
    ensure(len(result["files"]) == 1, "Expected one result item")
    ensure(result["files"][0]["local_path"] == f"{TEST_DEST_PATH}/report.csv", "Unexpected local path")
    ensure(dispatcher.list_calls[0]["source"] == "google_drive", "Expected google_drive source")
    ensure(
        dispatcher.list_calls[0]["kwargs"]["file_id"] == TEST_FILE_ID,
        "Expected exact file_id to be forwarded to list_files",
    )
    ensure(
        dispatcher.download_calls[0]["dest_path"] == TEST_DEST_PATH,
        "Expected exact dest_path to be forwarded to download",
    )
    ensure(len(repo.saved_files) == 1, "Expected one file saved to repository")
    ensure(repo.saved_files[0].dest_path == f"{TEST_DEST_PATH}/report.csv", "Repository saved wrong path")
    ensure(
        repo.saved_files[0].date_download == datetime.fromisoformat(TEST_EXECUTION_DATE),
        "Repository saved wrong download time",
    )


def test_run_data_loader_success_with_empty_file_list(monkeypatch):
    dispatcher = FakeDispatcher(files=[])
    repo = FakeRepository()
    patch_loader_dependencies(monkeypatch, dispatcher, repo)

    result = entrypoints.run_data_loader(
        source="google_drive",
        execution_date=TEST_EXECUTION_DATE,
        dest_path=TEST_DEST_PATH,
        file_id=TEST_FILE_ID,
    )

    ensure(result["status"] == "success", "Expected success status for empty file list")
    ensure(result["downloaded"] == 0, "Expected zero successful downloads")
    ensure(result["failed"] == 0, "Expected zero failed downloads")
    ensure(result["total"] == 0, "Expected zero total files")
    ensure(len(result["files"]) == 0, "Expected no file results")
    ensure(len(repo.saved_files) == 0, "Expected repository to stay empty")


def test_run_data_loader_partial_when_one_download_fails(monkeypatch):
    file_1 = build_google_drive_file(TEST_FILE_ID, "report.csv")
    file_2 = build_google_drive_file("file-2", "broken.csv")
    dispatcher = FakeDispatcher(
        files=[file_1, file_2],
        download_outputs={TEST_FILE_ID: f"{TEST_DEST_PATH}/report.csv"},
        download_errors={"file-2": RuntimeError("download exploded")},
    )
    repo = FakeRepository()
    patch_loader_dependencies(monkeypatch, dispatcher, repo)

    result = entrypoints.run_data_loader(
        source="google_drive",
        execution_date=TEST_EXECUTION_DATE,
        dest_path=TEST_DEST_PATH,
        file_id=TEST_FILE_ID,
    )

    ensure(result["status"] == "partial", "Expected partial status when one download fails")
    ensure(result["downloaded"] == 1, "Expected one successful download")
    ensure(result["failed"] == 1, "Expected one failed download")
    ensure(result["total"] == 2, "Expected total files to be two")
    ensure(len(result["errors"]) == 1, "Expected one collected error")
    ensure("download exploded" in result["errors"][0], "Expected original download error message")
    ensure(len(repo.saved_files) == 1, "Expected only successful file to be saved")
    ensure(repo.saved_files[0].file_id == TEST_FILE_ID, "Expected only the successful file in repository")


def test_run_data_loader_partial_when_repository_save_fails(monkeypatch):
    file = build_google_drive_file(TEST_FILE_ID)
    dispatcher = FakeDispatcher(
        files=[file],
        download_outputs={TEST_FILE_ID: f"{TEST_DEST_PATH}/report.csv"},
    )
    repo = FakeRepository(save_errors={TEST_FILE_ID: RuntimeError("mongo unavailable")})
    patch_loader_dependencies(monkeypatch, dispatcher, repo)

    result = entrypoints.run_data_loader(
        source="google_drive",
        execution_date=TEST_EXECUTION_DATE,
        dest_path=TEST_DEST_PATH,
        file_id=TEST_FILE_ID,
    )

    ensure(result["status"] == "partial", "Expected partial status when repository save fails")
    ensure(result["downloaded"] == 0, "Expected zero completed downloads after save failure")
    ensure(result["failed"] == 1, "Expected one failed file")
    ensure(result["total"] == 1, "Expected total files to be one")
    ensure(len(result["errors"]) == 1, "Expected one repository error")
    ensure("mongo unavailable" in result["errors"][0], "Expected repository error message in result")
    ensure(len(repo.saved_files) == 0, "Expected repository save list to stay empty")


def test_run_data_loader_failed_when_listing_files_crashes(monkeypatch):
    dispatcher = FakeDispatcher(list_error=RuntimeError("list api crashed"))
    repo = FakeRepository()
    patch_loader_dependencies(monkeypatch, dispatcher, repo)

    result = entrypoints.run_data_loader(
        source="google_drive",
        execution_date=TEST_EXECUTION_DATE,
        dest_path=TEST_DEST_PATH,
        file_id=TEST_FILE_ID,
    )

    ensure(result["status"] == "failed", "Expected failed status when list_files crashes")
    ensure(result["downloaded"] == 0, "Expected zero successful downloads")
    ensure(result["failed"] == 0, "Expected loop not to start when listing fails")
    ensure(result["total"] == 0, "Expected zero total files on top-level failure")
    ensure(len(result["errors"]) == 1, "Expected one top-level error")
    ensure("list api crashed" in result["errors"][0], "Expected list_files error in response")


def test_run_data_loader_failed_when_source_is_invalid(monkeypatch):
    dispatcher = FakeDispatcher()
    repo = FakeRepository()
    patch_loader_dependencies(monkeypatch, dispatcher, repo)

    result = entrypoints.run_data_loader(
        source="not_supported",
        execution_date=TEST_EXECUTION_DATE,
        dest_path=TEST_DEST_PATH,
        file_id=TEST_FILE_ID,
    )

    ensure(result["status"] == "failed", "Expected failed status for invalid source")
    ensure(result["downloaded"] == 0, "Expected zero successful downloads")
    ensure(result["failed"] == 0, "Expected zero failed loop items")
    ensure(result["total"] == 0, "Expected zero total files")
    ensure(len(result["errors"]) == 1, "Expected one invalid-source error")
    ensure("not_supported" in result["errors"][0], "Expected invalid source value in error")
    ensure(len(dispatcher.list_calls) == 0, "Expected list_files not to be called for invalid source")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
