"""PostgreSQL repository cho ProcessingResult."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from shared.domain.processing_result import ProcessingResult
from shared.infrastructure.postgres.base_repository import BasePostgresRepository

_DDL = """
CREATE TABLE IF NOT EXISTS processing_results (
    id               SERIAL PRIMARY KEY,
    run_id           VARCHAR(100) UNIQUE NOT NULL,
    summary          JSONB        NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
"""


class ProcessingResultPgRepository(BasePostgresRepository[ProcessingResult]):
    """Repository lưu ProcessingResult vào PostgreSQL."""

    table_name = "processing_results"

    def __init__(self):
        super().__init__()
        self.create_table_if_not_exists(_DDL)

    # ── Mapping ───────────────────────────────────────────────────────────────

    def _from_row(self, row: dict) -> ProcessingResult:
        return ProcessingResult(
            result_id=str(row.get("id")) if row.get("id") is not None else None,
            run_id=str(row["run_id"]),
            summary=row.get("summary") or {},
            created_at=row.get("created_at") or datetime.now(timezone.utc),
        )

    def _to_row(self, result: ProcessingResult) -> dict:
        return {
            "run_id": result.run_id,
            "summary": json.dumps(result.summary),
            "created_at": result.created_at,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def upsert_by_run_id(self, result: ProcessingResult) -> ProcessingResult:
        """Insert hoặc update theo run_id."""
        row = self._to_row(result)
        saved = self.upsert(row, conflict_columns=["run_id"])
        return self._from_row(saved)

    def find_by_run_id(self, run_id: str) -> ProcessingResult | None:
        """Tìm kết quả theo run_id."""
        rows = self.execute_raw(
            f"SELECT * FROM {self.table_name} WHERE run_id = %s LIMIT 1",
            (run_id,),
        )
        return self._from_row(rows[0]) if rows else None
