"""Minimal structured logger + time formatter.

Kept simple on purpose — no third-party dep, consistent format across the
codebase. Swap in `logging` / `structlog` in a later PR if the team wants
JSON output for ingestion into an observability backend.
"""
from datetime import datetime

_ICONS = {
    "INFO": "[i] ",
    "SUCCESS": "[+] ",
    "WARNING": "[!] ",
    "ERROR": "[x] ",
    "PROCESS": "[>] ",
    "SEARCH": "[~] ",
    "DEBUG": "[-] ",
    "POPUP": "[p] ",
}


def log(msg, level="INFO"):
    """Print `[HH:MM:SS] <icon> msg` to stdout."""
    now = datetime.now().strftime("%H:%M:%S")
    icon = _ICONS.get(level, "")
    print(f"[{now}] {icon}{msg}")


def format_time_elapsed(seconds):
    """Human-readable duration (hours/minutes/seconds, Vietnamese)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
