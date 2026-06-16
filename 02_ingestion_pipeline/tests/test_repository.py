"""Tests for the FileRepository contract."""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from data_loader.domain.ports.file_repository import FileRepository
from shared.domain import BaseFileModel, FileSource


class FakeFileRepository:
    """In-memory implementation used to validate repository behavior."""

    def __init__(self):
        self._items: dict[str, BaseFileModel] = {}

    def save(self, file: BaseFileModel) -> str:
        self._items[file.file_id] = file
        return file.file_id

    def find_by_id(self, file_id: str) -> BaseFileModel | None:
        return self._items.get(file_id)

    def find_all(self) -> list[BaseFileModel]:
        return list(self._items.values())

    def find_by_source(self, source: str) -> list[BaseFileModel]:
        return [item for item in self._items.values() if item.original.value == source]

    def delete_by_id(self, file_id: str) -> bool:
        return self._items.pop(file_id, None) is not None


def build_file(file_id: str, source: FileSource = FileSource.GOOGLE_DRIVE) -> BaseFileModel:
    return BaseFileModel(
        file_id=file_id,
        name=f"{file_id}.txt",
        date_create=datetime.fromisoformat("2024-01-01T00:00:00"),
        original=source,
    )


class TestFileRepositoryContract:
    """Behavior checks for implementations following FileRepository."""

    def test_fake_repository_implements_required_interface(self):
        repo: FileRepository = FakeFileRepository()

        assert callable(repo.save)
        assert callable(repo.find_by_id)
        assert callable(repo.find_all)
        assert callable(repo.find_by_source)
        assert callable(repo.delete_by_id)

    def test_save_and_find_by_id(self):
        repo: FileRepository = FakeFileRepository()
        file = build_file("file_1")

        saved_id = repo.save(file)
        found = repo.find_by_id("file_1")

        assert saved_id == "file_1"
        assert found == file

    def test_find_all_returns_all_saved_files(self):
        repo: FileRepository = FakeFileRepository()
        file_1 = build_file("file_1", FileSource.GOOGLE_DRIVE)
        file_2 = build_file("file_2", FileSource.S3)

        repo.save(file_1)
        repo.save(file_2)

        results = repo.find_all()

        assert len(results) == 2
        assert file_1 in results
        assert file_2 in results

    def test_find_by_source_filters_correctly(self):
        repo: FileRepository = FakeFileRepository()
        drive_file = build_file("file_1", FileSource.GOOGLE_DRIVE)
        s3_file = build_file("file_2", FileSource.S3)

        repo.save(drive_file)
        repo.save(s3_file)

        results = repo.find_by_source("google_drive")

        assert results == [drive_file]

    def test_delete_by_id_removes_file(self):
        repo: FileRepository = FakeFileRepository()
        file = build_file("file_1")
        repo.save(file)

        deleted = repo.delete_by_id("file_1")
        found = repo.find_by_id("file_1")

        assert deleted is True
        assert found is None

    def test_delete_by_id_returns_false_when_file_missing(self):
        repo: FileRepository = FakeFileRepository()

        deleted = repo.delete_by_id("missing_file")

        assert deleted is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
