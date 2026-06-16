"""Data Loader repositories."""

__all__ = ["GoogleDriveFileRepository"]


def __getattr__(name: str):
    if name == "GoogleDriveFileRepository":
        from shared.infrastructure.mongo.repositories.google_drive_file_repository import (
            GoogleDriveFileRepository,
        )

        return GoogleDriveFileRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
