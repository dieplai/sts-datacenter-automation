"""Base settings for the entire application."""

from pathlib import Path
from typing import ClassVar

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = PROJECT_ROOT / "src"

class AppBaseSetting(BaseSettings):
    """
    Base class for all settings in the system.
    Pydantic-settings automatically reads from environment variables.
    Subclasses only need to declare fields.
    """

    PROJECT_ROOT: ClassVar[Path] = PROJECT_ROOT
    SRC_ROOT: ClassVar[Path] = SRC_ROOT

    model_config = ConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        case_sensitive=False,
        extra="ignore"
    )
