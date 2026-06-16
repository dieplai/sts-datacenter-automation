"""Infrastructure layer — Chrome/CDP/auth/tokens.

Consumed by `nav/`, `extract/`, `pipeline/`. Depends only on `config/` and
`observability/`.
"""
from .browser import get_driver
from .tokens import tokens_from_driver
from .auth import login_pro
from .proxy_rotator import get_rotator

__all__ = ["get_driver", "tokens_from_driver", "login_pro", "get_rotator"]
