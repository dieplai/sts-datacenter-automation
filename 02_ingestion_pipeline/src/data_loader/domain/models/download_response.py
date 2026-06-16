"""Download response model containing file id, local path, and download status."""

from pydantic import Field

from shared.domain.base_file_model import FileDownloadStatus
from shared.domain.base_model import CustomBaseModel


class DownloadResponse(CustomBaseModel):
    """
    Response model returned from downloader.download() method.
    Contains file id, local path, and download status.
    """

    id: str = Field(..., description="File ID from database/source")
    local_path: str = Field(..., description="Local file path after download")
    file_download_status: FileDownloadStatus = Field(
        ..., description="Download status (SUCCESS, FAILED, etc.)"
    )

    @classmethod
    def _to_model(cls, doc: dict) -> "DownloadResponse":
        """Map a document dictionary into a DownloadResponse model."""
        return cls(
            id=doc.get("id", doc.get("file_id", "")),
            local_path=doc.get("local_path", ""),
            file_download_status=doc.get(
                "file_download_status",
                FileDownloadStatus.PENDING,
            ),
        )

    def _to_doc(self) -> dict:
        """Map the response model into a pipeline-friendly dictionary."""
        return {
            "id": self.id,
            "file_id": self.id,
            "local_path": self.local_path,
            "file_download_status": self.file_download_status.value,
        }

    class Config:
        json_schema_extra = {
            "example": {
                "id": "file_123",
                "local_path": "/tmp/downloaded_file.xlsx",
                "file_download_status": "success",
            }
        }
