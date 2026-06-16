"""OpenAI API settings."""

from shared.infrastructure.setting.base_setting import AppBaseSetting


class OpenAISetting(AppBaseSetting):
    """Settings for OpenAI API integration.

    Environment variables are read automatically by pydantic-settings:
    - OPENAI_API_KEY
    - OPENAI_MODEL
    - OPENAI_MAX_CONTEXT_WINDOW
    """

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_max_context_window: int = 128000
