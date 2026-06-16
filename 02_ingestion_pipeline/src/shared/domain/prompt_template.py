"""Abstract PromptTemplate — center of the prompt management strategy.

``PromptTemplate`` is a Generic Pydantic model parameterized on ``OutputT``
(bounded by ``PromptOutput``).  Each concrete subclass at the module level
declares ``system_prompt``, ``user_prompt_template``, and implements the
``output_class`` property.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from shared.domain.base_model import CustomBaseModel
from shared.domain.prompt import BuiltPrompt, Message

OutputT = TypeVar("OutputT", bound="CustomBaseModel")


class PromptTemplate(BaseModel, Generic[OutputT]):
    """Abstract prompt template that every module-level template must subclass.

    Subclasses **must** provide:
    - ``system_prompt``          — system instruction string.
    - ``user_prompt_template``   — Python ``.format()`` template string.
    - ``output_class`` property  — returns the concrete ``PromptOutput`` subclass.

    The ``build()`` method renders the template and injects the output JSON
    schema automatically so callers never need to write format instructions
    manually.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    system_prompt: str = Field(
        ..., description="System instruction content"
    )
    user_prompt_template: str = Field(
        ..., description="Template string with Python {placeholder} syntax"
    )

    @property
    @abstractmethod
    def output_class(self) -> type[OutputT]:
        """Return the Pydantic output model class for this template."""
        ...

    def build(self, variables: dict) -> BuiltPrompt:
        """Render the template with *variables* and return a ``BuiltPrompt``.

        Steps:
        1. Format ``user_prompt_template`` with *variables* → user content.
        2. Get ``output_class.model_json_schema()`` → inject into system prompt
           as a JSON Schema instruction block.
        3. Package into ``BuiltPrompt`` and return.

        Args:
            variables: Mapping of placeholder names to their values.

        Returns:
            A ``BuiltPrompt`` ready for token counting and API calling.

        Raises:
            KeyError: If a required placeholder is missing from *variables*.
        """
        # Step 1: Format user prompt with provided variables.
        try:
            user_content = self.user_prompt_template.format(**variables)
        except KeyError as exc:
            raise KeyError(
                f"Missing variable in user_prompt_template: {exc}"
            ) from exc

        # Step 2: Inject output JSON schema into system prompt.
        output_schema = self.output_class.model_json_schema()
        schema_instruction = (
            "\n\n---\n"
        "You MUST return a valid JSON object that conforms to the "
            "following JSON Schema:\n"
            f"```json\n{json.dumps(output_schema, indent=2, ensure_ascii=False)}\n```"
        )
        full_system_prompt = self.system_prompt + schema_instruction

        # Step 3: Build messages and return BuiltPrompt.
        messages = [
            Message(role="system", content=full_system_prompt),
            Message(role="user", content=user_content),
        ]

        return BuiltPrompt(
            messages=messages,
            output_schema=output_schema,
            output_class=self.output_class,
            num_tokens=0,  # Will be set by PromptBuilderService
            metadata={},
        )

