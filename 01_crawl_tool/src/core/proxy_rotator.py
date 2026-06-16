"""Brightdata sticky-session rotator + adaptive cooldown on block.

acc6 IP-block resistance. Singleton instance shared by Selenium + httpx code
paths so they all see the same `current_session_id` (and thus the same
exit-IP family) at any given moment. When `rotate()` is called, the next
URL fetched gets a new session-id → Brightdata maps it to a new residential
IP for ~10 minutes.

Usage:
    rotator = get_rotator()                       # singleton
    proxy_url = rotator.current_proxy_url()       # build URL with session-id
    rotator.rotate(reason="page_boundary")         # cycle session-id
    rotator.cooldown_on_block(45, reason="429")   # sleep + cycle

Disabled via `PROXY_ROTATION_ENABLED=False` in `_local.py`. Disabled mode
returns the static proxy URL (no session-id) — same as acc5 behavior.
"""
import secrets
import time

try:
    from ..config import proxy as _proxy_cfg
    from .. import config as _cfg
    from ..observability import log
except ImportError:  # pragma: no cover — script-mode fallback
    import os, sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import proxy as _proxy_cfg  # type: ignore
    import config as _cfg  # type: ignore
    from observability import log  # type: ignore


def _new_session_id():
    """8-char hex (~32-bit entropy). Brightdata accepts any short alnum
    token; collisions are fine — they just hit the same IP pool."""
    return secrets.token_hex(4)


class ProxyRotator:
    """Holds the current Brightdata session-id and cycles it on demand."""

    def __init__(self):
        self._enabled = bool(getattr(_cfg, "PROXY_ROTATION_ENABLED", False))
        self._rotation_interval = max(
            1, int(getattr(_cfg, "PROXY_ROTATION_INTERVAL_PAGES", 10))
        )
        self._cooldown_default = max(
            5, int(getattr(_cfg, "PROXY_COOLDOWN_ON_BLOCK_SEC", 45))
        )
        self._session_id = _new_session_id() if self._enabled else None
        self._last_rotate_page = 0
        self._rotation_count = 0
        if self._enabled:
            log(f"[ProxyRotator] initialized | session={self._session_id} | "
                f"interval={self._rotation_interval} pages | "
                f"cooldown={self._cooldown_default}s", "INFO")
        else:
            log("[ProxyRotator] disabled (acc5-compatible mode)", "INFO")

    @property
    def enabled(self):
        return self._enabled

    @property
    def session_id(self):
        return self._session_id

    @property
    def rotation_count(self):
        return self._rotation_count

    def current_proxy_url(self):
        """URL hiện tại (đang dùng). Pass-through tới `build_proxy_url`."""
        return _proxy_cfg.build_proxy_url(session_id=self._session_id)

    def rotate(self, reason="manual"):
        """Sinh session-id mới, log lý do, increment counter."""
        if not self._enabled:
            return None
        old = self._session_id
        self._session_id = _new_session_id()
        self._rotation_count += 1
        log(f"[ProxyRotator] rotate: session {old} → {self._session_id} | "
            f"reason={reason} | total_rotations={self._rotation_count}", "INFO")
        return self._session_id

    def should_rotate_by_page_count(self, current_page):
        """True nếu đã chạy đủ `interval` page kể từ lần rotate cuối.

        Counter reset trong `mark_rotated_at_page()` — caller phải gọi
        sau khi rotate xong để tránh re-rotate cùng 1 page.
        """
        if not self._enabled:
            return False
        return (current_page - self._last_rotate_page) >= self._rotation_interval

    def mark_rotated_at_page(self, page_num):
        """Caller gọi sau khi đã rotate ở page này. Reset counter."""
        self._last_rotate_page = page_num

    def cooldown_on_block(self, seconds=None, reason="block"):
        """Sleep `seconds` rồi rotate session. Dùng khi detect 429/403/captcha.

        Nếu rotation disabled, vẫn sleep (defensive backoff) nhưng không
        đổi session-id.
        """
        secs = int(seconds if seconds is not None else self._cooldown_default)
        log(f"[ProxyRotator] cooldown: {secs}s | reason={reason}", "WARNING")
        time.sleep(secs)
        if self._enabled:
            self.rotate(reason=f"after_cooldown_{reason}")

    def force_rotate_browser(self):
        """Stub — caller (core_pro_detail) decides khi nào restart Chrome.

        Trả về proxy URL mới sau khi rotate, để caller pass vào
        `browser.rebuild_with_new_proxy(url)`. Selenium-side rotation
        đắt (Chrome restart ~15-30s) nên chỉ gọi từ DEEP recovery.
        """
        if self._enabled:
            self.rotate(reason="browser_rebuild")
        return self.current_proxy_url()


# --- Singleton ----------------------------------------------------------

_singleton = None


def get_rotator():
    """Lấy singleton ProxyRotator. Tạo lazily ở lần gọi đầu."""
    global _singleton
    if _singleton is None:
        _singleton = ProxyRotator()
    return _singleton


def reset_for_tests():
    """Test-only: vứt singleton để test cấu hình khác."""
    global _singleton
    _singleton = None
