"""Google Drive file model."""

from datetime import datetime, timezone

from shared.domain import BaseFileModel, FileSource
from pydantic import Field
from typing import Optional

from shared.domain.base_model import CustomBaseModel
from shared.utils.logging import info, log_error


class GoogleDriveFile(BaseFileModel):
    """FileModel for Google Drive sources."""

    original: FileSource = Field(
        default=FileSource.GOOGLE_DRIVE, description="File source"
    )
    drive_file_id: str = Field(..., description="Google Drive internal file ID")
    mime_type: str = Field(..., description="File MIME type")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")

    @classmethod
    def _to_model(cls, doc: dict) -> "GoogleDriveFile":
        """Mapping google drive file from dict -> GoogleDriveFileModel """

        info(f"Start _to_model with doc: {doc}")

        # --- drive_file_id ---
        _drive_file_id = doc.get("id", None)

        if _drive_file_id is None:
            _drive_file_id = doc.get("drive_file_id")

        if _drive_file_id is None:
            log_error(f"drive_file_id is missing in doc: {doc}")

        # --- created_time ---
        created_time:str = doc.get("createdTime", None)

        try:
            date_create_str = created_time.replace("+00:00", "Z")
        except Exception as e:
            raise
        # --- file_id ---(mongo id)
        temp_id = doc.get("_id", None)
        _id:str = None
        if _id != None:
            _id = str(temp_id)
        # --- size ---
        size = doc.get("size", doc.get("size_bytes"))
        info(f"Step 3 - raw size: {size}" )
        try:
            size_bytes = int(size) if size is not None else None
        except Exception as e:
            log_error(f"Invalid size value: {size}")
            size_bytes = None

        # --- mime type ---
        mime_type = doc.get("mimeType", doc.get("mime_type", ""))

        # --- download status ---
        download_status = doc.get("download_status", "pending")

        try:
            model = GoogleDriveFile(
                file_id=_id,
                name=doc["name"],
                date_create=date_create_str,
                date_download=doc.get("date_download"),
                dest_path=doc.get("dest_path", None),
                original=doc.get("original", "google_drive"),
                drive_file_id=_drive_file_id,
                mime_type=mime_type,
                size_bytes=size_bytes,
                download_status=download_status,
            )
            return model

        except Exception as e:
            log_error(f"Failed to build GoogleDriveFile: {e} | doc={doc}")
            raise

    def _to_doc(self) -> dict:
        """Map a GoogleDriveFile model into a persistence document."""
        doc = {
            "name": self.name,
            "date_create": self.date_create,
            "date_download": self.date_download,
            "dest_path": self.dest_path,
            "original": self.original.value,
            "drive_file_id": self.drive_file_id,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "download_status": self.download_status,
        }

        # chỉ set _id khi có giá trị
        if self.file_id is not None:
            doc["_id"] = self.file_id

        return doc