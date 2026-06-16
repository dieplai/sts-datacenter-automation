"""Click a "Details" link, capture the resulting XHR response via CDP.

The Ant Design drawer suppresses its own detail XHR if re-clicked while
still mounted, so we MUST close the drawer between rows. That's the whole
reason the close step exists and can't be optimized out.

Plan E findings baked in:
  - MouseDown+MouseUp+Click dispatch (React synthetic-event compatibility)
  - 0.7s pre-sleep (CDP log is batched ~300-500ms)
  - 0.4s post-close settle (Ant close animation ~300ms + React cleanup)
  - 3 retries, 0.5s between on hard error, 0.3s between on soft fail
"""
import json
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

try:
    from ..observability import log
except ImportError:  # pragma: no cover
    import os
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import log  # type: ignore


class DetailCapture:
    """Owns the click → CDP-capture → close lifecycle for a single driver."""

    _CLICK_JS = (
        "var el=arguments[0];"
        "el.scrollIntoView({block:'center'});"
        "['mousedown','mouseup','click'].forEach(function(t){"
        "  el.dispatchEvent(new MouseEvent(t,"
        "    {bubbles:true,cancelable:true,view:window,button:0}));"
        "});"
    )

    def __init__(self, driver):
        self.driver = driver
        # Request IDs we've already returned a body for. Chrome guarantees
        # unique requestId per session, so this is collision-free across
        # rows — clicking the SAME bill twice gets two distinct requestIds,
        # and a stale response from row N arriving during row N+1's poll
        # window is detected as "already consumed" → skipped.
        # (URL-level tracking was tried and dropped: same URL clicked at
        # different times across page refreshes is legitimate, so URL
        # dedup caused false-positive blocks → rows 15-18 failed capture
        # after SOFT recovery in the 2026-05-05 follow-up incident.)
        self._consumed_request_ids = set()

    # ---- public: the one-call API ----

    def click_and_capture(self, detail_link, row_num, max_retries=3):
        """Click `detail_link`, return the JSON `data` object, or None.

        The returned dict mirrors the server's `data` field, containing
        `detail` (the transaction) and `title` (the per-run schema).
        """
        for attempt in range(max_retries):
            try:
                self._flush_logs()
                self.driver.execute_script(self._CLICK_JS, detail_link)
                time.sleep(0.7 if attempt == 0 else 1.5)

                response_data = self._capture(timeout=3 if attempt == 0 else 6)
                if response_data:
                    detail = response_data.get("detail") or {}
                    if detail and len(detail) > 3:
                        self.close_drawer()
                        return response_data

                if (attempt + 1) < max_retries:
                    log(f"   ⚠️ Row {row_num} (Attempt {attempt+1}/{max_retries}): "
                        f"Capture failed, retrying...", "WARNING")

                self.close_drawer()
                time.sleep(0.3)

            except Exception as e:
                log(f"   ❌ Row {row_num} (Attempt {attempt+1}/{max_retries}) "
                    f"Error: {e}", "DEBUG")
                err = str(e)
                if any(x in err for x in (
                    "Max retries exceeded", "WinError 10061", "timed out",
                    "script timeout", "HTTPConnectionPool",
                )):
                    log("🚨 Fatal browser connection/timeout! Aborting row.", "ERROR")
                    return None
                self.close_drawer()
                time.sleep(0.5)

        return None

    def close_drawer(self):
        """Close Ant Design drawer. Click the X, fall back to ESC."""
        try:
            btn = self.driver.find_element(
                By.CSS_SELECTOR, "button.ant-drawer-close",
            )
            self.driver.execute_script("arguments[0].click();", btn)
        except Exception:
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
        time.sleep(0.4)

    # ---- internals ----

    def _flush_logs(self):
        try:
            _ = self.driver.get_log("performance")
        except Exception:
            pass

    def _capture(self, timeout=2):
        """Poll CDP performance logs for the next /api/..detail response.

        Skips responses we've already returned a body for (instance-wide
        URL + requestId tracking). Without that, a stale response arriving
        late in the next row's poll window would be returned as if it
        were the new row's response — the row 13/14 identical-data bug.
        """
        try:
            start = time.time()
            seen = set()

            while time.time() - start < timeout:
                try:
                    logs = self.driver.get_log("performance")
                    for entry in logs:
                        try:
                            msg = json.loads(entry["message"]).get("message", {})
                        except Exception:
                            continue
                        if msg.get("method") != "Network.responseReceived":
                            continue
                        resp = msg.get("params", {}).get("response", {})
                        url = resp.get("url", "")
                        if "/api/" not in url and "/detail" not in url.lower():
                            continue
                        rid = msg["params"]["requestId"]
                        if rid in seen:
                            continue
                        seen.add(rid)
                        # Cross-call dedup: skip requestIds we've already
                        # returned a body for. Chrome requestIds are
                        # unique per session, so this catches stale
                        # responses (row N's late XHR arriving in row N+1's
                        # poll) without false positives across rows.
                        if rid in self._consumed_request_ids:
                            continue
                        try:
                            body = self.driver.execute_cdp_cmd(
                                "Network.getResponseBody", {"requestId": rid},
                            )
                            body_json = json.loads(body["body"])
                            if body_json.get("state") == 0 and body_json.get("data"):
                                data = body_json["data"]
                                if data.get("detail"):
                                    self._consumed_request_ids.add(rid)
                                    return data
                        except Exception:
                            pass
                    time.sleep(0.03)
                except Exception:
                    time.sleep(0.03)
            return None
        except Exception:
            return None
