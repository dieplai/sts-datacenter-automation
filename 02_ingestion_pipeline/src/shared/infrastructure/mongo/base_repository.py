"""Shared repository abstractions and MongoDB base implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any, Generic, Type, TypeVar

from bson import ObjectId
from pydantic import BaseModel
from pymongo.collection import Collection
from pymongo import errors
from shared.domain.base_model import CustomBaseModel
from shared.infrastructure.mongo.client import mongo_client
from shared.utils.logging import info, log_error

T = TypeVar("T", bound=CustomBaseModel)


class BaseRepository(ABC, Generic[T]):
    """Generic repository contract used by the application layer."""

    @abstractmethod
    def find_one(self, **filter_options: Any) -> T | None:
        """
        Find a single item that matches the provided filters.
        
        Returns:
            Model instance or None if not found
        """

    @abstractmethod
    def find_many(self, **filter_options: Any) -> list[T]:
        """
        Find multiple items that match the provided filters.
        
        Returns:
            List of model instances
        """

    @abstractmethod
    def insert_one(self, model: T) -> str | None:
        """
        Insert a single model by converting it to document using model._to_doc().
        
        Args:
            model: Model instance to persist (will call model._to_doc() internally)
            
        Returns:
            Document ID or None if insert fails
        """

    @abstractmethod
    def insert_many(self, models: list[T]) -> bool:
        """
        Insert multiple models by converting them to documents using _to_doc().
        
        Args:
            models: List of model instances (each will call _to_doc() internally)
            
        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    def update_one(self, update_model: T) -> bool:
        """
        Update a single model by converting it to document using update_model._to_doc().
        
        Args:
            update_model: Model instance to update (will call _to_doc() internally)
            
        Returns:
            True if successful, False otherwise
        """

    @abstractmethod
    def delete_one(self, **filter_options: Any) -> bool:
        """
        Delete a single item matching the provided filters.
        
        Returns:
            True if successful, False otherwise
        """



T = TypeVar("T", bound=CustomBaseModel)


class BaseMongoRepository(BaseRepository[T], Generic[T]):
    model: Type[T]
    collection_name: str

    def __init__(
        self,
        model: Type[T],
        collection_name: str | None = None,
    ):
        self.model = model
        self.collection_name = collection_name or getattr(model, "collection_name", "")
        self.database = mongo_client.db
        if not self.collection_name:
            raise Exception(
                f"Collection name is not configured for model '{model.__name__}'."
            )

    def _get_collection(self) -> Collection:
        info("Start _get_collection")

        _collection_name = self.collection_name
        info(f"Collection name: {_collection_name}")

        try:
            list_collection_names = self.database.list_collection_names()
        except Exception as e:
            log_error("Failed to list collections")
            raise

        if _collection_name not in list_collection_names:
            log_error(f"Collection {_collection_name} not found", )
            raise ValueError(f"Collection '{_collection_name}' not found")

        return self.database[_collection_name]

    def _normalize_filter_options(self, options: dict[str, Any]) -> dict[str, Any]:
        """Normalize repository filters before sending them to MongoDB."""
        filter_options = dict(options)
        temp_id = filter_options.pop("_id", filter_options.pop("id", None))

        if temp_id is not None:
            if isinstance(temp_id, str):
                filter_options["_id"] = ObjectId(temp_id)
            else:
                filter_options["_id"] = temp_id
        info(filter_options)
        return filter_options

    def find_one(self, **filter_options) -> T | None:
        try:
            filter_options = self._normalize_filter_options(filter_options)
            info(json.dumps(filter_options,default=str))
            raw = self._get_collection().find_one(filter_options)
            if raw != None:
                return self.model._to_model(raw)
            return None
        except errors.OperationFailure:
            log_error("[%s] find_one failed: %s", self.model.__name__, filter_options)
            return None

    def find_many(self, **filter_options) -> list[T]:
        try:
            filter_options = self._normalize_filter_options(filter_options)
            info(json.dumps(filter_options))
            raws = list(self._get_collection().find(filter_options))
            info(f"Length Result: {len(raws)}")
            for raw in raws:
                info(f"Result: {json.dumps(raw,default=str)}")
            return [
                model
                for raw in raws
                if (model := self.model._to_model(raw)) is not None
            ]
        except errors.OperationFailure:
            log_error("[%s] find_many failed: %s", self.model.__name__, filter_options)
            return []


    def insert_one(self, model: T) -> str | None:
        """
        Insert a single model by converting it to document using model._to_doc().
        
        Args:
            model: Model instance to persist
            
        Returns:
            Inserted document ID or None if insert fails
        """
        try:
            document = model._to_doc()
            result = self._get_collection().insert_one(document)
            return result.inserted_id
        except errors.WriteError:
            log_error("[%s] insert_one failed", self.model.__name__)
            return None

    def insert_many(self, models: list[T]) -> bool:
        """
        Insert multiple models by converting each to document using _to_doc().
        
        Args:
            models: List of model instances to persist
            
        Returns:
            True if successful, False otherwise
        """
        try:
            documents = [model._to_doc() for model in models]
            self._get_collection().insert_many(documents)
            return True
        except (errors.WriteError, errors.BulkWriteError):
            log_error("[%s] insert_many failed", self.model.__name__)
            return False

    def update_one(self, update_model: T) -> bool:
        """
        Update a single model by converting it to document using update_model._to_doc().
        
        Args:
            update_model: Model instance to update
            
        Returns:
            True if successful, False otherwise
        """
        try:
            document = update_model._to_doc()
            file_id = document.pop("_id", document.pop("file_id", None))
            
            if file_id is None:
                log_error(f"[{self.model.__name__}] update_one failed: no ID found")
                return False
            
            # Convert string ID to ObjectId if needed
            if isinstance(file_id, str):
                file_id = ObjectId(file_id)
                
            result = self._get_collection().update_one(
                {"_id": file_id},
                {"$set": document}
            )
            return result.modified_count > 0
        except errors.WriteError:
            log_error("[%s] update_one failed", self.model.__name__)
            return False

    def delete_one(self, **filter_options) -> bool:
        options =self._normalize_filter_options(filter_options)
        try:
            self._get_collection().delete_one(options)
            return True
        except errors.WriteError:
            log_error("[%s] delete_one failed", self.model.__name__)
            return False
