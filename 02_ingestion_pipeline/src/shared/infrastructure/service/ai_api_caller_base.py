"""Abstract CQRS BaseRequestHandler for OpenAI API calls.

Generic on ``RequestT`` (input DTO) and ``ResponseT`` (output DTO).
Provides a fixed ``handle()`` flow:
    _build_prompt → _call_api → _to_response

Subclasses implement ``_build_prompt`` and ``_to_response``.
``_call_api`` is fully implemented here — modules never touch API internals.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from shared.domain.base_model import CustomBaseModel
from shared.domain.prompt import BuiltPrompt
from shared.domain.prompt_template import PromptTemplate
from shared.infrastructure.service.prompt_builder_service import PromptBuilderService

RequestT = TypeVar("RequestT", bound=BaseModel)
ResponseT = TypeVar("ResponseT", bound=BaseModel)


class BaseRequestHandler(ABC, Generic[RequestT, ResponseT]):
    """Abstract CQRS handler that orchestrates prompt → API → response.

    Parameters:
        client: An ``openai.OpenAI`` client instance (injected).
        prompt_service: ``PromptBuilderService`` for token control.
        template: The ``PromptTemplate`` for this handler's domain.
    """

    def __init__(
        self,
        client: Any,
        prompt_service: PromptBuilderService,
        template: PromptTemplate[Any],
    ) -> None:
        self._client = client
        self._prompt_service = prompt_service
        self._template = template

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle(self, request: RequestT) -> ResponseT:
        """Execute the CQRS flow: build prompt → call API → map response.

        Args:
            request: The input DTO.

        Returns:
            The output response DTO.
        """
        # Step 1: Build prompt from request.
        built_prompt = self._build_prompt(request)

        # Step 2: Call OpenAI API.
        output = self._call_api(built_prompt)

        # Step 3: Map raw output + request → response DTO.
        return self._to_response(output, request)

    def handle_batch(
        self,
        requests: list[RequestT],
        max_workers: int = 4,
    ) -> list[ResponseT]:
        """Process multiple requests concurrently, preserving input order.

        Args:
            requests: List of request DTOs.
            max_workers: Maximum parallel threads.

        Returns:
            Ordered list of response DTOs matching the input order.
        """
        results: list[ResponseT | None] = [None] * len(requests)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(self.handle, req): idx
                for idx, req in enumerate(requests)
            }
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                results[idx] = future.result()

        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Abstract hooks — subclasses MUST implement
    # ------------------------------------------------------------------

    @abstractmethod
    def _build_prompt(self, request: RequestT) -> BuiltPrompt:
        """Extract variables from *request* and build a ``BuiltPrompt``.

        Typical implementation:
        ```python
        variables = {"field": request.field, ...}
        return self._prompt_service.build(self._template, variables)
        ```
        """
        ...

    @abstractmethod
    def _to_response(self, output: CustomBaseModel, request: RequestT) -> ResponseT:
        """Map the parsed LLM *output* + original *request* → response DTO."""
        ...

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _temperature(self) -> float:
        """LLM sampling temperature.  Default ``0.0`` (deterministic)."""
        return 0.0

    def _max_output_tokens(self) -> int:
        """Maximum tokens for the LLM response.  Default ``1000``."""
        return 1000

    # ------------------------------------------------------------------
    # Implemented at base — subclasses should NOT override
    # ------------------------------------------------------------------

    def _call_api(self, built_prompt: BuiltPrompt) -> CustomBaseModel:
        """Call OpenAI ``chat.completions.create`` and parse the response.

        Flow:
        1. Format messages into the dict-list expected by the SDK.
        2. Call ``client.chat.completions.create()`` with JSON object mode.
        3. ``json.loads`` the response content.
        4. ``model_validate`` into ``built_prompt.output_class``.
        5. Return the validated ``PromptOutput`` subclass instance.
        """
        # Step 1: Format messages.
        api_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in built_prompt.messages
        ]

        # Step 2: Call API.
        response = self._client.chat.completions.create(
            model=self._get_model_name(),
            messages=api_messages,
            temperature=self._temperature(),
            max_tokens=self._max_output_tokens(),
            response_format={"type": "json_object"},
        )

        # Step 3: Parse JSON from response.
        raw_content = response.choices[0].message.content
        data = json.loads(raw_content)

        # Step 4: Validate into output class.
        output = built_prompt.output_class.model_validate(data)

        return output

    def _get_model_name(self) -> str:
        """Resolve the model name from the client or fall back to default."""
        # If the template or service carries a model name, use it.
        # Otherwise default to gpt-4o-mini.
        return getattr(self._prompt_service, "model_name", "gpt-4o-mini")
