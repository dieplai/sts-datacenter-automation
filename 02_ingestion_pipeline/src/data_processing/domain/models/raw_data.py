"""Raw data model."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class RawData(BaseModel):
    """Model representing raw data before processing."""

    file_id: str = Field(..., description="Unique file identifier")
    source: str = Field(..., description="Data source type")
    local_path: str = Field(..., description="Local file path")
    content: Optional[bytes] = Field(default=None, description="File content")
    metadata: dict = Field(default_factory=dict, description="Source metadata")
    received_at: datetime = Field(..., description="Timestamp when data was received")

    class Config:
        arbitrary_types_allowed = True
