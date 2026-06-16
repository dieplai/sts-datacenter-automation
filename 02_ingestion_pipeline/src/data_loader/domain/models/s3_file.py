"""S3 file model."""

from shared.domain import BaseFileModel, FileSource
from pydantic import Field
from typing import Optional


class S3File(BaseFileModel):
    """FileModel for AWS S3 sources."""

    original: FileSource = Field(default=FileSource.S3, description="File source")
    bucket: str = Field(..., description="S3 bucket name")
    key: str = Field(..., description="S3 object key (path)")
    etag: Optional[str] = Field(default=None, description="S3 ETag (MD5 hash)")
    storage_class: str = Field(default="STANDARD", description="S3 storage class")
    region: str = Field(default="ap-southeast-1", description="AWS region")
