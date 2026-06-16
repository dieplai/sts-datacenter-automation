"""PostgreSQL client singleton."""

from threading import Lock

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PgConnection

from shared.infrastructure.setting.postgres_setting import PostgresSetting
from shared.utils.logging import log_error, log_success


class PostgresClient:
    """
    Singleton PostgreSQL client.
    Quản lý connection lifecycle, cung cấp cursor cho repositories.

    Sử dụng:
        client = PostgresClient()
        with client.cursor() as cur:
            cur.execute("SELECT 1")
    """

    _instance: "PostgresClient | None" = None
    _conn: PgConnection | None = None
    _lock = Lock()

    def __new__(cls) -> "PostgresClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Khởi tạo PostgreSQL connection."""
        try:
            setting = PostgresSetting()
            self._conn = psycopg2.connect(
                host=setting.postgres_host,
                port=setting.postgres_port,
                user=setting.postgres_user,
                password=setting.postgres_password,
                dbname=setting.postgres_db,
                connect_timeout=10,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            self._conn.autocommit = False
            log_success(
                f"Connected to PostgreSQL successfully | DB: {setting.postgres_db}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to connect to PostgreSQL: {e}") from e

    @property
    def connection(self) -> PgConnection:
        """Trả về connection, tự reconnect nếu bị đứt."""
        if self._conn is None or self._conn.closed:
            self._initialize()
        return self._conn

    def cursor(self):
        """Context manager trả về cursor đã commit/rollback tự động."""
        return _CursorContext(self.connection)

    def close(self) -> None:
        """Đóng connection (dùng khi shutdown)."""
        if self._conn and not self._conn.closed:
            self._conn.close()
        PostgresClient._instance = None
        PostgresClient._conn = None


class _CursorContext:
    """Context manager cho psycopg2 cursor với auto commit/rollback."""

    def __init__(self, conn: PgConnection):
        self._conn = conn
        self._cur = None

    def __enter__(self):
        self._cur = self._conn.cursor()
        return self._cur

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
            log_error(f"PostgreSQL transaction rolled back: {exc_val}")
        self._cur.close()
        return False  # không suppress exception


# Module-level singleton — import trực tiếp khi cần
postgres_client = PostgresClient()
