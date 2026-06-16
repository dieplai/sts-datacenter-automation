"""MongoDB client singleton."""

from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from shared.infrastructure.setting import MongoSetting
from shared.utils.logging import log_success
from threading import Lock

class MongoDBClient:
    """
    Singleton MongoDB client.
    Manages connection lifecycle and provides access to the database.
    """

    _instance: "MongoDBClient | None" = None
    _client: MongoClient | None = None
    _lock = Lock()

    def __new__(cls) -> "MongoDBClient":
        if cls._instance is None:  # double-check
            cls._instance = super().__new__(cls)
            cls._instance._initialize()

        return cls._instance

    def _initialize(self) -> None:
        """Initialize MongoDB connection."""
        try:
            setting = MongoSetting()
            self._client = MongoClient(**setting.build_client_kwargs())

            # 1. Verify connection
            self._client.admin.command("ping")

            # 2. Chọn DB (bạn phải có db_name trong setting)
            db_name = setting.mongo_db_name
            db = self._client[db_name]

            log_success(
                f"Connected to MongoDB successfully | DB: {db_name}"
            )

        except ServerSelectionTimeoutError as e:
            raise RuntimeError(f"Failed to connect to MongoDB: {e}")
    
    @property
    def client(self) -> MongoClient:
        """Get the MongoDB client instance."""
        if self._client is None:
            raise RuntimeError("MongoDB client not initialized")
        return self._client

    @property
    def db(self) -> "pymongo.database.Database":
        """Get the default database."""
        setting = MongoSetting()
        return self.client[setting.mongo_db_name]

    def close(self) -> None:
        """Close the MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            from shared.utils.logging import log_success
            log_success("Closed MongoDB connection")

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        if cls._instance and cls._instance._client:
            cls._instance.close()
        cls._instance = None



class MongoDBClientProxy:
    """Lazy proxy that initializes the Mongo client only on first use."""

    def __getattr__(self, name: str):
        return getattr(MongoDBClient(), name)

    def close(self) -> None:
        MongoDBClient().close()

    def reset(self) -> None:
        MongoDBClient.reset()


# Convenient global reference
mongo_client = MongoDBClientProxy()
