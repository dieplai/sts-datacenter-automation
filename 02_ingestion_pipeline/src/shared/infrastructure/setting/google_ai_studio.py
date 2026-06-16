"""Google AI Studio settings."""

from shared.infrastructure.setting.base_setting import AppBaseSetting


class GoogleAIStudioSetting(AppBaseSetting):
    """Settings for Google AI Studio Generative Language API."""

    google_ai_studio_api_key: str = ""
    google_ai_studio_model: str = "gemini-1.5-flash"
    google_ai_studio_base_url: str = "https://generativelanguage.googleapis.com"
    google_ai_studio_timeout: int = 60
