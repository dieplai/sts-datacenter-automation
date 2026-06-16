"""Pipeline factory — wires the Chain of Responsibility pipeline."""

from data_processing.application.pipeline_handlers import (
    BaseProcessingHandler,
)
from data_processing.application.pipeline_handlers.hs_code_handlers import (
    ValidationHandler,
    SavingHandler
)

def build_hscode_pipeline() -> BaseProcessingHandler:
    validation_handler: BaseProcessingHandler = ValidationHandler()
    saving_handler: BaseProcessingHandler = SavingHandler()
    validation_handler.set_next(saving_handler)
    return validation_handler

def build_custom_pipeline(handlers: list[BaseProcessingHandler]) -> BaseProcessingHandler:
    """
    Build a custom pipeline with provided handlers in order.

    Args:
        handlers: List of handlers in execution order

    Returns:
        The head of the custom chain

    Raises:
        ValueError: If handlers list is empty
    """
    if not handlers:
        raise ValueError("At least one handler is required")

    for i in range(len(handlers) - 1):
        handlers[i].set_next(handlers[i + 1])

    return handlers[0]
