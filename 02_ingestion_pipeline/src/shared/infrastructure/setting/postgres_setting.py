"""PostgreSQL settings."""

from shared.infrastructure.setting.base_setting import AppBaseSetting


class PostgresSetting(AppBaseSetting):
    """Settings for PostgreSQL connection."""

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: str
    postgres_db: str = "data_ingestion"

    @property
    def connection_string(self) -> str:
        """Generate PostgreSQL connection string."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
