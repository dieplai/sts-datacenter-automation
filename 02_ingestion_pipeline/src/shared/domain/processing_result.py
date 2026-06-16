from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

from pydantic import Field
from shared.domain.base_model import CustomBaseModel

class ProcessingResult(CustomBaseModel):
    result_id: str | None = Field(default = None)
    run_id: str = Field(...)
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def _to_model(cls, doc: dict[str, Any]) -> "ProcessingResult":
        return cls(
            result_id=str(doc.get("_id")) if doc.get("_id") is not None else None,
            run_id=str(doc.get("run_id", "")),
            summary=doc.get("summary", {}),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
        )

    def _to_doc(self) -> dict[str, Any]:
        document = {
            "run_id": self.run_id,
            "summary": self.summary,
            "created_at": self.created_at,
        }
        if self.result_id:
            document["_id"] = self.result_id
        return document