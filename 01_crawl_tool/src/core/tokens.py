"""Extract `access-token` + `auth-pd-user` from the Selenium session.

These two values are what `pro.52wmb.com` puts into `localStorage` after
login and sends as HTTP headers on every XHR. The httpx client in
`extract/http_fetcher.py` reads them here and re-uses them.
"""
import json


def tokens_from_driver(driver):
    """Return `(access_token, pd_user)` from the browser's localStorage.

    Values in localStorage are JSON-encoded, e.g. '"1ce69a9cee3d5a58"'.
    Returns `(None, None)` if either key is missing.
    """
    def _get(key):
        try:
            v = driver.execute_script(
                f"return window.localStorage.getItem({json.dumps(key)});"
            )
        except Exception:
            return None
        if v is None:
            return None
        if isinstance(v, str) and len(v) >= 2 and v.startswith('"') and v.endswith('"'):
            try:
                return json.loads(v)
            except Exception:
                return v.strip('"')
        return v

    return _get("access-token"), _get("auth_pd_user")
