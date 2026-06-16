"""Base processing handler — implements Chain of Responsibility pattern."""

from abc import ABC, abstractmethod
from typing import Any
from data_processing.domain.models.processed_data import ProcessedData, ProcessingStatus


class BaseProcessingHandler(ABC):
    """
    Abstract base class for all handlers in the processing chain.
    Implements Template Method and Chain of Responsibility patterns.
    """

    def __init__(self):
        self._next: "BaseProcessingHandler | None" = None

    def set_next(self, handler: "BaseProcessingHandler") -> "BaseProcessingHandler":
        """
        Set the next handler in the chain.
        Fluent interface — allows A.set_next(B).set_next(C).

        Args:
            handler: Next handler in the chain

        Returns:
            The handler passed in (for chaining)
        """
        self._next = handler
        return handler

    def handle(self, data: ProcessedData) -> ProcessedData:
        """
        Process data through this handler and pass to next.
        Template Method: orchestrates the chain.

        Args:
            data: Data to process

        Returns:
            Processed data (possibly modified by entire chain)
        """
        result = self._process(data)
        if self._next is not None:
            return self._next.handle(result)
        return result
    
    def _update_processing_result(
        self,
        data: ProcessedData,
        processing_result: Any,
        is_valid: bool,
        processing_step:dict,
        df: Any | None = None,
    ) -> ProcessedData:
        """
        Update processing execution result into the `ProcessedData` object.

        This method updates internal processing metadata and synchronizes
        the latest execution state into the returned `ProcessedData` instance.

        Updated attributes include:
        - `structured_data["processing_step"]`
        - `structured_data["dataframe"]` (if provided)
        - `is_valid`
        - `status`
        - `errors`
        - `processing_steps`

        Args:
            data (ProcessedData):
                Current processed data instance.

            processing_result (Any):
                Result payload generated from the current processing step.
                Usually contains logs, validation results, metrics,
                transformation summaries, or execution details.

            is_valid (bool):
                Indicates whether the current processing step succeeded.

            processing_step:
                Name or identifier of the current processing step.

            df (Any | None, optional):
                Updated dataframe generated after processing.
                If provided, replaces the existing dataframe stored in
                `structured_data`.

        Returns:
            ProcessedData:
                New immutable `ProcessedData` instance containing updated
                processing state and execution metadata.
        """

    @abstractmethod
    def _process(self, data: ProcessedData) -> ProcessedData:
        """
        Business logic of this handler.
        Subclasses override this method.

        Args:
            data: Data to process

        Returns:
            Modified data for next handler
        """
        ...

    def __repr__(self) -> str:
        """String representation for debugging."""
        next_name = self._next.__class__.__name__ if self._next else "None"
        return f"{self.__class__.__name__} -> {next_name}"
