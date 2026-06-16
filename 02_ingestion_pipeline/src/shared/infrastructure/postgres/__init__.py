"""PostgreSQL infrastructure."""

from shared.infrastructure.postgres.client import PostgresClient, postgres_client
from shared.infrastructure.postgres.base_repository import BasePostgresRepository
from shared.infrastructure.postgres.repositories.processing_result_pg_repository import (
    ProcessingResultPgRepository,
)

__all__ = [
    "PostgresClient",
    "postgres_client",
    "BasePostgresRepository",
    "ProcessingResultPgRepository",
]
