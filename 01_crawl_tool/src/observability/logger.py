"""Enterprise structured logger — no third-party deps.

Format: YYYY-MM-DD HH:MM:SS.mmm | LEVEL    | MODULE     | message
Emoji/icon characters are stripped at output time — no call-site changes needed.
"""
import re
from datetime import datetime

_LEVEL_WIDTH = 8
_MODULE_WIDTH = 10

_STRIP_EMOJI = re.compile(
    r"[\U00010000-\U0010FFFF"
    r"\U0001F300-\U0001F9FF"
    r"☀-➿"
    r"⬀-⯿"
    r"︀-️"
    r"‍"
    r"]+",
    flags=re.UNICODE,
)


def _clean(msg: str) -> str:
    return _STRIP_EMOJI.sub("", str(msg)).strip()


def log(msg, level="INFO", module="CRAWL"):
    """Print enterprise-format log line to stdout."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    lvl = level.upper().ljust(_LEVEL_WIDTH)
    mod = module.upper().ljust(_MODULE_WIDTH)
    print(f"{now} | {lvl} | {mod} | {_clean(msg)}", flush=True)


def format_time_elapsed(seconds):
    """Human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
