"""Ant Design pagination controls for the Customs Data result table.

The functions here are kept as module-level operations on `(driver, wait)`.
The pipeline layer wires them to a ScraperProDetail instance; tooling can
call them directly without instantiating the big class.
"""
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

try:
    from ..observability import log
    from ..utils import human_click
    from ..scraper import api_client
except ImportError:  # pragma: no cover
    import os
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import log  # type: ignore
    from utils import human_click  # type: ignore
    from scraper import api_client  # type: ignore


def get_ui_pagination_progress(driver):
    """Return `(current_page, last_page, pct)` or `(None, None, None)`.

    Reads the active pagination item + the max-numbered item. Useful for
    progress logs so we don't have to trust the internal counter alone.
    """
    try:
        current_page = None
        try:
            active = driver.find_element(
                By.CSS_SELECTOR, "li.ant-pagination-item-active a",
            )
            current_page = int(active.text.strip().replace(",", ""))
        except Exception:
            pass

        last_page = None
        try:
            for el in driver.find_elements(
                By.CSS_SELECTOR, "li.ant-pagination-item a",
            ):
                try:
                    n = int(el.text.strip().replace(",", ""))
                    if last_page is None or n > last_page:
                        last_page = n
                except Exception:
                    pass
        except Exception:
            pass

        if current_page and last_page and last_page > 0:
            return current_page, last_page, (current_page / last_page) * 100
    except Exception:
        pass
    return None, None, None


def close_tips_modal(driver, wait):
    """Close the "Tips" / welcome modal or any blocking popup."""
    try:
        api_client.handle_popup(driver, wait, timeout=0.1)
    except Exception:
        pass
    return False


def has_next_page(driver):
    try:
        driver.find_element(
            By.XPATH,
            "//li[contains(@class, 'ant-pagination-next') "
            "and not(contains(@class, 'ant-pagination-disabled'))]",
        )
        return True
    except Exception:
        return False


def go_to_page(driver, wait, page_target):
    """Jump to a specific page using the 'Go to' input field."""
    try:
        log(f"🚀 Navigating to page {page_target}...", "PROCESS")
        try:
            jump_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".ant-pagination-options-quick-jumper input"),
            ))
        except Exception:
            jump_input = driver.find_element(
                By.XPATH, "//li[@class='ant-pagination-options']//input",
            )

        driver.execute_script("arguments[0].value = '';", jump_input)
        jump_input.send_keys(str(page_target))
        jump_input.send_keys(Keys.ENTER)
        time.sleep(1)

        start = time.time()
        while time.time() - start < 10:
            try:
                active = driver.find_element(
                    By.CSS_SELECTOR, "li.ant-pagination-item-active",
                )
                current = active.get_attribute("title") or active.text
                if str(current) == str(page_target):
                    log(f"✅ Successfully jumped to page {page_target}", "SUCCESS")
                    time.sleep(2.0)
                    api_client.wait_for_loading_overlay(driver, timeout=30)
                    time.sleep(3.5)
                    return True
            except Exception:
                pass
            time.sleep(0.5)

        log(f"⚠️ Verification failed: Could not confirm arrival at page {page_target}",
            "WARNING")
        return False
    except Exception as e:
        log(f"❌ Failed to go to page {page_target}: {e}", "ERROR")
        return False


def go_to_next_page(driver, wait, is_recovery=False, max_retries=3):
    """Click the "next" arrow with retry + popup handling + loading wait."""
    for attempt in range(max_retries):
        try:
            time.sleep(1)
            api_client.handle_popup(driver, wait)
            next_btn = driver.find_element(
                By.XPATH,
                "//li[contains(@class, 'ant-pagination-next') "
                "and not(contains(@class, 'ant-pagination-disabled'))]//a",
            )
            if is_recovery:
                driver.execute_script("arguments[0].click();", next_btn)
            else:
                human_click(driver, next_btn)
            time.sleep(2.0)
            api_client.wait_for_loading_overlay(driver, timeout=30)
            time.sleep(3.5)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                log(f"⚠️ go_to_next_page attempt {attempt+1} failed, retrying... "
                    f"({str(e)[:50]})", "WARNING")
                time.sleep(2)
                try:
                    api_client.handle_popup(driver, wait)
                    driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);"
                    )
                    time.sleep(1)
                except Exception:
                    pass
            else:
                log(f"⚠️ go_to_next_page failed after {max_retries} attempts", "WARNING")
                return False
