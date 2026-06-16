"""Abstract base model for all models in the system."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class CustomBaseModel(ABC,BaseModel):
    """
    Abstract base class for models that support conversion to/from document format.
    Provides interface for persistence operations.
    """

    @classmethod
    @abstractmethod
    def _to_model(cls, doc: dict) -> "CustomBaseModel":
        """
        Convert a document dictionary to a model instance.
        
        Args:
            doc: Dictionary representation of the document
            
        Returns:
            Instance of the model class
        """
        pass

    @abstractmethod
    def _to_doc(self) -> dict:
        """
        Convert the model instance to a document dictionary.
        
        Returns:
            Dictionary representation suitable for persistence
        """
        pass
