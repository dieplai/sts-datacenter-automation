"""Processed data model."""

from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from datetime import datetime
from enum import Enum


class ProcessingStatus(str, Enum):
    """Processing status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class ProcessedData(BaseModel):
    """Model representing data after processing pipeline."""

    file_id: str = Field(..., description="Unique file identifier")
    structured_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured processing payload and metadata",
    )

    processing_steps: list[dict] = Field(
        default_factory=list[dict], description="Audit trail of processing steps"
    )
    processed_at: datetime = Field(..., description="Processing completion time")
    status: ProcessingStatus = Field(
        default=ProcessingStatus.PENDING, description="Processing status"
    )
    is_valid: bool = Field(default=True, description="Whether data passed validation")
    errors: list[str] = Field(default_factory=list, description="Processing errors")

    @field_serializer("structured_data", when_used="json")
    def serialize_structured_data(self, value: dict[str, Any]) -> dict[str, Any]:
        """Convert nested DataFrames to JSON-safe records for Airflow XCom/API output."""
        return {
            key: self._serialize_value(item)
            for key, item in value.items()
        }

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, pd.DataFrame):
            return value.to_dict(orient="records")
        if isinstance(value, dict):
            return {
                key: ProcessedData._serialize_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [ProcessedData._serialize_value(item) for item in value]
        return value

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        json_encoders={
            datetime: lambda value: value.isoformat(),
            pd.DataFrame: lambda df: df.to_dict(orient="records"),
        },
    )
