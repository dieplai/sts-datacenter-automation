"""Base file model for all file types in the system."""

from pydantic import Field
from datetime import datetime
from enum import Enum

from shared.domain.base_model import CustomBaseModel


class FileSource(str, Enum):
    """Enumeration of available file sources."""

    GOOGLE_DRIVE = "google_drive"
    S3 = "s3"
    API = "api"

class FileDownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    SUCCESS = "success"
    FAILED = "failed"    


class BaseFileModel(CustomBaseModel):
    """
    Base model for all file types in the system.
    Only uses Pydantic — does not import any infrastructure libraries.
    This is a Value Object with immutable behavior.
    """

    file_id: str | None = Field(default=None, description="Unique file identifier")
    name: str = Field(..., description="File name")
    date_create: datetime = Field(..., description="Creation date from source")
    date_download: datetime | None = Field(
        default=None, description="Download timestamp"
    )
    dest_path:str | None = Field(
        default= None, description="Local path"
    )
    original: FileSource = Field(..., description="Source of the file")
    download_status:FileDownloadStatus = FileDownloadStatus.PENDING
    class Config:
        frozen = True  # Immutable — Value Object behavior
        json_schema_extra = {
            "example": {
                "file_id": "file_123",
                "name": "document.pdf",
                "date_create": "2024-01-01T00:00:00",
                "date_download": "2024-01-02T12:30:00",
                "original": "google_drive",
            }
        }
