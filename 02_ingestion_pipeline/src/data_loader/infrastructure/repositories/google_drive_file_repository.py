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