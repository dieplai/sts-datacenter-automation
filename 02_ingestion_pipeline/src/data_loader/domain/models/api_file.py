"""API file model."""

from shared.domain import BaseFileModel, FileSource
from pydantic import Field
from typing import Optional


class ApiFile(BaseFileModel):
    """FileModel for API/HTTP sources."""

    original: FileSource = Field(default=FileSource.API, description="File source")
    endpoint_url: str = Field(..., description="API endpoint URL")
    response_code: Optional[int] = Field(default=None, description="HTTP response code")
    content_type: Optional[str] = Field(default=None, description="Content-Type header")
    request_params: dict = Field(default_factory=dict, description="Request parameters")
