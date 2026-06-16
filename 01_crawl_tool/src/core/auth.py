"""pro.52wmb.com login flow — single canonical implementation.

Used by the scraper pipeline, the recon tool, and the benchmark harness.
Previously this logic was copy-pasted into `core_pro_detail.main_pro_detail`
and into `tools/recon_detail_request.do_login`; keeping one copy avoids
drift.

The function tries auto-fill with a short timeout; on failure (captcha,
anti-bot challenge, JS form not ready) it pauses at the terminal so the
operator can log in manually in the visible Chrome window and press Enter.
"""
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from .. import config
    from ..observability import log
except ImportError:  # pragma: no cover — run-as-script fallback
    import os
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config  # type: ignore
    from observability import log  # type: ignore


def login_pro(driver, auto_timeout=15):
    """Log into pro.52wmb.com. Returns True on success.

    Flow:
      1. Navigate to PRO_LOGIN_URL
      2. If already at /Workbenches → cached session, return True
      3. Try auto-fill username + password (up to `auto_timeout` s)
      4. On failure → prompt operator for manual login, wait for Enter
      5. Verify we're at /Workbenches
    """
    pro_login_url = getattr(
        config, "PRO_LOGIN_URL",
        "https://pro.52wmb.com/user/login?redirect=%2FWorkbenches",
    )
    log(f"📍 Navigating to Pro Login: {pro_login_url}", "INFO")
    driver.get(pro_login_url)
    time.sleep(3)

    if "/Workbenches" in driver.current_url:
        log("Already logged in", "SUCCESS")
        return True

    fast_wait = WebDriverWait(driver, auto_timeout)
    try:
        user_field = fast_wait.until(
            EC.element_to_be_clickable((By.ID, "username"))
        )
        user_field.click()
        time.sleep(0.3)
        user_field.clear()
        user_field.send_keys(config.USERNAME)
        time.sleep(0.5)

        pass_field = fast_wait.until(
            EC.element_to_be_clickable((By.ID, "password"))
        )
        pass_field.click()
        time.sleep(0.3)
        pass_field.clear()
        pass_field.send_keys(config.PASSWORD)
        time.sleep(1.5)

        submit_btn = fast_wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".login-button"))
        )
        try:
            submit_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", submit_btn)

        WebDriverWait(driver, 30).until(EC.url_contains("/Workbenches"))
        log("Login successful (auto)", "SUCCESS")
        return True

    except Exception as e:
        log(f"Auto-login failed ({type(e).__name__}); falling back to MANUAL",
            "WARNING")

    # Manual fallback — block terminal until operator signals login done
    print("\n" + "=" * 60)
    print("[!] MANUAL LOGIN required (captcha / anti-bot blocked auto-fill)")
    print("    Log in the browser, wait for URL to contain '/Workbenches',")
    print("    then press Enter here.")
    print("=" * 60)
    try:
        input("   [Press Enter once on Workbenches] > ")
    except EOFError:
        time.sleep(60)

    if "/Workbenches" in driver.current_url:
        log("Login successful (manual)", "SUCCESS")
        return True

    log(f"Still not on Workbenches: {driver.current_url}", "ERROR")
    return False
