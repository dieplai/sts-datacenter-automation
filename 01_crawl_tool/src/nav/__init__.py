"""UI navigation — pagination + popup handling for the result table."""
from .pagination import (
    go_to_page,
    has_next_page,
    go_to_next_page,
    get_ui_pagination_progress,
    close_tips_modal,
)

__all__ = [
    "go_to_page",
    "has_next_page",
    "go_to_next_page",
    "get_ui_pagination_progress",
    "close_tips_modal",
]
