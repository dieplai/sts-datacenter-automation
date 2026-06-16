"""Ingestion record — Aggregate root for a complete ingestion run."""

from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class IngestionStatus(str, Enum):
    """Status of an ingestion run."""

    PENDING = "pending"
    LOADING = "loading"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class IngestionRecord(BaseModel):
    """
    Aggregate root for a complete ingestion run.
    Tracks the entire lifecycle from download → process → store.
    """

    run_id: str = Field(..., description="Unique run identifier")
    execution_date: str = Field(..., description="Execution date (YYYY-MM-DD)")
    source: str = Field(..., description="Data source type")
    source_path: str = Field(..., description="Source-specific path")
    status: IngestionStatus = Field(
        default=IngestionStatus.PENDING, description="Current status"
    )
    files_total: int = Field(default=0, description="Total files found")
    files_done: int = Field(default=0, description="Files successfully processed")
    files_failed: int = Field(default=0, description="Files that failed")
    started_at: datetime | None = Field(default=None, description="Start time")
    completed_at: datetime | None = Field(default=None, description="Completion time")
    error_message: str | None = Field(default=None, description="Error details if failed")
    metadata: dict = Field(
        default_factory=dict, description="Additional metadata"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}
