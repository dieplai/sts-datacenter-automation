"""MongoDB infrastructure."""

from shared.infrastructure.mongo.base_repository import BaseMongoRepository, BaseRepository
from shared.infrastructure.mongo.client import mongo_client

__all__ = ["BaseRepository", "BaseMongoRepository", "mongo_client"]
