"""pro.52wmb.com authentication.

Placeholders are intentionally invalid; override in `_local.py` or via env.
"""
import os

USERNAME = os.environ.get("PRO_USERNAME", "your-email@example.com")
PASSWORD = os.environ.get("PRO_PASSWORD", "your-password")

TARGET_URL = "https://pro.52wmb.com"
PRO_LOGIN_URL = "https://pro.52wmb.com/user/login?redirect=%2FWorkbenches"
