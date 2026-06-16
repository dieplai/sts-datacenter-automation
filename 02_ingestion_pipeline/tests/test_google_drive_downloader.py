"""Unit tests for GoogleDriveDownloader."""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from data_loader.domain.models.google_drive_file import GoogleDriveFile
from data_loader.application.downloaders import google_drive_downloader as downloader_module
from data_loader.application.downloaders.google_drive_downloader import (
    GoogleDriveDownloader,
)


class FakeGoogleDriveService:
    """Fake Google Drive service for downloader tests."""

    def __init__(self):
        self.metadata_map = {
            "file-1": {
                "id": "file-1",
                "name": "report.csv",
                "mimeType": "text/csv",
                "createdTime": "2024-01-01T00:00:00Z",
                "parents": ["folder-root"],
                "size": "12",
            },
            "folder-1": {
                "id": "folder-1",
                "name": "dataset",
                "mimeType": "application/vnd.google-apps.folder",
                "createdTime": "2024-01-01T00:00:00Z",
                "parents": [],
            },
            "child-1": {
                "id": "child-1",
                "name": "part-1.json",
                "mimeType": "application/json",
                "createdTime": "2024-01-02T00:00:00Z",
                "parents": ["folder-1"],
                "size": "20",
            },
            "subfolder-1": {
                "id": "subfolder-1",
                "name": "nested",
                "mimeType": "application/vnd.google-apps.folder",
                "createdTime": "2024-01-03T00:00:00Z",
                "parents": ["folder-1"],
            },
            "nested-file-1": {
                "id": "nested-file-1",
                "name": "part-2.json",
                "mimeType": "application/json",
                "createdTime": "2024-01-04T00:00:00Z",
                "parents": ["subfolder-1"],
                "size": "24",
            },
            "fail-file": {
                "id": "fail-file",
                "name": "broken.txt",
                "mimeType": "text/plain",
                "createdTime": "2024-01-05T00:00:00Z",
                "parents": ["folder-root"],
                "size": "5",
            },
        }
        self.children_map = {
            "folder-1": [
                self.metadata_map["child-1"],
                self.metadata_map["subfolder-1"],
            ],
            "subfolder-1": [self.metadata_map["nested-file-1"]],
        }
        self.download_calls: list[tuple[str, str]] = []

    def get_file_metadata(self, file_id: str) -> dict:
        return self.metadata_map[file_id]

    def list_files(
        self, file_id: str | None = None, max_results: int = 100
    ) -> list[dict]:
        return self.children_map.get(file_id, [])

    def download_file(self, file_id: str, dest_path: str) -> str:
        if file_id == "fail-file":
            raise RuntimeError("simulated download failure")

        self.download_calls.append((file_id, dest_path))
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(dest_path).write_text(f"downloaded:{file_id}", encoding="utf-8")
        return dest_path


@pytest.fixture
def fake_service(monkeypatch) -> FakeGoogleDriveService:
    service = FakeGoogleDriveService()
    monkeypatch.setattr(downloader_module, "google_drive_service", service)
    return service


@pytest.fixture
def downloader() -> GoogleDriveDownloader:
    return GoogleDriveDownloader()


def build_file(file_id: str, name: str, mime_type: str) -> GoogleDriveFile:
    return GoogleDriveFile(
        file_id=file_id,
        name=name,
        date_create=datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
        original="google_drive",
        drive_file_id=file_id,
        mime_type=mime_type,
        parent_folder=None,
        size_bytes=None,
    )


def test_download_single_file_into_directory_path(
    downloader: GoogleDriveDownloader, fake_service: FakeGoogleDriveService, tmp_path: Path
):
    result = downloader.download(
        build_file("file-1", "report.csv", "text/csv"),
        str(tmp_path / "case_1") + "/",
    )

    expected = tmp_path / "case_1" / "report.csv"
    assert result == str(expected)
    assert expected.exists()
    assert expected.read_text(encoding="utf-8") == "downloaded:file-1"
    assert ("file-1", str(expected)) in fake_service.download_calls


def test_download_single_file_into_explicit_file_path(
    downloader: GoogleDriveDownloader, fake_service: FakeGoogleDriveService, tmp_path: Path
):
    expected = tmp_path / "case_2" / "renamed-output.csv"

    result = downloader.download(
        build_file("file-1", "report.csv", "text/csv"),
        str(expected),
    )

    assert result == str(expected)
    assert expected.exists()
    assert expected.read_text(encoding="utf-8") == "downloaded:file-1"
    assert ("file-1", str(expected)) in fake_service.download_calls


def test_download_folder_recursively(
    downloader: GoogleDriveDownloader, fake_service: FakeGoogleDriveService, tmp_path: Path
):
    result = downloader.download(
        build_file("folder-1", "dataset", "application/vnd.google-apps.folder"),
        str(tmp_path / "case_3"),
    )

    folder_root = tmp_path / "case_3" / "dataset"
    file_1 = folder_root / "part-1.json"
    file_2 = folder_root / "nested" / "part-2.json"

    assert result == str(folder_root)
    assert folder_root.is_dir()
    assert file_1.exists()
    assert file_2.exists()
    assert file_1.read_text(encoding="utf-8") == "downloaded:child-1"
    assert file_2.read_text(encoding="utf-8") == "downloaded:nested-file-1"
    assert ("child-1", str(file_1)) in fake_service.download_calls
    assert ("nested-file-1", str(file_2)) in fake_service.download_calls


def test_download_treats_extensionless_destination_as_directory(
    downloader: GoogleDriveDownloader, fake_service: FakeGoogleDriveService, tmp_path: Path
):
    result = downloader.download(
        build_file("file-1", "report.csv", "text/csv"),
        str(tmp_path / "case_4"),
    )

    expected = tmp_path / "case_4" / "report.csv"
    assert result == str(expected)
    assert expected.exists()
    assert ("file-1", str(expected)) in fake_service.download_calls


def test_download_propagates_service_error(
    downloader: GoogleDriveDownloader, fake_service: FakeGoogleDriveService, tmp_path: Path
):
    with pytest.raises(RuntimeError, match="simulated download failure"):
        downloader.download(
            build_file("fail-file", "broken.txt", "text/plain"),
            str(tmp_path / "case_5" / "broken.txt"),
        )

    assert fake_service.download_calls == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
