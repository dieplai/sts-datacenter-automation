"""Processing handler port (interface) definition."""

from typing import Protocol
from data_processing.domain.models.processed_data import ProcessedData


class ProcessingHandler(Protocol):
    """
    Contract for processing handlers in the pipeline.
    Domain defines interface; Infrastructure implements it.
    """

    def handle(self, data: ProcessedData) -> ProcessedData:
        """
        Process data and pass to next handler in chain.

        Args:
            data: ProcessedData to handle

        Returns:
            Modified ProcessedData
        """
        ...

    def set_next(self, handler: "ProcessingHandler") -> "ProcessingHandler":
        """
        Set the next handler in the chain.
        Fluent interface for chaining.

        Args:
            handler: Next handler in chain

        Returns:
            The next handler (for chaining)
        """
        ...
