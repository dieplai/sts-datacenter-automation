"""MongoDB settings."""

from typing import Any

from shared.infrastructure.setting.base_setting import AppBaseSetting


class MongoSetting(AppBaseSetting):
    """Settings for MongoDB connection."""

    mongo_host: str
    mongo_port: int 
    mongo_db_name: str 
    mongo_timeout: int

    def build_client_kwargs(self) -> dict[str, Any]:
        """Build MongoClient keyword arguments from individual settings."""
        client_kwargs: dict[str, Any] = {
            "host": self.mongo_host,
            "port": self.mongo_port,
            "serverSelectionTimeoutMS": self.mongo_timeout,
        }

        return client_kwargs

