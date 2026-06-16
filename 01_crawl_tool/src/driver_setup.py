"""
src/driver_setup.py
Compatibility shim: re-exports get_driver from src.core.browser and provides
a standalone force_kill_chrome. Kept here so older imports like
`from ..driver_setup import get_driver` continue to work.
"""
import subprocess
import sys

from .core.browser import get_driver  # noqa: F401 — re-export


def force_kill_chrome():
    """Kill orphan chromedriver/chrome processes left by a crashed session."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "chromedriver.exe", "/T"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True)
    except Exception:
        pass
