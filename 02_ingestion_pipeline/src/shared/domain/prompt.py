"""Prompt domain models — core data structures for the prompt management system.

These models flow through the entire system and have no infrastructure dependencies.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from shared.domain.base_model import CustomBaseModel


class Message(BaseModel):
    """A single message in the OpenAI chat format.

    Attributes:
        role: The role of the message sender (system, user, or assistant).
        content: The text content of the message.
    """

    role: Literal["system", "user", "assistant"] = Field(
        ..., description="Role of the message sender"
    )
    content: str = Field(..., description="Text content of the message")


class BuiltPrompt(BaseModel):
    """Result object after a PromptTemplate is rendered with real data.

    This is the sole input object for the API calling layer.

    Attributes:
        messages: Fully formatted chat messages ready to send.
        output_schema: JSON Schema dict of the expected output class.
        output_class: The Pydantic model type used to parse the LLM response.
        num_tokens: Estimated token count for the messages.
        metadata: Free-form dict for tracing / debugging.
    """

    messages: list[Message] = Field(
        ..., description="Formatted chat messages ready to send"
    )
    output_schema: dict[str, Any] = Field(
        ..., description="JSON Schema of the output class"
    )
    output_class: type[CustomBaseModel] = Field(
        ..., description="Pydantic model type to parse the LLM response"
    )
    num_tokens: int = Field(
        default=0, description="Estimated token count for all messages"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Free-form dict for tracing"
    )

    class Config:
        arbitrary_types_allowed = True
