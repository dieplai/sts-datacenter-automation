"""MongoDB implementation of the file metadata repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from bson import ObjectId
from data_loader.domain.models import ApiFile, GoogleDriveFile, S3File
from shared.domain import BaseFileModel, FileSource
from shared.domain.base_file_model import FileDownloadStatus
from shared.infrastructure.mongo.base_repository import BaseMongoRepository
from shared.utils.logging import info, log_error


class GoogleDriveFileRepository(BaseMongoRepository[GoogleDriveFile]):
    """MongoDB repository for storing file metadata."""

    COLLECTION_NAME = "file_collection"

    def __init__(self) -> None:
        super().__init__(
            model=GoogleDriveFile,
            collection_name=self.COLLECTION_NAME,
        )

    def upsert_by_drive_file_id(self, file_model: GoogleDriveFile) -> str | None:
        """Insert or update Google Drive file metadata by drive_file_id."""
        try:
            document = file_model._to_doc()
            document.pop("_id", None)
            result = self._get_collection().update_one(
                {"drive_file_id": file_model.drive_file_id},
                {"$set": document},
                upsert=True,
            )
            if result.upserted_id is not None:
                return str(result.upserted_id)

            existing = self._get_collection().find_one(
                {"drive_file_id": file_model.drive_file_id},
                {"_id": 1},
            )
            return str(existing["_id"]) if existing else None
        except Exception as exc:
            log_error(f"[GoogleDriveFile] upsert_by_drive_file_id failed: {exc}")
            return None
