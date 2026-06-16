"""Top-level utility module — THIN SHIM kept for backward compatibility.

The old `utils.py` mixed logging, metrics, browser helpers, and column
ordering. Logger/metrics/exceptions now live in `src.observability`. The
selenium helpers remain here until PR3 moves them to `src.core.browser`.

Existing imports like

    from ..utils import log, Timer, RateMeter, SessionExpired, ApiError,
                        human_click, random_sleep

keep working — they're re-exported below.
"""
import random
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Re-exports from the new observability layer
from .observability import (
    ApiError,
    RateMeter,
    SessionExpired,
    Timer,
    format_time_elapsed,
    log,
)


# --- HUMAN-LIKE BEHAVIORS ------------------------------------------------
# TODO(PR3): move to src/core/browser.py as internal helpers

def random_sleep(min_sec=0.5, max_sec=1.5):
    time.sleep(random.uniform(min_sec, max_sec))


def human_like_scroll(driver):
    for _ in range(3):
        driver.execute_script(f"window.scrollBy(0, {random.randint(100, 300)});")
        time.sleep(random.uniform(0.3, 0.8))
        if random.random() < 0.4:
            time.sleep(random.uniform(0.5, 1.2))


def human_type(element, text, min_delay=0.02, max_delay=0.08):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def random_mouse_movement(driver):
    try:
        driver.execute_script("""
            var event = new MouseEvent('mousemove', {
                'view': window, 'bubbles': true, 'cancelable': true,
                'clientX': Math.random() * window.innerWidth,
                'clientY': Math.random() * window.innerHeight
            });
            document.dispatchEvent(event);
        """)
    except Exception:
        pass


def human_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        random_sleep(0.3, 0.6)
    except Exception:
        pass
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).move_to_element(element).perform()
        random_sleep(0.2, 0.4)
    except Exception:
        pass
    random_mouse_movement(driver)
    if random.random() < 0.25:
        time.sleep(random.uniform(0.3, 0.9))
    random_sleep(0.2, 0.5)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)


def read_page_pause():
    time.sleep(random.uniform(2, 4))


def wait_for_loading_to_disappear(driver, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, "div.layui-layer-content.layui-layer-loading0")
            )
        )
        time.sleep(0.5)
    except Exception:
        pass
    return True


def is_pig_error(driver):
    """Check if we're on the 4003 error page (Chinese 'con heo')."""
    try:
        if "4003" in driver.title or "Page Expired" in driver.title:
            return True
        page_source = driver.page_source
        if "found me hiding here" in page_source or "Code: 4003" in page_source:
            return True
        if driver.find_elements(
            By.XPATH,
            "//a[@class='back-index' and contains(text(), '返回首页')]",
        ):
            return True
        if driver.find_elements(
            By.XPATH,
            "//a[contains(@onclick, 'window.location.reload()') and contains(text(), 'Refresh')]",
        ):
            return True
    except Exception:
        pass
    return False


def check_and_handle_419_error(driver):
    """Handle 419 (session expired) or 4003 (pig) error pages."""
    try:
        if is_pig_error(driver):
            log("🐷 Phát hiện lỗi 'con heo' (4003). Đang tiến hành refresh...", "WARNING")
            try:
                refresh_btns = driver.find_elements(
                    By.XPATH,
                    "//a[contains(@onclick, 'window.location.reload()') and contains(text(), 'Refresh')]",
                )
                if refresh_btns:
                    driver.execute_script("arguments[0].click();", refresh_btns[0])
                    time.sleep(3)
                    if not is_pig_error(driver):
                        return True
            except Exception:
                pass
            driver.refresh()
            time.sleep(5)
            return True

        title = driver.title
        if any(code in title for code in ["419", "Page Expired", "forbidden"]):
            log(f"Session error detected ({title}). Refreshing...", "WARNING")
            driver.refresh()
            time.sleep(5)
            return True
    except Exception:
        pass
    return False


# --- CANONICAL COLUMN ORDER FOR EXCEL OUTPUT -----------------------------
# TODO(PR4): move to src/parsing/normalizer.py

CANONICAL_COLUMN_ORDER = [
    # METADATA
    'page', 'stt', 'segment', 'bill_id',
    # WHEN
    'Transaction Date', 'Declaration No', 'Type of Import',
    # WHAT
    'HS Code', 'Product Description', 'Product Desc (EN)',
    # HOW MUCH
    'quantity', 'Quantity unit', 'Currency',
    'Unit Price(Currency)', 'Total Price(Currency)', 'Exchange Rate',
    'Unit Price(USD)', 'Amount',
    # WHO
    'Buyer', 'Buyer Name(EN)', 'Importer ID', 'Buyer Address(VN)', 'Buyer Tel',
    'Supplier', 'Country of Origin', 'Exporter Country',
    'Exporter Country Name', 'Supply Country',
    # HOW
    'Incoterms', 'Payment Method', 'Mode of Transport', 'Bill of Lading ID',
    # WHERE
    'Import Country', 'Customs Code', 'Customs Name',
    'Customs Br Code', 'Customs Br Name',
]


def reorder_columns(df, column_order=None):
    """Return df with columns ordered by `column_order` (unknowns appended)."""
    if column_order is None:
        column_order = CANONICAL_COLUMN_ORDER
    ordered = [c for c in column_order if c in df.columns]
    remaining = [c for c in df.columns if c not in column_order]
    return df[ordered + remaining]


__all__ = [
    # Re-exports from observability (backward-compat)
    "log", "Timer", "RateMeter", "SessionExpired", "ApiError",
    "format_time_elapsed",
    # Selenium helpers
    "random_sleep", "human_like_scroll", "human_type", "human_click",
    "random_mouse_movement", "read_page_pause",
    "wait_for_loading_to_disappear", "is_pig_error",
    "check_and_handle_419_error",
    # Column ordering
    "CANONICAL_COLUMN_ORDER", "reorder_columns",
]
