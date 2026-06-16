"""HTTP client for 52wmb Pro 2026 trade detail/list endpoints.

Auth is via two request headers (NOT cookies):
  - access-token  (read from window.localStorage['access-token'])
  - auth-pd-user  (read from window.localStorage['auth_pd_user'])

Detail endpoint:
  GET /api/raw/trade/detail/{bill_id}?country=vietnam&ie=0
      &trade_date=YYYY-MM-DD&lang=en

List endpoint:
  GET /api/raw/trade/list?country=vietnam&start=0&size=30&ie=0
      &start_date=YYYY-MM-DD&end_date=YYYY-MM-DD[&hs=..&buyer=..]
"""
import httpx

try:
    from ..observability import SessionExpired, ApiError, log
    from ..core.tokens import tokens_from_driver as _tokens_from_driver
    from .. import config
except ImportError:  # pragma: no cover
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import SessionExpired, ApiError, log
    from core.tokens import tokens_from_driver as _tokens_from_driver
    import config


BASE = (
    config.TARGET_URL.rstrip("/") if getattr(config, "TARGET_URL", None)
    else "https://pro.52wmb.com"
)
DETAIL_PATH_TEMPLATE = "/api/raw/trade/detail/{bill_id}"
LIST_PATH = "/api/raw/trade/list"


def build_proxy_url():
    """acc6: pull proxy URL từ ProxyRotator để pickup session-id hiện tại.

    Khi rotator disabled (acc5 mode), trả về URL static y hệt hành vi cũ.
    """
    if not getattr(config, "FAST_API_USE_PROXY", True):
        return None
    host = getattr(config, "PROXY_HOST", None)
    if not host:
        return None
    try:
        from ..core.proxy_rotator import get_rotator
        return get_rotator().current_proxy_url()
    except Exception:
        # Fallback to static URL nếu rotator chưa init
        return (
            f"http://{config.PROXY_USER}:{config.PROXY_PASS}@"
            f"{host}:{config.PROXY_PORT}"
        )


# Re-export from core.tokens for backward-compat with any external callers
tokens_from_driver = _tokens_from_driver


def default_headers(access_token=None, pd_user=None, user_agent=None, referer=None):
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Referer": referer or f"{BASE}/CustomsData",
        "Origin": BASE,
        "access-token": access_token or "",
        "auth-pd-user": str(pd_user or ""),
        "client-device": "pc",
        "client-lang": "en",
    }


class ProHttpClient:
    """Sync httpx client. Use `from_selenium()` to build from browser state."""

    def __init__(self, access_token=None, pd_user=None, proxy=None,
                 user_agent=None, timeout=15.0):
        self.access_token = access_token
        self.pd_user = pd_user
        self.proxy = proxy
        self.user_agent = user_agent
        self._client = httpx.Client(
            base_url=BASE,
            proxy=proxy,
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers=default_headers(
                access_token=access_token, pd_user=pd_user, user_agent=user_agent,
            ),
            follow_redirects=False,
        )

    @classmethod
    def from_selenium(cls, driver, **kwargs):
        access, pd_user = tokens_from_driver(driver)
        if not access or not pd_user:
            log("⚠️ access-token / auth_pd_user not found in localStorage — "
                "fast mode will fail", "WARNING")
        try:
            ua = driver.execute_script("return navigator.userAgent")
        except Exception:
            ua = None
        return cls(
            access_token=access, pd_user=pd_user,
            proxy=build_proxy_url(), user_agent=ua, **kwargs,
        )

    def refresh_tokens(self, driver):
        access, pd_user = tokens_from_driver(driver)
        if access:
            self.access_token = access
            self._client.headers["access-token"] = access
        if pd_user:
            self.pd_user = pd_user
            self._client.headers["auth-pd-user"] = str(pd_user)

    def disable_proxy(self):
        """Rebuild the inner httpx.Client without a proxy, preserving
        headers/tokens. Used when BrightData (or whatever upstream proxy)
        starts returning 407 — the site itself is reachable directly,
        so we'd rather hit it from the user's IP than fail every fetch."""
        try:
            self._client.close()
        except Exception:
            pass
        self.proxy = None
        self._client = httpx.Client(
            base_url=BASE,
            proxy=None,
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers=default_headers(
                access_token=self.access_token,
                pd_user=self.pd_user,
                user_agent=self.user_agent,
            ),
            follow_redirects=False,
        )

    def rebuild_with_proxy(self, new_proxy_url):
        """acc6: rebuild httpx.Client với proxy URL mới (giữ tokens/headers).

        Dùng khi ProxyRotator vừa rotate session-id — caller pull URL mới
        bằng `get_rotator().current_proxy_url()` rồi truyền vào đây.
        Truyền None = disable proxy (= disable_proxy()).
        """
        try:
            self._client.close()
        except Exception:
            pass
        self.proxy = new_proxy_url
        self._client = httpx.Client(
            base_url=BASE,
            proxy=new_proxy_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers=default_headers(
                access_token=self.access_token,
                pd_user=self.pd_user,
                user_agent=self.user_agent,
            ),
            follow_redirects=False,
        )

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass

    def _parse(self, r):
        if r.status_code == 429:
            raise ApiError(429, "rate limited")
        if r.status_code >= 500:
            raise ApiError(r.status_code, "server error")
        if r.status_code != 200:
            raise ApiError(r.status_code, f"unexpected status: {r.text[:200]}")
        body = r.json()
        state = body.get("state")
        if state == 0:
            return body.get("data") or {}
        if state in (3001, 4003):
            raise SessionExpired(state, body.get("message", ""))
        raise ApiError(state, body.get("message", ""))

    def fetch_detail(self, bill_id, trade_date, country="vietnam", ie=0):
        url = DETAIL_PATH_TEMPLATE.format(bill_id=bill_id)
        params = {
            "country": country, "ie": ie,
            "trade_date": trade_date, "lang": "en",
        }
        try:
            r = self._client.get(url, params=params)
        except httpx.HTTPError as e:
            raise ApiError("network", str(e))
        return self._parse(r)

    def fetch_list(self, *, country="vietnam", ie=0, start=0, size=30,
                   start_date=None, end_date=None, **extra):
        params = {"country": country, "ie": ie, "start": start, "size": size}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        for k, v in extra.items():
            if v not in (None, ""):
                params[k] = v
        try:
            r = self._client.get(LIST_PATH, params=params)
        except httpx.HTTPError as e:
            raise ApiError("network", str(e))
        return self._parse(r)
