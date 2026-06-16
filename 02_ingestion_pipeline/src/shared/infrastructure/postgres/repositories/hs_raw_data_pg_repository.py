"""Repository for hs_raw_data table — bulk insert processed trade records."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import execute_values

from shared.infrastructure.postgres.base_repository import BasePostgresRepository
from shared.utils.logging import info, log_error

# Columns accepted by the table (excludes auto-generated: id, created_at, updated_at)
_TABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "declaration_number",
        "transaction_date",
        "hs_code",
        "product_description",
        "product_description_en",
        "supplier_name",
        "buyer_name",
        "quantity",
        "quantity_unit",
        "unit_price_usd",
        "unit_price_foreign_currency",
        "total_price_foreign_currency",
        "total_amount_usd",
        "exchange_rate",
        "incoterms",
        "payment_method",
        "import_country",
        "transport_mode",
        "country_of_origin",
        "customs_branch_code",
        "customs_branch_name",
        "bill_id",
        "buyer_country",
        "customs_branch_code_secondary",
        "date",
        "exporter_country",
        "foreign_currency",
        "importer_address_vn",
        "importer_name_en",
        "importer_tel",
        "import_type",
        "need_check",
        "data_source",
        "mongo_file_id",
    }
)


class HsRawDataPgRepository(BasePostgresRepository[dict]):
    table_name = "hs_raw_data"

    def _from_row(self, row: dict) -> dict:
        return row

    @staticmethod
    def _get_insert_columns(records: list[dict[str, Any]]) -> list[str]:
        all_keys: set[str] = set()
        for record in records:
            all_keys.update(k for k in record.keys() if k in _TABLE_COLUMNS)
        return sorted(all_keys)

    def _insert_records(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0

        columns = self._get_insert_columns(records)
        if not columns:
            log_error("[HsRawDataPgRepository] No valid columns found in records.")
            return 0

        col_str = ", ".join(columns)
        sql = f"INSERT INTO {self.table_name} ({col_str}) VALUES %s"
        values = [tuple(r.get(col) for col in columns) for r in records]

        with self._client.cursor() as cur:
            execute_values(cur, sql, values, page_size=500)

        return len(records)

    # ── Public API ─────────────────────────────────────────────────────────

    def bulk_insert(self, records: list[dict[str, Any]]) -> int:
        """Insert nhiều rows vào hs_raw_data, trả về số rows đã insert.

        - Chỉ lấy các key khớp với cột bảng (bỏ qua cột lạ).
        - Nếu records rỗng, không làm gì.
        """
        if not records:
            info("[HsRawDataPgRepository] No records to insert.")
            return 0

        inserted_count = self._insert_records(records)
        info(
            f"[HsRawDataPgRepository] Inserted {inserted_count} rows "
            f"into {self.table_name}."
        )
        return inserted_count

    def bulk_insert_with_run_id(self, records: list[dict[str, Any]], run_id: str) -> int:
        """Insert rows và đính kèm run_id vào mỗi row (nếu bảng có cột run_id).

        Hiện tại bảng hs_raw_data chưa có cột run_id nên gọi bulk_insert bình thường.
        """
        return self.bulk_insert(records)
