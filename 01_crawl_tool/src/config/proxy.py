"""Brightdata residential proxy (optional).

Empty values = no proxy. Override via env or `_local.py`.

acc6: hỗ trợ Brightdata sticky-session — append `-session-<id>` vào username
để pin IP residential trong ~10 phút. Đổi session-id = đổi IP. ProxyRotator
ở `src/core/proxy_rotator.py` sinh session-id và build proxy URL qua
`build_proxy_url(session_id=...)`.
"""
import os

PROXY_HOST = os.environ.get("PROXY_HOST", "")
PROXY_PORT = os.environ.get("PROXY_PORT", "")
PROXY_USER = os.environ.get("PROXY_USER", "")
PROXY_PASS = os.environ.get("PROXY_PASS", "")


def build_proxy_url(session_id=None, host=None, port=None, user=None,
                    password=None):
    """Build a Brightdata-style proxy URL.

    If `session_id` truyền vào, append `-session-<id>` vào username để
    Brightdata pin IP cho session đó. Trả về None nếu không có proxy
    config (host trống).

    Các param `host/port/user/password` chỉ dùng khi muốn override config
    runtime — mặc định đọc từ `_local.py` qua `config` module.
    """
    if host is None or port is None or user is None or password is None:
        try:
            from .. import config as _cfg
        except ImportError:
            import config as _cfg  # type: ignore
        host = host or getattr(_cfg, "PROXY_HOST", "")
        port = port or getattr(_cfg, "PROXY_PORT", "")
        user = user or getattr(_cfg, "PROXY_USER", "")
        password = password or getattr(_cfg, "PROXY_PASS", "")

    if not host:
        return None

    if session_id:
        # Brightdata format: <user>-session-<id>. Sticky session ~10 phút.
        user = f"{user}-session-{session_id}"

    return f"http://{user}:{password}@{host}:{port}"
