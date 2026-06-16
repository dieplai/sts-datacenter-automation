"""PromptBuilderService — centralized token management and BuiltPrompt assembly.

This service is injected into every ``BaseRequestHandler``.  All token
counting and truncation logic lives here — modules never deal with tokens.
"""

from __future__ import annotations

from typing import Any

from shared.domain.prompt import BuiltPrompt, Message
from shared.domain.prompt_template import PromptTemplate


class PromptBuilderService:
    """Build a complete ``BuiltPrompt`` with token control.

    Parameters:
        max_token_window: Maximum allowed token count (default 90% of context).
        model_name: Model name for tiktoken encoding lookup.
    """

    def __init__(
        self,
        max_token_window: int = 115_200,
        model_name: str = "gpt-4o-mini",
    ) -> None:
        self.max_token_window = max_token_window
        self.model_name = model_name

    def build(
        self,
        template: PromptTemplate[Any],
        variables: dict[str, Any],
    ) -> BuiltPrompt:
        """Render *template* with *variables* and apply token control.

        Processing flow:
        1. Call ``template.build(variables)`` → raw ``BuiltPrompt``.
        2. Count total tokens of all messages (via ``tiktoken``).
        3. If token count exceeds ``max_token_window``, truncate the last
           ``user`` message from the end until it fits.
        4. Set ``num_tokens`` on the ``BuiltPrompt`` and return.

        Args:
            template: The prompt template to render.
            variables: Variable values to fill placeholders.

        Returns:
            A ``BuiltPrompt`` with token count set and content truncated
            if necessary.
        """
        # Step 1: Build raw BuiltPrompt from template.
        built = template.build(variables)

        # Step 2: Count tokens.
        total_tokens = self._count_tokens(built.messages)

        # Step 3: Truncate user message if over limit.
        if total_tokens > self.max_token_window:
            built = self._truncate_user_message(built, total_tokens)
            total_tokens = self._count_tokens(built.messages)

        # Step 4: Set num_tokens and return.
        return BuiltPrompt(
            messages=built.messages,
            output_schema=built.output_schema,
            output_class=built.output_class,
            num_tokens=total_tokens,
            metadata=built.metadata,
        )

    def _count_tokens(self, messages: list[Message]) -> int:
        """Count total tokens across all messages using tiktoken.

        Falls back to a simple word-based estimate when tiktoken is not
        available or the model encoding cannot be resolved.
        """
        try:
            import tiktoken

            try:
                encoding = tiktoken.encoding_for_model(self.model_name)
            except KeyError:
                encoding = tiktoken.get_encoding("cl100k_base")

            total = 0
            for msg in messages:
                # Per-message overhead (role + delimiters).
                total += 4
                total += len(encoding.encode(msg.content))
            # Reply priming tokens.
            total += 2
            return total

        except ImportError:
            # Fallback: rough estimate (~1 token per 4 chars).
            return sum(len(msg.content) // 4 for msg in messages)

    def _truncate_user_message(
        self,
        built: BuiltPrompt,
        current_tokens: int,
    ) -> BuiltPrompt:
        """Truncate the last user message from the end to fit the window.

        Only the *content* of the last user-role message is shortened.
        """
        overflow = current_tokens - self.max_token_window
        # Approximate chars to remove (~4 chars per token).
        chars_to_remove = overflow * 4

        messages = list(built.messages)
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "user":
                original = messages[i].content
                truncated = original[: max(0, len(original) - chars_to_remove)]
                truncated += "\n\n[... content truncated due to token limit ...]"
                messages[i] = Message(role="user", content=truncated)
                break

        return BuiltPrompt(
            messages=messages,
            output_schema=built.output_schema,
            output_class=built.output_class,
            num_tokens=built.num_tokens,
            metadata=built.metadata,
        )
