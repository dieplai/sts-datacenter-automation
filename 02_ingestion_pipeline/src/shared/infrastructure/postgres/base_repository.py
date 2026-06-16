"""Base PostgreSQL repository với generic CRUD operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from shared.infrastructure.postgres.client import PostgresClient

T = TypeVar("T")


class BasePostgresRepository(ABC, Generic[T]):
    """
    Base repository cho PostgreSQL.
    Subclass cần khai báo:
        table_name  : tên bảng (str)
        _from_row() : convert RealDictRow → domain model

    Ví dụ:
        class BuyerRepository(BasePostgresRepository[Buyer]):
            table_name = "buyers"

            def _from_row(self, row: dict) -> Buyer:
                return Buyer(**row)
    """

    table_name: str

    def __init__(self):
        self._client = PostgresClient()

    # ── Abstract ──────────────────────────────────────────────────────────────

    @abstractmethod
    def _from_row(self, row: dict) -> T:
        """Convert một DB row (dict) thành domain model."""
        ...

    # ── Generic CRUD ──────────────────────────────────────────────────────────

    def find_all(self) -> list[T]:
        """Lấy tất cả records trong bảng."""
        with self._client.cursor() as cur:
            cur.execute(f"SELECT * FROM {self.table_name}")
            rows = cur.fetchall()
        return [self._from_row(dict(r)) for r in rows]

    def find_by_id(self, id: Any) -> T | None:
        """Tìm 1 record theo primary key `id`."""
        with self._client.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {self.table_name} WHERE id = %s LIMIT 1", (id,)
            )
            row = cur.fetchone()
        return self._from_row(dict(row)) if row else None

    def insert(self, data: dict) -> dict:
        """Insert 1 record, trả về row đã insert (với id được DB sinh ra)."""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        sql = (
            f"INSERT INTO {self.table_name} ({columns}) "
            f"VALUES ({placeholders}) RETURNING *"
        )
        with self._client.cursor() as cur:
            cur.execute(sql, list(data.values()))
            row = cur.fetchone()
        return dict(row)

    def upsert(self, data: dict, conflict_columns: list[str]) -> dict:
        """
        Insert hoặc update nếu conflict.

        Args:
            data             : dict column→value cần upsert
            conflict_columns : danh sách cột làm unique key
                               (vd: ["run_id"] hoặc ["buyer_name", "country"])
        """
        columns = list(data.keys())
        col_str = ", ".join(columns)
        placeholder_str = ", ".join(["%s"] * len(columns))
        conflict_str = ", ".join(conflict_columns)

        update_parts = [
            f"{col} = EXCLUDED.{col}"
            for col in columns
            if col not in conflict_columns
        ]
        update_str = ", ".join(update_parts) if update_parts else f"{columns[0]} = EXCLUDED.{columns[0]}"

        sql = (
            f"INSERT INTO {self.table_name} ({col_str}) "
            f"VALUES ({placeholder_str}) "
            f"ON CONFLICT ({conflict_str}) DO UPDATE SET {update_str} "
            f"RETURNING *"
        )
        with self._client.cursor() as cur:
            cur.execute(sql, list(data.values()))
            row = cur.fetchone()
        return dict(row)

    def delete_by_id(self, id: Any) -> bool:
        """Xoá record theo id, trả về True nếu có row bị xoá."""
        with self._client.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self.table_name} WHERE id = %s", (id,)
            )
            return cur.rowcount > 0

    def execute_raw(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        """Chạy câu SQL tuỳ ý, trả về list[dict]."""
        with self._client.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
        return [dict(r) for r in rows]

    def create_table_if_not_exists(self, ddl: str) -> None:
        """Chạy DDL tạo bảng nếu chưa tồn tại."""
        with self._client.cursor() as cur:
            cur.execute(ddl)
