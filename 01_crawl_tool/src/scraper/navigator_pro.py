"""
Navigator Pro - New UI Flow for 52wmb.com Pro 2026
Handles the new navigation flow:
1. Login (reuse from old flow)
2. Click Trade Data (reuse from old flow)
3. Click "Access Pro 2026 →" button
4. Navigate to https://pro.52wmb.com/Workbenches
5. Click "Customer Development" menu item
"""

import sys
import time
import random
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Import from utils
try:
    from ..utils import (
        human_type, human_click, random_sleep,
        human_like_scroll, random_mouse_movement, log
    )
    from . import api_client
    from .. import config
except ImportError:
    def random_sleep(a, b): time.sleep(random.uniform(a, b))
    def human_click(d, e): d.execute_script("arguments[0].click();", e)
    def human_type(e, t, *args): e.send_keys(t)
    def human_like_scroll(d): pass
    def random_mouse_movement(d): pass
    def log(msg, level="INFO"): print(f"[{level}] {msg}")
    api_client = None
    import src.config as config


def wait_for_spinner(driver, timeout=30):
    """Wait for any Ant Design spinner (.ant-spin-spinning) to disappear."""
    try:
        if not driver.find_elements(By.CSS_SELECTOR, ".ant-spin-spinning"):
            return True
        log("⏳ Waiting for page loading to complete...", "DEBUG")
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".ant-spin-spinning"))
        )
        try:
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, ".ant-spin-container.ant-spin-blur"))
            )
        except Exception:
            pass
        log("✅ Page loading complete", "DEBUG")
        time.sleep(0.5)
        return True
    except Exception as e:
        log(f"⚠️ wait_for_spinner timeout or error: {e}", "WARNING")
        return False


def wait_for_loading_to_disappear(driver, wait, timeout=30):
    """
    Wait for loading spinner to disappear.
    
    The Pro 2026 UI shows a loading spinner with class 'ant-spin-spinning'
    when loading data. We need to wait for it to disappear before continuing.
    
    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait instance
        timeout: Maximum time to wait in seconds
    
    Returns:
        bool: True if loading disappeared, False if timeout
    """
    try:
        log("⏳ Waiting for loading spinner to disappear...", "DEBUG")
        start_time = time.time()
        
        # Wait for spinner to disappear
        while time.time() - start_time < timeout:
            try:
                # Check if spinner is still present and spinning
                spinner = driver.find_element(
                    By.CSS_SELECTOR,
                    ".ant-spin.ant-spin-spinning"
                )
                # If we found it, it's still loading
                time.sleep(0.5)
            except:
                # Spinner not found = loading complete
                log("✅ Loading complete", "DEBUG")
                time.sleep(0.5)  # Small buffer
                return True
        
        log(f"⚠️ Loading spinner did not disappear after {timeout}s", "WARNING")
        return False
        
    except Exception as e:
        log(f"⚠️ Error waiting for loading: {e}", "WARNING")
        return False


def wait_for_form_ready(driver, max_wait=60, check_interval=2):
    """
    Wait for the search form to be fully ready after a clear/reset operation.
    
    This function handles the common issue where dropdown elements become stale
    after clicking "All Clear" button. It waits for:
    1. Loading spinners to disappear
    2. Form container to be present
    3. All dropdown elements to be clickable
    4. Input fields to be interactable
    
    Args:
        driver: Selenium WebDriver
        max_wait: Maximum wait time in seconds (default: 60)
        check_interval: Time between checks in seconds (default: 2)
    
    Returns:
        bool: True if form is ready, False if timeout
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    log("⏳ Waiting for form to be fully ready...", "INFO")
    start_time = time.time()
    
    # Phase 1: Wait for loading spinner to disappear
    try:
        spinner_wait = WebDriverWait(driver, 15)
        spinner_wait.until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".ant-spin-spinning"))
        )
        log("✅ Phase 1: No loading spinner", "DEBUG")
    except:
        log("⚠️ Phase 1: Spinner wait timed out, proceeding...", "DEBUG")
    
    # Phase 2: Wait for form container to be present
    form_ready = False
    while time.time() - start_time < max_wait:
        try:
            # Check form container exists
            form_container = driver.find_element(By.CSS_SELECTOR, "div.searchforclass")
            if not form_container:
                time.sleep(check_interval)
                continue
            
            # Check all required elements are present and stable
            required_elements = [
                ("Country dropdown", "div.searchforclass div.ant-select"),
                ("Calendar picker", "input.ant-calendar-picker-input"),
                ("HS code input", "input[placeholder='HS code']"),
            ]
            
            all_present = True
            for name, selector in required_elements:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if not elements:
                        log(f"⏳ Waiting for {name}...", "DEBUG")
                        all_present = False
                        break
                except:
                    all_present = False
                    break
            
            if all_present:
                # Final check: Ensure dropdowns are not disabled/loading
                dropdowns = driver.find_elements(By.CSS_SELECTOR, "div.searchforclass div.ant-select")
                if len(dropdowns) >= 2:
                    # Check that dropdowns don't have loading class
                    dropdown_loading = any(
                        "ant-select-loading" in d.get_attribute("class") or ""
                        for d in dropdowns
                    )
                    if not dropdown_loading:
                        log("✅ Phase 2: Form container and elements ready", "DEBUG")
                        form_ready = True
                        break
            
        except Exception as e:
            log(f"⏳ Form not ready yet: {e}", "DEBUG")
        
        time.sleep(check_interval)
    
    if form_ready:
        # Phase 3: Small stability buffer
        time.sleep(1)
        log("✅ Form is fully ready for interaction", "SUCCESS")
        return True
    else:
        elapsed = time.time() - start_time
        log(f"⚠️ Form readiness check timed out after {elapsed:.1f}s", "WARNING")
        return False



def navigate_to_pro_2026(driver, wait):
    """
    Click "Access Pro 2026 →" button to navigate to Pro version.
    
    Expected button HTML:
    <a class="newNavigationClass6" 
       href="https://pro.52wmb.com/Workbenches?52wmb_token=8e7b0552f88b0604&lang=en" 
       target="_blank">Access Pro 2026 →</a>
    
    Returns:
        bool: True if successfully navigated to Pro 2026
    """
    try:
        log("📍 Navigating to Pro 2026...", "PROCESS")
        
        # Handle any popups before clicking
        if api_client:
            api_client.handle_popup(driver, wait, timeout=1)
        
        # Find the "Access Pro 2026 →" button
        # Try multiple selectors for robustness
        pro_button = None
        
        # Strategy 1: By class name
        try:
            pro_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "a.newNavigationClass6"))
            )
            log("✅ Found Pro 2026 button by class", "DEBUG")
        except:
            pass
        
        # Strategy 2: By text content
        if not pro_button:
            try:
                pro_button = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Access Pro 2026')]"))
                )
                log("✅ Found Pro 2026 button by text", "DEBUG")
            except:
                pass
        
        # Strategy 3: By href pattern
        if not pro_button:
            try:
                pro_button = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(@href, 'pro.52wmb.com/Workbenches')]"))
                )
                log("✅ Found Pro 2026 button by href", "DEBUG")
            except:
                pass
        
        if not pro_button:
            log("❌ Could not find Pro 2026 button", "ERROR")
            return False
        
        # Scroll to button
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", pro_button)
        time.sleep(0.5)
        
        # Capture handles before click (button opens in new tab)
        old_handles = driver.window_handles
        log(f"Current tabs before click: {len(old_handles)}", "DEBUG")
        
        # Click the button
        human_click(driver, pro_button)
        log("✅ Clicked Pro 2026 button", "DEBUG")
        time.sleep(2)  # Wait for new tab to open
        
        # Find and switch to the new Pro tab
        new_handles = driver.window_handles
        log(f"Current tabs after click: {len(new_handles)}", "DEBUG")
        
        pro_handle = None
        for handle in new_handles:
            if handle not in old_handles:
                driver.switch_to.window(handle)
                current_url = driver.current_url.lower()
                log(f"Checking new tab: {current_url}", "DEBUG")
                
                if "pro.52wmb.com" in current_url:
                    pro_handle = handle
                    break
        
        if pro_handle:
            driver.switch_to.window(pro_handle)
            driver.execute_script("window.focus();")
            log(f"✅ Navigated to Pro 2026: {driver.current_url}", "SUCCESS")
            
            # Handle any popups on new page
            if api_client:
                api_client.handle_popup(driver, wait, timeout=2)
            
            random_sleep(1, 2)
            return True
        else:
            log("❌ Could not find Pro 2026 tab", "ERROR")
            return False
            
    except Exception as e:
        log(f"❌ Failed to navigate to Pro 2026: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def click_customer_development(driver, wait):
    """
    Click "Customer Development" menu item on Pro 2026 page.
    
    Expected HTML:
    <li role="menuitem" class="ant-menu-item" style="position: relative;">
        Customer Development
        <span class="red-dot" style="..."></span>
    </li>
    
    Returns:
        bool: True if successfully clicked
    """
    try:
        log("📍 Clicking Customer Development menu...", "PROCESS")
        
        # Verify we're on Pro page
        current_url = driver.current_url.lower()
        if "pro.52wmb.com" not in current_url:
            log(f"⚠️ Not on Pro page. Current URL: {current_url}", "WARNING")
            return False
        
        # Handle any popups
        if api_client:
            api_client.handle_popup(driver, wait, timeout=1)
        
        # Wait for page to load
        time.sleep(1)
        
        # Find the "Customer Development" menu item
        menu_item = None
        
        # Strategy 1: By exact text match
        try:
            menu_item = wait.until(
                EC.element_to_be_clickable((
                    By.XPATH, 
                    "//li[@role='menuitem' and contains(@class, 'ant-menu-item') and contains(text(), 'Customer Development')]"
                ))
            )
            log("✅ Found Customer Development by exact text", "DEBUG")
        except:
            pass
        
        # Strategy 2: By partial text (more flexible)
        if not menu_item:
            try:
                menu_item = wait.until(
                    EC.element_to_be_clickable((
                        By.XPATH, 
                        "//li[contains(@class, 'ant-menu-item') and contains(., 'Customer Development')]"
                    ))
                )
                log("✅ Found Customer Development by partial text", "DEBUG")
            except:
                pass
        
        # Strategy 3: By class and position (if text changes)
        if not menu_item:
            try:
                # Find all menu items and look for the one with "Customer Development"
                menu_items = driver.find_elements(By.CSS_SELECTOR, "li.ant-menu-item")
                for item in menu_items:
                    if "customer development" in item.text.lower():
                        menu_item = item
                        log("✅ Found Customer Development by iteration", "DEBUG")
                        break
            except:
                pass
        
        if not menu_item:
            log("❌ Could not find Customer Development menu item", "ERROR")
            # Save screenshot for debugging
            try:
                driver.save_screenshot("debug_screenshots/customer_dev_not_found.png")
                log("📸 Screenshot saved: debug_screenshots/customer_dev_not_found.png", "DEBUG")
            except:
                pass
            return False
        
        # Scroll to menu item
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", menu_item)
        time.sleep(0.5)
        
        # Click the menu item
        human_click(driver, menu_item)
        log("✅ Clicked Customer Development menu", "SUCCESS")
        time.sleep(2)  # Wait for page to load
        
        # Handle any popups after click
        if api_client:
            api_client.handle_popup(driver, wait, timeout=1)
        
        # Verify navigation (URL might change or content loads)
        log(f"Current URL after click: {driver.current_url}", "DEBUG")
        
        return True
        
    except Exception as e:
        log(f"❌ Failed to click Customer Development: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def click_market_analysis(driver, wait):
    """
    Click "Market Analysis" menu item on Pro 2026 page (for detail mode).
    
    Expected HTML:
    <li role="menuitem" class="ant-menu-item" style="position: relative;">
        Market Analysis
        <span class="red-dot" style="..."></span>
    </li>
    
    Returns:
        bool: True if successfully clicked
    """
    try:
        log("📍 Clicking Market Analysis menu...", "PROCESS")
        
        # Verify we're on Pro page
        current_url = driver.current_url.lower()
        if "pro.52wmb.com" not in current_url:
            log(f"⚠️ Not on Pro page. Current URL: {current_url}", "WARNING")
            return False
        
        # Handle any popups
        if api_client:
            api_client.handle_popup(driver, wait, timeout=1)
        
        # Wait for page to load
        time.sleep(1)
        
        # Find the "Market Analysis" menu item
        menu_item = None
        
        # Strategy 1: By exact text match
        try:
            menu_item = wait.until(
                EC.element_to_be_clickable((
                    By.XPATH, 
                    "//li[@role='menuitem' and contains(@class, 'ant-menu-item') and contains(text(), 'Market Analysis')]"
                ))
            )
            log("✅ Found Market Analysis by exact text", "DEBUG")
        except:
            pass
        
        # Strategy 2: By partial text (more flexible)
        if not menu_item:
            try:
                menu_item = wait.until(
                    EC.element_to_be_clickable((
                        By.XPATH, 
                        "//li[contains(@class, 'ant-menu-item') and contains(., 'Market Analysis')]"
                    ))
                )
                log("✅ Found Market Analysis by partial text", "DEBUG")
            except:
                pass
        
        # Strategy 3: By class and position (if text changes)
        if not menu_item:
            try:
                # Find all menu items and look for the one with "Market Analysis"
                menu_items = driver.find_elements(By.CSS_SELECTOR, "li.ant-menu-item")
                for item in menu_items:
                    if "market analysis" in item.text.lower():
                        menu_item = item
                        log("✅ Found Market Analysis by iteration", "DEBUG")
                        break
            except:
                pass
        
        if not menu_item:
            log("❌ Could not find Market Analysis menu item", "ERROR")
            # Save screenshot for debugging
            try:
                driver.save_screenshot("debug_screenshots/market_analysis_not_found.png")
                log("📸 Screenshot saved: debug_screenshots/market_analysis_not_found.png", "DEBUG")
            except:
                pass
            return False
        
        # Scroll to menu item
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", menu_item)
        time.sleep(0.5)
        
        # Click the menu item
        human_click(driver, menu_item)
        log("✅ Clicked Market Analysis menu", "SUCCESS")
        time.sleep(2)  # Wait for page to load
        
        # Handle any popups after click
        if api_client:
            api_client.handle_popup(driver, wait, timeout=1)
        
        # Verify navigation (URL might change or content loads)
        log(f"Current URL after click: {driver.current_url}", "DEBUG")
        
        return True
        
    except Exception as e:
        log(f"❌ Failed to click Market Analysis: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def click_customs_data(driver, wait):
    """
    Click "Customs Data" link in sidebar (for detail mode).
    
    Expected HTML:
    <a data-v-2550eb93="" href="/CustomsData" class="menu-link fontw">
        <i data-v-2550eb93="" aria-label="icon: database" class="anticon anticon-database">...</i>
        Customs Data
    </a>
    
    Returns:
        bool: True if successfully clicked
    """
    try:
        log("📍 Clicking Customs Data link...", "PROCESS")
        
        # Strategy: Multi-attempt click with popup handling
        for attempt in range(5):
            # Handle any popups BEFORE clicking
            if api_client:
                api_client.handle_popup(driver, wait, timeout=0.5)
            
            # Find the "Customs Data" link
            customs_link = None
            
            # Strategy 1: By href
            try:
                customs_link = wait.until(
                    EC.presence_of_element_located((
                        By.CSS_SELECTOR,
                        "a.menu-link[href='/CustomsData']"
                    ))
                )
            except:
                pass
            
            # Strategy 2: By text content
            if not customs_link:
                try:
                    customs_link = driver.find_element(By.XPATH, "//a[contains(@class, 'menu-link') and contains(., 'Customs Data')]")
                except:
                    pass
            
            if not customs_link:
                log(f"⚠️ Attempt {attempt+1}: Could not find Customs Data link", "DEBUG")
                time.sleep(1)
                continue
            
            # Click the link
            try:
                # Scroll to link
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", customs_link)
                time.sleep(0.3)
                human_click(driver, customs_link)
                log(f"✅ Attempt {attempt+1}: Clicked Customs Data link", "DEBUG")
                time.sleep(2)
            except:
                continue
            
            # Handle any popups after click
            if api_client:
                api_client.handle_popup(driver, wait, timeout=0.5)
            
            # Verify navigation
            if "/customsdata" in driver.current_url.lower():
                log("✅ Successfully navigated to Customs Data page", "SUCCESS")
                return True
            
            log(f"⚠️ Attempt {attempt+1}: URL did not change. Retrying...", "WARNING")
            time.sleep(1)
            
        log("❌ Failed to navigate to Customs Data after 5 attempts", "ERROR")
        return False
        
    except Exception as e:
        log(f"❌ Failed to click Customs Data: {e}", "ERROR")
        return False



def navigate_from_home_pro(driver, wait, pro_mode=None):
    """
    Complete navigation flow for Pro 2026:
    1. Go to home page (reuse existing login if needed)
    2. Navigate to Trade Data (reuse existing function)
    3. Click "Access Pro 2026 →" button
    4. Click menu based on pro_mode:
       - "fast": Customer Development (company list scraping)
       - "detail": Market Analysis (detailed market data)
    
    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait instance
        pro_mode: str - "fast" or "detail" (defaults to config.PRO_MODE)
    
    Returns:
        bool: True if navigation successful
    """
    try:
        # Determine mode
        if pro_mode is None:
            pro_mode = config.PRO_MODE
        
        log(f"🚀 Starting Pro 2026 navigation flow (mode: {pro_mode})...", "PROCESS")
        
        # Check if we are on Pro domain
        if "pro.52wmb.com" not in driver.current_url.lower():
             log("⚠️ Not on Pro domain? Attempting repair...", "WARNING")
             driver.get("https://pro.52wmb.com/Workbenches")
             time.sleep(3)
             
        log("✅ Verified on Pro 2026 domain", "SUCCESS")
        
        # Step 4: Click menu based on mode
        if pro_mode == "fast":
            log("📍 Step 4: Opening Customer Development (fast mode)...", "INFO")
            if not click_customer_development(driver, wait):
                log("❌ Failed to open Customer Development", "ERROR")
                return False
        elif pro_mode == "detail":
            log("📍 Step 4: Opening Customs Data (detail mode)...", "INFO")
            # Direct Navigation to avoid UI layout changes breaking clicks
            driver.get("https://pro.52wmb.com/CustomsData")
            time.sleep(3)
            
            # Post-navigation popup handling
            if hasattr(api_client, 'handle_popup'):
                api_client.handle_popup(driver, wait, timeout=2)
                
            if "/customsdata" not in driver.current_url.lower():
                log(f"❌ Failed to reach Customs Data. Current URL: {driver.current_url}", "ERROR")
                return False
        else:
            log(f"❌ Invalid pro_mode: {pro_mode}. Must be 'fast' or 'detail'", "ERROR")
            return False
        
        log(f"✅ Pro 2026 navigation flow complete (mode: {pro_mode})!", "SUCCESS")
        return True
        
    except Exception as e:
        log(f"❌ Pro 2026 navigation flow failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False
def fill_search_form_pro(driver, wait, hs_code):
    """
    Fill search form on Pro 2026 Customer Development page (HS Code only).
    
    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait instance
        hs_code: str - HS code to search for
    
    Returns:
        bool: True if form filled successfully
    """
    try:
        log(f"📝 Filling Pro 2026 search form (HS: {hs_code})...", "PROCESS")
        
        # Handle popups
        if api_client:
            api_client.handle_popup(driver, wait, timeout=1)
        
        time.sleep(0.5)
        
        # Step 1: Click "HS Code" radio button (value="3") - check if already selected
        log("Step 1: Selecting HS Code search type...", "DEBUG")
        try:
            # Check if HS Code is already selected
            hs_radio = driver.find_element(
                By.XPATH,
                "//input[@type='radio' and @value='3']"
            )
            
            # Check if already checked
            parent_label = hs_radio.find_element(By.XPATH, "./ancestor::label")
            is_checked = "ant-radio-button-wrapper-checked" in parent_label.get_attribute("class")
            
            if not is_checked:
                driver.execute_script("arguments[0].click();", parent_label)
                log("✅ Selected HS Code search type", "DEBUG")
                time.sleep(0.5)
            else:
                log("✅ HS Code already selected", "DEBUG")
        except Exception as e:
            log(f"⚠️ Could not select HS Code type: {e}", "WARNING")
            # Continue anyway - might already be selected
        
        # Step 2: Fill HS code into search input
        log(f"Step 2: Filling HS code: {hs_code}...", "DEBUG")
        try:
            # Find the search input field
            search_input = wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "input.ant-input.ant-input-lg[placeholder='Please enter...']"
                ))
            )
            
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_input)
            time.sleep(0.3)
            
            search_input.clear()
            human_type(search_input, hs_code)
            time.sleep(0.5)
            
            log(f"✅ Filled HS code: {hs_code}", "DEBUG")
        except Exception as e:
            log(f"❌ Could not fill HS code: {e}", "ERROR")
            return False
            
        log("✅ Pro 2026 search form filled successfully", "SUCCESS")
        return True
        
    except Exception as e:
        log(f"❌ Failed to fill Pro 2026 search form: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def click_search_button_pro(driver, wait):
    """
    Click the Search button on Pro 2026 page.
    
    Returns:
        bool: True if clicked successfully (Total count is retrieved separately now)
    """
    try:
        log("🔍 Clicking Search button...", "SEARCH")
        
        # Handle popups
        if api_client:
            api_client.handle_popup(driver, wait, timeout=1)
        
        time.sleep(0.5)
        
        # Find and click the Search button
        search_button = wait.until(
            EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                "button.ant-btn.ant-btn-primary.ant-btn-lg.ant-input-search-button"
            ))
        )
        
        human_click(driver, search_button)
        log("✅ Clicked Search button", "DEBUG")
        
        # Wait for loading to complete
        wait_for_loading_to_disappear(driver, wait, timeout=30)
        time.sleep(2) # Initial wait after search
        
        return True
        
    except Exception as e:
        log(f"❌ Failed to click Search button: {e}", "ERROR")
        return False

def select_vietnam_filter(driver, wait):
    """
    Select "Vietnam" country filter on the result page.
    """
    log("🌍 Selecting Vietnam filter...", "PROCESS")
    try:
        # Wait for loading to disappear first to ensure UI is ready
        wait_for_loading_to_disappear(driver, wait, timeout=10)
        
        vietnam_selected = False
        
        # Strategy 1: Direct value match
        try:
            vietnam_radio = driver.find_element(
                By.XPATH,
                "//input[@type='radio' and @value='Vietnam']"
            )
            parent_label = vietnam_radio.find_element(By.XPATH, "./ancestor::label")
            
            # Check if already checked
            if "ant-radio-button-wrapper-checked" in parent_label.get_attribute("class"):
                log("✅ Vietnam already selected", "DEBUG")
                vietnam_selected = True
            else:
                driver.execute_script("arguments[0].click();", parent_label)
                log("✅ Clicked Vietnam radio button", "DEBUG")
                vietnam_selected = True
                
        except Exception as e:
            # Strategy 2: Label text match
            try:
                vietnam_label = driver.find_element(
                    By.XPATH,
                    "//label[contains(@class, 'ant-radio-button-wrapper') and contains(., 'Vietnam')]"
                )
                if "ant-radio-button-wrapper-checked" in vietnam_label.get_attribute("class"):
                    log("✅ Vietnam already selected", "DEBUG")
                    vietnam_selected = True
                else:
                    driver.execute_script("arguments[0].click();", vietnam_label)
                    log("✅ Clicked Vietnam label", "DEBUG")
                    vietnam_selected = True
            except:
                log(f"⚠️ Could not find Vietnam filter option: {e}", "WARNING")
        
        if vietnam_selected:
            # Wait for reload
            wait_for_loading_to_disappear(driver, wait, timeout=30)
            time.sleep(2)
            return True
            
        return False
        
    except Exception as e:
        log(f"❌ Failed to select Vietnam filter: {e}", "ERROR")
        return False


def select_date_sort(driver, wait):
    """
    Select "Date" sorting (last_trade_date) on the result page.
    """
    log("📅 Selecting Date sorting...", "PROCESS")
    try:
        # Wait for loading
        wait_for_loading_to_disappear(driver, wait, timeout=10)
        
        date_selected = False
        
        try:
            # Find the "Date" radio button (value="last_trade_date")
            date_radio = driver.find_element(
                By.XPATH,
                "//input[@type='radio' and @value='last_trade_date']"
            )
            
            parent_label = date_radio.find_element(By.XPATH, "./ancestor::label")
            
            # Check if already checked
            if "ant-radio-button-wrapper-checked" in parent_label.get_attribute("class"):
                log("✅ Date sorting already selected", "DEBUG")
                date_selected = True
            else:
                driver.execute_script("arguments[0].click();", parent_label)
                log("✅ Clicked Date sorting", "DEBUG")
                date_selected = True
                
        except Exception as e:
            log(f"⚠️ Could not find Date sorting option: {e}", "WARNING")
            
        if date_selected:
            # Wait for reload
            wait_for_loading_to_disappear(driver, wait, timeout=30)
            time.sleep(2)
            return True
            
        return False
        
    except Exception as e:
        log(f"❌ Failed to select Date sorting: {e}", "ERROR")
        return False


def get_total_companies(driver, wait):
    """
    Extract the total number of companies from the result page.
    """
    try:
        # Wait a bit for DOM to settle
        time.sleep(2)
        
        # Look for the "companies29743668" text pattern
        # Update XPath to be more robust if needed
        total_element = driver.find_element(By.XPATH, "//div[contains(text(), 'companies')]")
        total_text = total_element.text
        
        import re
        match = re.search(r'companies(\d+)', total_text)
        if match:
            total = int(match.group(1))
            log(f"✅ Found total companies: {total:,}", "SUCCESS")
            return total
            
    except Exception as e:
        log(f"⚠️ Could not extract total companies count: {e}", "WARNING")
    
    return None


def clear_search_form_detail(driver, wait):
    """
    Clear/reset the search form on Detail Mode.
    Clicks the 'All clear' button to clear all form fields.
    
    Used between batch searches in multi mode to start fresh.
    Uses robust wait_for_form_ready() to ensure form is stable after clearing.
    
    Returns:
        bool: True if form was cleared and ready for filling
    """
    try:
        log("🔄 Clearing search form... (Short timeout)", "INFO")
        
        # Lower timeout to fail fast if button not clickable
        short_wait = WebDriverWait(driver, 5)
        
        reset_button = short_wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(@class, 'ant-btn') and .//span[contains(text(), 'All clear')]]"
            ))
        )
        
        human_click(driver, reset_button)
        
        # ============================================================
        # ROBUST WAIT: Use wait_for_form_ready() for stable form state
        # Reduced max_wait from 60 to 5 to avoid hanging
        # ============================================================
        if wait_for_form_ready(driver, max_wait=5, check_interval=1):
            log("✅ Search form cleared and ready", "SUCCESS")
            return True
        else:
            # Fallback instead of proceeding with dirty state
            raise Exception("Form readiness check timed out after clear.")
        
    except Exception as e:
        log(f"⚠️ Could not clear search form nicely: {e}", "WARNING")
        # Try alternative: just refresh the page
        try:
            log("🔄 Refreshing page as fallback...", "INFO")
            driver.refresh()
            time.sleep(3)
            # Short wait after refresh
            wait_for_form_ready(driver, max_wait=10)
            log("✅ Page refreshed as fallback", "SUCCESS")
            return True
        except Exception as refresh_err:
            log(f"❌ Page refresh also failed: {refresh_err}", "ERROR")
            return False


def fill_search_form_detail(driver, wait, end_date_override=None, batch_config=None):
    """
    Simplified, robust form filling flow for Detail Mode.
    
    Flow:
    1. Select Country (Vietnam)
    2. Loop (max 3 attempts):
       a. Select Data Type (Import/Export)
       b. Fill Dates (Start & End)
       c. CHECK INTERFERENCE: If "Report Label" became active (autofilled info), 
          click it to deactivate and RESTART loop (Step 2a).
    3. Fill remaining fields (HS Code, Product, etc.)
    
    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait
        end_date_override: Optional end date override (for segmentation)
        batch_config: Optional batch config dict
    """
    try:
        log("🚀 Filling Detail Mode search form...", "PROCESS")
        
        # 0. Get Config Values
        country_idx = 0
        datatype_idx = 1
        
        target_country = getattr(config, 'DETAIL_COUNTRY', 'Vietnam')
        
        # Determine Data Type
        target_data_type = getattr(config, 'DETAIL_DATA_TYPE', 'Export data')
        if batch_config and batch_config.get('data_type'):
            target_data_type = batch_config['data_type']
            
        # Determine Dates (batch_config takes priority over config vars)
        start_date = (batch_config.get('start_date') if batch_config else None) or getattr(config, 'DETAIL_START_DATE', '2024-01-01')
        end_date = end_date_override if end_date_override else ((batch_config.get('end_date') if batch_config else None) or getattr(config, 'DETAIL_END_DATE', None))
        
        # --- Helper for checking interference ---
        def check_and_fix_interference():
            """
            Check if a Report Label is active. If so, click it to deactivate.
            Returns True if interference was found and fixed.
            """
            try:
                # Debug: Check structure of Report Label section
                report_section = driver.find_elements(By.CSS_SELECTOR, "div.screenclass")
                if not report_section:
                    # Maybe it's not loaded or selector is wrong?
                    # Try finding by text "Report Label" to be sure
                    try:
                        report_header = driver.find_element(By.XPATH, "//div[contains(text(), 'Report Label')]")
                        log("⚠️ Debug: Found 'Report Label' text but 'div.screenclass' selector failed?", "DEBUG")
                    except:
                        pass
                
                # Look for ANY labels to verify basic selector
                all_labels = driver.find_elements(By.CSS_SELECTOR, "div.screenclass label.ant-radio-button-wrapper")
                
                # Look for ACTIVE labels
                active_labels = driver.find_elements(By.CSS_SELECTOR, "div.screenclass label.ant-radio-button-wrapper-checked")
                
                if active_labels:
                    log(f"⚠️ DETECTED INTERFERENCE: Found {len(active_labels)} active label(s)!", "WARNING")
                    log("   -> Action: Deactivating label and restarting fill from Data Type.", "WARNING")
                    
                    # Click to deactivate (toggle off)
                    human_click(driver, active_labels[0])
                    time.sleep(2) # Wait for UI update/reset
                    return True
                
                # Debug logging if no interference found but labels exist
                if len(all_labels) > 0:
                    log(f"ℹ️ Debug: {len(all_labels)} Report Labels found. Checking deep state...", "DEBUG")
                    for i, label in enumerate(all_labels):
                        class_attr = label.get_attribute("class")
                        
                        # Check deep: Is the input inside actually checked?
                        is_input_checked = False
                        try:
                            input_el = label.find_element(By.TAG_NAME, "input")
                            is_input_checked = input_el.is_selected()
                        except:
                            pass
                            
                        log(f"   Label {i+1}: Class='{class_attr}', Input Checked={is_input_checked}", "DEBUG")
                        
                        # Fallback check: if 'checked' is in class text OR input is selected
                        if ("checked" in class_attr or is_input_checked) and label not in active_labels:
                            log(f"   ⚠️ WARNING: Label {i+1} IS ACTIVE (Class: {'checked' in class_attr}, Input: {is_input_checked})", "WARNING")
                            human_click(driver, label)
                            time.sleep(2)
                            return True
                    log("ℹ️ Debug: No labels considered active after deep check.", "DEBUG")
                else:
                    # Only log warning if we genuinely can't find the section, as it might be hidden intentionally
                    log("ℹ️ Debug: No Report Labels found (Section hidden or empty?)", "DEBUG")
                    pass

                return False
            except Exception as e:
                log(f"⚠️ Error checking interference: {e}", "WARNING")
                return False

        # ============================================================
        # STEP 1: Select Country (Vietnam)
        # ============================================================
        # ============================================================
        # STEP 1: Select Country (Vietnam)
        # ============================================================
        log(f"Step 1: Selecting country: {target_country}...", "INFO")
        if not select_dropdown_with_retry(driver, wait, country_idx, target_country):
            log("❌ Failed to select country", "ERROR")
            return False
            
        # ============================================================
        # LOOP: Data Type -> Date -> Check Interference
        # We loop here because if interference happens, we restart this block.
        # ============================================================
        max_attempts = 3
        
        for attempt in range(max_attempts):
            log(f"🔄 Form Fill Loop (Attempt {attempt+1}/{max_attempts})", "DEBUG")
            
            # Stabilization
            wait_for_loading_to_disappear(driver, wait, timeout=5)
            
            # STEP 2: Select Data Type
            log(f"Step 2: Selecting data type: {target_data_type}...", "INFO")
            if not select_dropdown_with_retry(driver, wait, datatype_idx, target_data_type):
                log("❌ Failed to select data type", "ERROR")
                return False
            
            # STEP 3: Fill Date (Only if we have dates)
            if start_date or end_date:
                # Ensure we pass the correct arguments: (driver, wait, start_date, end_date)
                # end_date_override (boundary date) takes precedence for the End Date field
                fill_end = end_date_override if end_date_override else end_date
                
                log(f"Step 3: Filling dates ({start_date or 'N/A'} - {fill_end or 'Now'})...", "INFO")
                if not _fill_date_simple(driver, wait, start_date, fill_end):
                    log("⚠️ Date fill had issues, but continuing...", "WARNING")
                
                # Force close any calendar popup that might be left hovering
                try:
                    safe = driver.find_element(By.CSS_SELECTOR, "div.textclass")
                    driver.execute_script("arguments[0].click();", safe)
                except:
                    driver.execute_script("document.body.click();")
                time.sleep(1)
            
            # STEP 4: Check for Interference
            # Two types:
            # A) Explicit: Label is Active
            # B) Implicit: Data Type changed (Label activated then deactivated, leaving dirty data)
            
            # Wait a moment for any auto-selection
            time.sleep(2) 
            
            interference_type = None
            
            # Check A: Label Active
            if check_and_fix_interference():
                interference_type = "Explicit (Label Active)"
            
            # Check B: Data Type Mismatch
            # (Only check if we didn't already find explicit interference, 
            #  because explicit fix restarts loop anyway)
            if not interference_type:
                try:
                    # Quick check of current Data Type value
                    dt_dropdowns = driver.find_elements(By.CSS_SELECTOR, "div.searchforclass div.ant-select")
                    if len(dt_dropdowns) > 1:
                        current_dt_text = dt_dropdowns[1].text.strip() # Index 1 is Data Type
                        if target_data_type.lower() not in current_dt_text.lower():
                            interference_type = f"Implicit (Data Type Changed to '{current_dt_text}')"
                            log(f"⚠️ Data Type mismatch detected! Expected '{target_data_type}', found '{current_dt_text}'", "WARNING")
                except:
                    pass

            if interference_type:
                log(f"🔄 Interference detected ({interference_type}). Cleaning dirty fields and restarting...", "PROCESS")
                
                # CLEANUP: The label likely filled HS Code/Product. Clear them.
                try:
                    log("🧹 Cleaning potentially dirty fields (HS Code, Product)...", "DEBUG")
                    clean_fields = ["HS code", "Product Descr", "Product"]
                    for ph in clean_fields:
                        try:
                            inp = driver.find_element(By.XPATH, f"//input[@placeholder='{ph}']")
                            inp.clear()
                            # Ensure empty
                            human_type(inp, "") 
                        except:
                            pass
                except Exception as e:
                    log(f"⚠️ Cleanup failed: {e}", "WARNING")
                
                continue # Loop back to Step 2 (Select Data Type)
            
            # If we get here, no interference detected
            break
        
        # ============================================================
        # STEP 5: Fill Other Fields (Only if no configured)
        # ============================================================
        
        # HS Code
        hs_code = batch_config.get('hs_code') if batch_config else getattr(config, 'DETAIL_HS_CODE', '')
        if hs_code:
            log(f"Step 5a: Filling HS Code: {hs_code}", "INFO")
            fill_input_field_simple(driver, wait, "HS code", hs_code)
            
        # Product Description
        product = batch_config.get('product') if batch_config else getattr(config, 'DETAIL_PRODUCT', '')
        if product:
            log(f"Step 5b: Filling Product: {product}", "INFO")
            fill_input_field_simple(driver, wait, "Product", product)
            
        # Buyer / Supplier (depends on config)
        supplier = batch_config.get('supplier') if batch_config else getattr(config, 'DETAIL_SUPPLIER', '')
        if supplier:
            log(f"Step 5c: Filling Supplier: {supplier}", "INFO")
            fill_input_field_simple(driver, wait, "Supplier", supplier, element_id_override="seller") # ID might be 'seller'
            
        buyer = batch_config.get('buyer') if batch_config else getattr(config, 'DETAIL_BUYER', '')
        if buyer:
            log(f"Step 5d: Filling Buyer: {buyer}", "INFO")
            fill_input_field_simple(driver, wait, "Buyer", buyer)
            
        # Other optional fields (single mode only from config)
        if not batch_config:
            bill_number = getattr(config, 'DETAIL_BILL_NUMBER', '')
            if bill_number:
                fill_input_field_simple(driver, wait, "Bill number", bill_number)
                
            buyer_country = getattr(config, 'DETAIL_BUYER_COUNTRY', '')
            if buyer_country:
                fill_input_field_simple(driver, wait, "Buyer country", buyer_country)
                
            pol = getattr(config, 'DETAIL_POL', '')
            if pol:
                fill_input_field_simple(driver, wait, "POL", pol)
                
            pod = getattr(config, 'DETAIL_POD', '')
            if pod:
                fill_input_field_simple(driver, wait, "POD", pod)
                
            shipping_method = getattr(config, 'DETAIL_SHIPPING_METHOD', '')
            if shipping_method:
                # Based on field.html, the placeholder is "Shipping methods"
                fill_input_field_simple(driver, wait, "Shipping methods", shipping_method)

        # Qty / Amount filters: batch_config takes priority, falls back to global config
        min_qty = (batch_config.get('min_qty') if batch_config else None) or getattr(config, 'DETAIL_MIN_QTY', None)
        if min_qty is not None and str(min_qty).strip() != "":
            fill_input_field_simple(driver, wait, "Minimum qty", min_qty)
            
        max_qty = (batch_config.get('max_qty') if batch_config else None) or getattr(config, 'DETAIL_MAX_QTY', None)
        if max_qty is not None and str(max_qty).strip() != "":
            fill_input_field_simple(driver, wait, "Maximum qty", max_qty)
            
        min_amount = (batch_config.get('min_amount') if batch_config else None) or getattr(config, 'DETAIL_MIN_AMOUNT', None)
        if min_amount is not None and str(min_amount).strip() != "":
            fill_input_field_simple(driver, wait, "Minimum amount", min_amount)
            
        max_amount = (batch_config.get('max_amount') if batch_config else None) or getattr(config, 'DETAIL_MAX_AMOUNT', None)
        if max_amount is not None and str(max_amount).strip() != "":
            fill_input_field_simple(driver, wait, "Maximum amount", max_amount)
            
        min_uusd = (batch_config.get('min_uusd') if batch_config else None) or getattr(config, 'DETAIL_MIN_UUSD', None)
        if min_uusd is not None and str(min_uusd).strip() != "":
            fill_input_field_simple(driver, wait, "Minimum uusd", min_uusd)
            
        max_uusd = (batch_config.get('max_uusd') if batch_config else None) or getattr(config, 'DETAIL_MAX_UUSD', None)
        if max_uusd is not None and str(max_uusd).strip() != "":
            fill_input_field_simple(driver, wait, "Maximum uusd", max_uusd)
        
        # ============================================================
        # STEP 6: FORM AUDIT - Verify critical fields actually stuck
        # Reads back UI state; returns False if critical field is wrong.
        # ============================================================
        time.sleep(0.5)  # Let React reconcile
        
        form_ok = True
        
        # --- Verify HS Code (critical) ---
        # EXACT match only. '52' in '552' is True but they query different
        # data — using `in` was masking the bug where send_keys appended
        # to existing field state and the second fill produced '552'.
        if hs_code:
            try:
                # Use the same fuzzy/validated finder as fill_input_field_simple
                # so audit can't be tricked by a hidden duplicate that the
                # exact-XPath happened to find first. Pure exact-XPath was
                # also failing entirely (no such element) when the search
                # form was wrapped in a panel reorder, silently passing audit.
                hs_input = _find_input_by_placeholder_fuzzy(driver, "HS code")
                if hs_input is None:
                    log("❌ FORM AUDIT FAILED: HS Code input not found (or "
                        "all candidates rejected as hidden/non-Ant). "
                        "Treating as fill failure.", "ERROR")
                    form_ok = False
                else:
                    actual_hs = (hs_input.get_attribute('value') or '').strip()
                    expected_hs = str(hs_code).strip()
                    if actual_hs != expected_hs:
                        log(f"❌ FORM AUDIT FAILED: HS Code expected '{expected_hs}' (exact), "
                            f"UI shows '{actual_hs}'", "ERROR")
                        form_ok = False
                    else:
                        log(f"✅ FORM AUDIT: HS Code OK → '{actual_hs}'", "DEBUG")
            except Exception as audit_err:
                # Read failure when we EXPECT a value is a hard fail —
                # silently passing here let the scraper click Search with
                # an unfilled HS filter, returning all-HS data and
                # tripping the date-conflict guard.
                log(f"❌ FORM AUDIT FAILED: Could not read HS Code field: "
                    f"{audit_err}", "ERROR")
                form_ok = False
        
        # --- Verify Dates (critical) ---
        audit_start = start_date
        audit_end = end_date_override if end_date_override else end_date
        try:
            date_inputs = driver.find_elements(By.XPATH, "//input[contains(@class, 'ant-calendar-picker-input')]")
            if len(date_inputs) >= 2:
                actual_start = (date_inputs[0].get_attribute('value') or '').strip()
                actual_end   = (date_inputs[1].get_attribute('value') or '').strip()
                
                date_failed = False
                # Exact match for dates — '2026-01-01' in '2026-01-013' would
                # be True but is wrong. Date strings don't have legitimate
                # prefix/suffix, so `==` is correct.
                if audit_start and str(audit_start).strip() != actual_start:
                    log(f"❌ FORM AUDIT FAILED: Start Date expected '{audit_start}' (exact), UI shows '{actual_start}'", "ERROR")
                    date_failed = True
                    form_ok = False

                if audit_end and str(audit_end).strip() != actual_end:
                    log(f"❌ FORM AUDIT FAILED: End Date expected '{audit_end}' (exact), UI shows '{actual_end}'", "ERROR")
                    date_failed = True
                    form_ok = False
                
                if not date_failed:
                    log(f"✅ FORM AUDIT: Dates OK → Start='{actual_start}', End='{actual_end}'", "DEBUG")
        except Exception as date_audit_err:
            log(f"⚠️ FORM AUDIT: Could not read date fields: {date_audit_err}", "WARNING")
        
        # --- Verify min_qty / min_amount (non-critical but logged) ---
        for ph_check, val_check in [
            ("Minimum qty", min_qty),
            ("Minimum amount", min_amount),
            ("Minimum uusd", min_uusd),
        ]:
            if val_check is not None and str(val_check).strip() != "":
                try:
                    el = driver.find_element(By.XPATH, f"//input[@placeholder='{ph_check}']")
                    actual_v = (el.get_attribute('value') or '').strip()
                    if str(val_check).strip() not in actual_v:
                        log(f"⚠️ FORM AUDIT: '{ph_check}' expected '{val_check}', UI shows '{actual_v}'", "WARNING")
                    else:
                        log(f"✅ FORM AUDIT: '{ph_check}' OK → '{actual_v}'", "DEBUG")
                except: pass
        
        if not form_ok:
            log("❌ Form audit failed on critical field(s). Triggering re-fill...", "ERROR")
            return False
            
        log("✅ Search form filled and audited successfully", "SUCCESS")
        return True

    except Exception as e:
        log(f"❌ Error filling search form: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False

_MONTH_TO_INT = {
    # English short
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    # English full
    "January": 1, "February": 2, "March": 3, "April": 4, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10,
    "November": 11, "December": 12,
}


def _parse_calendar_header_month(text):
    """Map Ant Calendar header month label to int (1-12)."""
    text = (text or "").strip()
    if not text:
        return None
    if text in _MONTH_TO_INT:
        return _MONTH_TO_INT[text]
    # Take first 3 chars (handles "April " etc.)
    short = text[:3]
    if short in _MONTH_TO_INT:
        return _MONTH_TO_INT[short]
    # Numeric label "4"
    try:
        n = int(text)
        if 1 <= n <= 12:
            return n
    except ValueError:
        pass
    return None


def _force_close_date_popups(driver):
    """Aggressively kill every Ant DatePicker popup. Without this, a
    failed Start Date attempt leaves its popup open on top of the End
    Date input — the next click on End's outer hits Start's
    `.ant-calendar-input` and Selenium reports
    'element click intercepted'.

    Real-world observation (2026-04-29): just adding the
    `ant-calendar-picker-container-hidden` class wasn't enough — Ant
    sometimes re-renders without the class, and the inner
    `.ant-calendar-input` keeps absolute positioning over the End
    Date field. So now we do a layered nuke:
      1. CSS overrides on every picker container: display:none +
         visibility:hidden + pointer-events:none + opacity:0 + force
         the hidden class. Inline styles win over Ant's runtime CSS.
      2. Same overrides on every `.ant-calendar-input` (the inner
         input is what actually intercepts clicks).
      3. Move them off-screen as a final guarantee.
      4. Esc + body click for components that key off events.
    """
    try:
        driver.execute_script("""
            var hideStyles = function(el) {
                el.style.display = 'none';
                el.style.visibility = 'hidden';
                el.style.pointerEvents = 'none';
                el.style.opacity = '0';
                el.style.left = '-99999px';
                el.style.top = '-99999px';
            };
            document.querySelectorAll('.ant-calendar-picker-container')
                .forEach(function(el){
                    el.classList.add('ant-calendar-picker-container-hidden');
                    hideStyles(el);
                });
            document.querySelectorAll('.ant-calendar-input')
                .forEach(hideStyles);
            document.querySelectorAll('.ant-calendar')
                .forEach(hideStyles);
        """)
    except Exception:
        pass
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ESCAPE)
    except Exception:
        pass
    try:
        driver.find_element(By.TAG_NAME, "body").click()
    except Exception:
        pass
    time.sleep(0.25)


def _try_clear_date_picker(driver, outer):
    """Force-click the picker's clear (X) button so the field is empty
    before we open the popup. Hover via ActionChains first because the X
    is `display:none` until the picker is hovered. Without this, Ant
    keeps the previous value (or a default like 2025-03-31) and rejects
    our typed value because the calendar's internal moment cursor is
    locked to the old month."""
    try:
        ActionChains(driver).move_to_element(outer).perform()
        time.sleep(0.25)
    except Exception:
        pass
    # The X is a sibling of the inner input inside the picker wrapper.
    # Walking via JS is more reliable than XPath following-sibling axes
    # because Ant nests it as <i class="anticon ant-calendar-picker-clear">.
    cleared = driver.execute_script(
        "var inp = arguments[0];"
        "var wrap = inp.closest('.ant-calendar-picker') || inp.parentElement;"
        "if (!wrap) return false;"
        "var x = wrap.querySelector('.ant-calendar-picker-clear');"
        "if (!x) return false;"
        "x.style.display = 'inline-block';"
        "x.style.opacity = '1';"
        "x.click();"
        "return true;",
        outer)
    if cleared:
        time.sleep(0.4)
    return bool(cleared)


def _fill_date_via_keystrokes(driver, placeholder, date_str, debug_name="Date"):
    """Type the date character-by-character into the popup's inner input
    via Selenium send_keys. This is what a human would do — open the
    picker, click into the text field at the top, type the date string,
    press Enter. Works even when the React native setter path doesn't
    trigger Ant's onChange reliably.

    Why this is the primary path now (2026-04-28):
    - User confirmed manual typing works on accounts where the native
      setter path silently fails (verify reads empty even after setter
      + Tab). The difference is real keystrokes vs programmatic value
      assignment — Ant's keydown/keyup handlers parse + apply the date
      on each character, while the native setter requires a precise
      input/change/blur dance that breaks on some account states.
    - Slower (~50ms × 10 chars + waits ≈ 1s) but predictable.
    """
    xpath = (
        "//input[contains(@class, 'ant-calendar-picker-input') "
        f"and @placeholder='{placeholder}']"
    )
    visible_input_css = (
        ".ant-calendar-picker-container:not("
        ".ant-calendar-picker-container-hidden) .ant-calendar-input"
    )

    try:
        outer = driver.find_element(By.XPATH, xpath)
    except Exception as e:
        log(f"⚠️ {debug_name}: outer input not found: {e}", "DEBUG")
        return False

    for attempt in range(2):
        # Aggressively close any leftover popup (e.g. from a previous
        # Start Date attempt that failed but left its popup open on
        # top of End Date's outer input).
        _force_close_date_popups(driver)

        try:
            outer = driver.find_element(By.XPATH, xpath)
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", outer)
            outer.click()  # native Selenium click — opens popup reliably
            time.sleep(0.8)
        except Exception as e:
            log(f"⚠️ {debug_name}: keystrokes — outer click failed: {e}",
                "DEBUG")
            _force_close_date_popups(driver)
            continue

        try:
            cal_input = WebDriverWait(driver, 6).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, visible_input_css)))
        except Exception:
            log(f"⚠️ {debug_name}: keystrokes — popup input not visible "
                f"(attempt {attempt+1}/2)", "DEBUG")
            continue

        try:
            cal_input.click()
            time.sleep(0.2)
            # Select-all + delete to clear any existing text.
            modifier = Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL
            cal_input.send_keys(modifier, "a")
            time.sleep(0.1)
            cal_input.send_keys(Keys.DELETE)
            time.sleep(0.2)

            # Type each character with a short delay so React handlers
            # process per-keystroke validation.
            for ch in date_str:
                cal_input.send_keys(ch)
                time.sleep(0.04)

            time.sleep(0.3)
            cal_input.send_keys(Keys.ENTER)
            time.sleep(0.6)
        except Exception as e:
            log(f"⚠️ {debug_name}: keystrokes send_keys failed: {e}",
                "DEBUG")
            continue

        actual = (outer.get_attribute("value") or "").strip()
        if date_str in actual:
            log(f"✅ {debug_name} via keystrokes: '{actual}'", "SUCCESS")
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except Exception:
                pass
            time.sleep(0.2)
            return True
        log(f"⚠️ {debug_name} keystrokes attempt {attempt+1}/2 verify "
            f"failed: got '{actual}', expected '{date_str}'", "DEBUG")

    return False


def _fill_date_via_input_setter(driver, placeholder, date_str, debug_name="Date"):
    """Open the date picker, type the date into the popup's inner input
    via React's native value setter, then commit with Tab.

    Lessons learned (segment 4→5 shift bug, 2026-04-27):
    - After page refresh the form has DEFAULT preset values (e.g.
      2025-03-31). When we click outer to open popup, Ant initializes
      the calendar cursor at March 2025 and rejects programmatic value
      changes that conflict with the cursor. → Pre-clear via the X
      button so the picker starts empty.
    - JS .click() on the outer can race with React's onClick handler
      and toggle (open→close→open) within the same animation frame. →
      Use ActionChains.click() which routes through the OS event queue.
    - Pressing Enter on the inner input sometimes fires keydown but the
      popup's focus has already shifted before keyup, so commit doesn't
      happen. → Use Tab (blur) to commit; Ant's onBlur parses + accepts
      the typed value reliably.
    - The popup container's hidden class flips async. Wait for the
      visible CALENDAR TABLE (not just the input) to be sure it's open.
    - Three attempts give us a fresh DOM snapshot per try.
    """
    xpath = (
        "//input[contains(@class, 'ant-calendar-picker-input') "
        f"and @placeholder='{placeholder}']"
    )

    react_set_js = (
        "var el=arguments[0],v=arguments[1];"
        "el.focus();"
        "el.select();"
        "var setter=Object.getOwnPropertyDescriptor("
        " window.HTMLInputElement.prototype,'value').set;"
        "setter.call(el,'');"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "setter.call(el,v);"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
    )

    visible_popup_css = (
        ".ant-calendar-picker-container:not("
        ".ant-calendar-picker-container-hidden)")
    visible_input_css = f"{visible_popup_css} .ant-calendar-input"
    visible_table_css = f"{visible_popup_css} .ant-calendar-table"

    try:
        outer = driver.find_element(By.XPATH, xpath)
    except Exception as e:
        log(f"⚠️ {debug_name}: outer input not found: {e}", "DEBUG")
        return False

    # Pre-clear: defends against default presets locking the cursor.
    _try_clear_date_picker(driver, outer)

    for attempt in range(3):
        # Aggressively close any leftover popup so this picker's click
        # actually opens its own popup (not get intercepted by another
        # picker's leftover popup).
        _force_close_date_popups(driver)

        try:
            outer = driver.find_element(By.XPATH, xpath)
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", outer)
            ActionChains(driver).move_to_element(outer).click().perform()
            time.sleep(0.7)
        except Exception as e:
            log(f"⚠️ {debug_name}: ActionChains click failed: {e}; "
                f"falling back to JS click", "DEBUG")
            try:
                driver.execute_script("arguments[0].click();", outer)
                time.sleep(0.7)
            except Exception:
                _force_close_date_popups(driver)
                continue

        # Wait for BOTH visible calendar table AND visible inner input —
        # confirms the popup is fully mounted, not mid-animation.
        try:
            WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, visible_table_css)))
            WebDriverWait(driver, 3).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, visible_input_css)))
        except Exception:
            log(f"⚠️ {debug_name}: typing path — visible popup not fully "
                f"rendered (attempt {attempt+1}/3)", "DEBUG")
            continue

        cal_inputs = [e for e in driver.find_elements(
            By.CSS_SELECTOR, visible_input_css) if e.is_displayed()]
        if not cal_inputs:
            continue
        cal_input = cal_inputs[0]

        try:
            driver.execute_script(react_set_js, cal_input, date_str)
            time.sleep(0.4)
            # Tab (blur) commits more reliably than Enter on Ant Calendar:
            # Ant's onBlur parses + applies the typed value; Enter
            # sometimes loses focus before keyup.
            cal_input.send_keys(Keys.TAB)
            time.sleep(0.6)
        except Exception as e:
            log(f"⚠️ {debug_name}: native setter failed: {e}", "DEBUG")
            continue

        actual = (outer.get_attribute("value") or "").strip()
        if date_str in actual:
            log(f"✅ {debug_name} via input-setter: '{actual}'", "SUCCESS")
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except Exception:
                pass
            time.sleep(0.2)
            return True
        log(f"⚠️ {debug_name} input-setter attempt {attempt+1}/3 verify "
            f"failed: got '{actual}', expected '{date_str}'", "DEBUG")

        # If we got the field's preset (eg 2025-03-31) back, re-clear
        # before next attempt — Ant likely re-initialized to default.
        try:
            _try_clear_date_picker(driver, outer)
        except Exception:
            pass

    return False


def _fill_date_via_calendar_grid(driver, placeholder, date_str, debug_name="Date"):
    """Pick a date by clicking the Ant Calendar grid (open → nav month → click day).

    Used as fallback if `_fill_date_via_input_setter` fails. Clicking the
    day cell uses the picker's intended UI flow.

    Returns True on success, False if anything goes off-script — caller
    should fall back to interactive prompt.
    """
    try:
        yyyy, mm, dd = date_str.split("-")
        target_year, target_month, target_day = int(yyyy), int(mm), int(dd)
    except (ValueError, AttributeError):
        log(f"⚠️ {debug_name}: invalid date format '{date_str}' (need YYYY-MM-DD)",
            "WARNING")
        return False

    xpath = (
        "//input[contains(@class, 'ant-calendar-picker-input') "
        f"and @placeholder='{placeholder}']"
    )

    # Pre-click stability: country/data-type selection just before the
    # date step often triggers a re-render. Make sure no spinner is up
    # and React has time to commit before we click.
    try:
        api_client.wait_for_loading_overlay(driver, timeout=10)
    except Exception:
        pass
    # Close any open popup from prior failed paths (keystrokes /
    # input-setter) so this path's outer click isn't intercepted.
    _force_close_date_popups(driver)
    time.sleep(0.4)

    # Try multiple click strategies; popup sometimes doesn't open on the
    # first click (post-render race) or with bare execute_script click on
    # certain Chrome+React combos. Cycle through native click → JS click
    # → full mouse-event dispatch (matches the Details click that worked).
    # Also detect popup via the inner editable input (.ant-calendar-input)
    # which appears even when the outer .ant-calendar wrapper is in a
    # transitional state.
    POPUP_SELECTORS = (
        ".ant-calendar-input",            # the inner typing input (fastest)
        ".ant-calendar",
        ".ant-calendar-picker-container",
        ".ant-calendar-date-panel",
    )

    popup_visible = False
    for click_attempt in range(3):
        try:
            input_el = driver.find_element(By.XPATH, xpath)
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", input_el,
            )
            time.sleep(0.2)
            if click_attempt == 0:
                # Native Selenium click — most realistic
                try:
                    input_el.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", input_el)
            elif click_attempt == 1:
                driver.execute_script("arguments[0].click();", input_el)
            else:
                driver.execute_script(
                    "var el=arguments[0];"
                    "['mousedown','mouseup','click'].forEach(function(t){"
                    "  el.dispatchEvent(new MouseEvent(t,{bubbles:true,"
                    "    cancelable:true,view:window,button:0}));"
                    "});",
                    input_el,
                )
            time.sleep(0.4)

            for sel in POPUP_SELECTORS:
                try:
                    WebDriverWait(driver, 4).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    popup_visible = True
                    break
                except Exception:
                    continue
            if popup_visible:
                break
            log(f"⚠️ {debug_name}: popup not visible after click "
                f"attempt {click_attempt+1}/3", "DEBUG")
        except Exception as e:
            log(f"⚠️ {debug_name}: click attempt {click_attempt+1} error: {e}",
                "DEBUG")

    if not popup_visible:
        log(f"⚠️ {debug_name}: calendar popup didn't appear after 3 click "
            f"attempts", "WARNING")
        return False

    # Step through months until we land on (target_year, target_month).
    # Full pointer + mouse event dispatch: some Ant Calendar handlers
    # listen on `pointerdown`/`pointerup` (newer React-DOM event system)
    # rather than the classic mouse events. Sending both covers Ant v3
    # AND the Pointer Events polyfill that React-DOM v17+ uses.
    # Verify the month label changed after each click; if 3 clicks in a
    # row don't move the calendar, give up early instead of looping 60.
    MOUSE_CLICK_JS = (
        "var el=arguments[0];"
        "var rect=el.getBoundingClientRect();"
        "var cx=rect.left+rect.width/2, cy=rect.top+rect.height/2;"
        "['pointerover','pointerenter','pointerdown','mousedown',"
        " 'pointerup','mouseup','click'].forEach(function(t){"
        "  var Ev=t.startsWith('pointer')?PointerEvent:MouseEvent;"
        "  try{el.dispatchEvent(new Ev(t,{bubbles:true,cancelable:true,"
        "    view:window,button:0,pointerType:'mouse',clientX:cx,clientY:cy}));"
        "  }catch(e){"
        "    el.dispatchEvent(new MouseEvent(t,{bubbles:true,"
        "      cancelable:true,view:window,button:0,clientX:cx,clientY:cy}));"
        "  }"
        "});"
    )
    MAX_NAV_CLICKS = 60
    last_label = None
    stuck_count = 0
    for _step in range(MAX_NAV_CLICKS):
        try:
            month_label = driver.find_element(
                By.CSS_SELECTOR, ".ant-calendar-month-select"
            ).text
            year_label = driver.find_element(
                By.CSS_SELECTOR, ".ant-calendar-year-select"
            ).text
        except Exception:
            log(f"⚠️ {debug_name}: can't read calendar header", "WARNING")
            return False

        try:
            cur_year = int(year_label.strip())
        except ValueError:
            log(f"⚠️ {debug_name}: can't parse year '{year_label}'", "WARNING")
            return False
        cur_month = _parse_calendar_header_month(month_label)
        if cur_month is None:
            log(f"⚠️ {debug_name}: can't parse month '{month_label}'", "WARNING")
            return False

        if cur_year == target_year and cur_month == target_month:
            break

        # Detect stuck nav: same header 3 clicks in a row → button click
        # is no-op, abort instead of looping.
        cur_label = f"{cur_year}-{cur_month:02d}"
        if cur_label == last_label:
            stuck_count += 1
            if stuck_count >= 3:
                log(f"⚠️ {debug_name}: nav stuck at {cur_label} (3 clicks "
                    f"didn't advance), giving up", "WARNING")
                return False
        else:
            stuck_count = 0
            last_label = cur_label

        diff = (target_year - cur_year) * 12 + (target_month - cur_month)
        nav_sel = (
            ".ant-calendar-prev-month-btn" if diff < 0
            else ".ant-calendar-next-month-btn"
        )
        try:
            btn = driver.find_element(By.CSS_SELECTOR, nav_sel)
            # Try MouseEvent dispatch first (most reliable across Chrome+React)
            try:
                driver.execute_script(MOUSE_CLICK_JS, btn)
            except Exception:
                driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.18)
        except Exception as e:
            log(f"⚠️ {debug_name}: month nav click failed: {e}", "WARNING")
            return False
    else:
        log(f"⚠️ {debug_name}: month navigation exceeded {MAX_NAV_CLICKS} clicks", "WARNING")
        return False

    # Click the day cell, ensuring it's the ACTIVE month (not greyed out).
    try:
        cells = driver.find_elements(By.CSS_SELECTOR, ".ant-calendar-tbody td")
    except Exception as e:
        log(f"⚠️ {debug_name}: day cell lookup failed: {e}", "WARNING")
        return False

    for cell in cells:
        cls = cell.get_attribute("class") or ""
        if "last-month-cell" in cls or "next-month-cell" in cls:
            continue
        try:
            inner = cell.find_element(By.CSS_SELECTOR, ".ant-calendar-date")
            if inner.text.strip() == str(target_day):
                # Click cell (pointer + mouse event sequence)
                try:
                    driver.execute_script(MOUSE_CLICK_JS, inner)
                except Exception:
                    driver.execute_script("arguments[0].click();", inner)
                time.sleep(0.5)

                # First-pass verify
                actual = (input_el.get_attribute("value") or "").strip()
                if date_str in actual:
                    log(f"✅ {debug_name} via calendar grid: '{actual}'", "SUCCESS")
                    return True

                # Sometimes Ant Calendar needs a "commit" signal — Enter on
                # the calendar's inner input forces it to submit the picked
                # date out to the outer input. Try this once before failing.
                try:
                    cal_input = driver.find_element(
                        By.CSS_SELECTOR, ".ant-calendar-input"
                    )
                    cal_input.send_keys(Keys.ENTER)
                    time.sleep(0.4)
                except Exception:
                    pass

                actual = (input_el.get_attribute("value") or "").strip()
                if date_str in actual:
                    log(f"✅ {debug_name} via calendar grid (Enter-commit): "
                        f"'{actual}'", "SUCCESS")
                    return True

                log(f"⚠️ {debug_name} grid click verify failed: "
                    f"got '{actual}', expected '{date_str}'", "WARNING")
                return False
        except Exception:
            continue

    log(f"⚠️ {debug_name}: day cell {target_day} not found", "WARNING")
    return False


def _fill_date_simple(driver, wait, start_date, end_date):
    """
    Fill dates using robust interaction by finding inputs via PLACEHOLDER.
    Includes strict Waiting for Popup Invisibility to prevent overlap.
    """
    try:
        def fill_by_placeholder(placeholder_text, date_val, debug_name="Date"):
            """Try three paths in order (re-ordered 2026-04-29 after
            real-world data showed input-setter wins more often than
            keystrokes when popup is slow to render):
              1. React native value-setter — atomic JS write with X-clear
                 first. ~5s per attempt, works on most Ant states. Rated
                 ~70% first-attempt success in production.
              2. Keystrokes (send_keys char-by-char) — fallback when
                 React setter fails (rare). ~7s per attempt.
              3. Calendar-grid click — last resort, ~15s per attempt.

            Old order was keystrokes-first which wasted ~14s per recovery
            cycle when Ant popup wasn't ready for typing — caller had to
            wait keystrokes 2-attempt timeout before falling to setter.
            """
            if not date_val:
                return True

            if _fill_date_via_input_setter(driver, placeholder_text, date_val, debug_name):
                return True

            if _fill_date_via_keystrokes(driver, placeholder_text, date_val, debug_name):
                return True

            if _fill_date_via_calendar_grid(driver, placeholder_text, date_val, debug_name):
                try:
                    driver.find_element(By.TAG_NAME, "body").click()
                except Exception:
                    pass
                time.sleep(0.3)
                return True

            log(f"❌ {debug_name}: input-setter + keystrokes + grid-click "
                f"all failed. Caller will prompt operator if "
                f"INTERACTIVE_SEARCH=1.", "WARNING")
            return False

        success = True

        # Explicitly fill Start Date
        if start_date:
            log(f"📅 Filling Start Date: {start_date}", "DEBUG")
            if not fill_by_placeholder("Please select the starting time...", start_date, "Start Date"):
                success = False
            # Always close any leftover popup from Start before touching End,
            # whether Start succeeded or failed. Otherwise End's outer-click
            # gets intercepted by Start's still-open `.ant-calendar-input`.
            _force_close_date_popups(driver)

        # Explicitly fill End Date
        if end_date:
            log(f"📅 Filling End Date: {end_date}", "DEBUG")
            if not fill_by_placeholder("Please select the end time...", end_date, "End Date"):
                success = False
            _force_close_date_popups(driver)

        return success
    except Exception as e:
        log(f"❌ Error in _fill_date_simple: {e}", "ERROR")
        return False

_REACT_SET_VALUE_JS = """
// Set an <input> value in a React-controlled way: CLEAR FIRST (so we
// don't append to existing state — was the cause of HS Code becoming
// '5252' / '552' on the second fill attempt because send_keys appended
// to a field React still thought had '52'), then write the new value.
// React's _valueTracker is updated on the prototype setter call, so
// the input/change events fire with the correct delta.
var el = arguments[0], v = arguments[1];
var proto = window.HTMLInputElement.prototype;
var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
el.focus();
setter.call(el, '');
el.dispatchEvent(new Event('input', {bubbles: true}));
setter.call(el, v);
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
el.blur();
"""


def _is_real_form_input(el):
    """Reject elements that are hidden, disabled, or not Ant form inputs.
    Without this, the label-based fallback in _find_input_by_placeholder_fuzzy
    can resolve to detail-panel inputs (e.g. value 'analyse_6') when DOM is
    polluted with overlay residue from a failed row capture, causing
    HS code fill to write into the wrong element.
    """
    try:
        if not el.is_displayed():
            return False
        if not el.is_enabled():
            return False
        cls = (el.get_attribute("class") or "").lower()
        # Ant Design form inputs always carry 'ant-input' on the field itself
        # or its parent picker. Detail panel internal inputs typically don't.
        if "ant-input" not in cls and "ant-calendar-picker-input" not in cls:
            return False
        return True
    except Exception:
        return False


def _find_input_by_placeholder_fuzzy(driver, placeholder):
    """Try exact placeholder first, then substring match (the site sometimes
    prefixes the placeholder with helper text, e.g. 'Support multi-HS code
    input split by "|", e.g. 940|950' instead of just 'HS code').

    Each candidate is validated by _is_real_form_input so we never return a
    hidden / non-Ant element when DOM has leftover overlay panels.
    """
    # 1. Exact match — pick the first VISIBLE one (some pages have
    # duplicate placeholders in detail panels which are invisible).
    try:
        for el in driver.find_elements(
            By.XPATH, f"//input[@placeholder='{placeholder}']"
        ):
            if _is_real_form_input(el):
                return el
    except Exception:
        pass
    # 2. Substring match on placeholder (still requires ant-input class)
    try:
        for el in driver.find_elements(
            By.XPATH,
            f"//input[contains(translate(@placeholder, "
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{placeholder.lower()}')]",
        ):
            if _is_real_form_input(el):
                return el
    except Exception:
        pass
    # 3. Label-based (floating label adjacent to the input). Most fragile
    # tier — keep the strict ant-input filter so we never grab a
    # detail-panel input by accident.
    try:
        for el in driver.find_elements(
            By.XPATH,
            f"//*[contains(text(),'{placeholder}')]"
            f"/following::input[1]",
        ):
            if _is_real_form_input(el):
                return el
    except Exception:
        pass
    return None


def fill_input_field_simple(driver, wait, placeholder, value, element_id_override=None):
    """Fill an input with EXACT post-fill verification.

    Order of attempts:
      1. React native value setter (atomic clear + set) — primary now, was
         fallback before. Reliably overwrites React state instead of
         appending to it. Fixed the HS-Code-becomes-'552' bug where
         send_keys appended to a field React still thought had '52'.
      2. Native typing with Ctrl+A clear — fallback if React setter
         doesn't take (rare, e.g. when input is wrapped in a custom
         component).
      3. Verify EXACT EQUALITY of the value, not substring. '52' was
         passing audit when actual='552' because '52' in '552' is True.
    """
    expected_str = str(value).strip()
    MAX_FILL_ATTEMPTS = 3

    for attempt in range(1, MAX_FILL_ATTEMPTS + 1):
        try:
            input_el = None
            if element_id_override:
                try:
                    input_el = driver.find_element(By.ID, element_id_override)
                except Exception:
                    pass
            if not input_el:
                input_el = _find_input_by_placeholder_fuzzy(driver, placeholder)
            if not input_el:
                log(f"⚠️ Field '{placeholder}': no matching input (attempt {attempt}/{MAX_FILL_ATTEMPTS})",
                    "WARNING")
                time.sleep(0.3 * attempt)
                continue

            # --- Primary: React native value setter (atomic clear + set) ---
            try:
                driver.execute_script(_REACT_SET_VALUE_JS, input_el, expected_str)
                time.sleep(0.2)
                actual = (input_el.get_attribute("value") or "").strip()
                if actual == expected_str:
                    if attempt > 1:
                        log(f"✅ Field '{placeholder}' set via React setter on "
                            f"attempt {attempt}: '{actual}'", "DEBUG")
                    return True
                log(f"⚠️ Field '{placeholder}' React setter gave '{actual}' "
                    f"(expected '{expected_str}'), trying native typing...",
                    "DEBUG")
            except Exception as js_err:
                log(f"⚠️ React setter failed: {js_err}; trying native typing",
                    "DEBUG")

            # --- Fallback: native typing with explicit clear ---
            try:
                input_el.click()
                time.sleep(0.1)
                input_el.send_keys(Keys.CONTROL + "a")
                time.sleep(0.1)
                input_el.send_keys(Keys.BACK_SPACE)
                time.sleep(0.1)
                input_el.send_keys(Keys.DELETE)
            except Exception:
                try:
                    input_el.clear()
                except Exception:
                    pass

            human_type(input_el, expected_str)
            time.sleep(0.2)

            actual = (input_el.get_attribute("value") or "").strip()
            # Exact match only — '52' in '552' is True but they're DIFFERENT
            # filter values that return different result sets.
            if actual == expected_str:
                if attempt > 1:
                    log(f"✅ Field '{placeholder}' verified on attempt {attempt}: '{actual}'", "DEBUG")
                return True

            log(f"⚠️ Field '{placeholder}' verify failed (attempt {attempt}/{MAX_FILL_ATTEMPTS}): "
                f"got '{actual}', expected '{expected_str}'. Retrying...", "WARNING")
            time.sleep(0.3 * attempt)

        except Exception as e:
            log(f"❌ Failed to fill input field '{placeholder}' with '{value}' "
                f"(attempt {attempt}): {e}", "ERROR")
            err_str = str(e)
            if any(x in err_str for x in (
                "Max retries exceeded", "WinError 10061", "timed out",
                "script timeout", "HTTPConnectionPool",
            )):
                raise
            time.sleep(0.3 * attempt)

    log(f"❌ Field '{placeholder}' could not be set to '{expected_str}' after "
        f"{MAX_FILL_ATTEMPTS} attempts", "ERROR")
    return False


def click_search_button_detail(driver, wait):
    """
    Click the Search button on Detail Mode page.
    Uses robust clicking strategy (Human + JS) to ensure activation.
    """
    try:
        log("🔍 Preparing to click Search button...", "SEARCH")
        
        # 1. Stabilization Wait (Ensure form state is settled)
        time.sleep(1)
        
        # 2. Find the button
        search_btn = wait.until(EC.element_to_be_clickable((
             By.CSS_SELECTOR, 
             "button.ant-btn.ant-btn-primary"
        )))
        
        # 3. Scroll into view
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_btn)
        time.sleep(0.5)
        
        # 4. Click Strategy
        
        # Attempt 1: Human Click (ActionChains) - For visual feedback/event triggering
        try:
            log("📍 Attempting Human Click on Search...", "DEBUG")
            human_click(driver, search_btn)
            time.sleep(0.2)
        except Exception as e:
            log(f"⚠️ Human click failed: {e}", "WARNING")
            
        # Attempt 2: JS Click (Force) - To ensure submission
        try:
            log("📍 Attempting JS Force Click on Search...", "DEBUG")
            driver.execute_script("arguments[0].click();", search_btn)
        except Exception as e:
            log(f"⚠️ JS click failed: {e}", "WARNING")
            
        log("✅ Clicked Search button", "DEBUG")
        
        # Enable network capture if possible
        try:
             driver.execute_cdp_cmd('Network.enable', {})
        except:
             pass

        # Wait for network response logic (retained)...
        log("⏳ Waiting for network response...", "DEBUG")
        time.sleep(2) 
        
        # ... (rest of network capture logic same as before) ...
        detail_api_url = "/api/"
        start_time = time.time()
        timeout = 10
        
        while time.time() - start_time < timeout:
             # ... capture loop ...
             try:
                logs = driver.get_log('performance')
                for log_entry in logs:
                    message = json.loads(log_entry['message'])['message']
                    if message['method'] == 'Network.responseReceived':
                        if detail_api_url in message['params']['response']['url']:
                             # Found it
                             log("✅ Captured API response signal", "SUCCESS")
                             return {'status': 'captured'} # Return dummy or actual data
             except:
                 pass
             time.sleep(0.2)
             
        return {}
        
    except Exception as e:
        log(f"❌ Failed to click Search button: {e}", "ERROR")
        return None

def select_dropdown_with_retry(driver, wait, dropdown_index, value, max_retries=3, retry_delay=2):
    """
    Select from Ant Design dropdown with robust option finding.
    """
    dropdown_names = {0: "Country", 1: "Data Type"}
    name = dropdown_names.get(dropdown_index, f"Dropdown {dropdown_index}")
    
    for attempt in range(max_retries):
        try:
            log(f"Step {dropdown_index+1}: Selecting {name}: {value} (attempt {attempt+1})", "INFO")
            
            # 1. Find Dropdown
            dropdowns = driver.find_elements(By.CSS_SELECTOR, "div.searchforclass div.ant-select-selection")
            if len(dropdowns) <= dropdown_index:
                time.sleep(retry_delay); continue
            
            target_dropdown = dropdowns[dropdown_index]
            
            # 2. Check current value (fast return)
            try:
                if value.lower() in target_dropdown.text.strip().lower():
                    log(f"✅ {name} already selected: {target_dropdown.text}", "SUCCESS")
                    return True
            except: pass
            
            # 3. Open Dropdown
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_dropdown)
            driver.execute_script("arguments[0].click();", target_dropdown)
            time.sleep(1.5) # Allow ample animation time
            
            # 4. Find Option (Multi-Strategy)
            # Ant Design 3.x options are usually in: div > div > ul > li.ant-select-dropdown-menu-item
            # They are often appended to BODY, not inside the select div.
            
            option = None
            v_lower = value.lower()
            v_translate = (
                f"translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                f"'abcdefghijklmnopqrstuvwxyz')"
            )

            # Strategy list — covers Ant Design v3 (li.ant-select-dropdown-menu-item)
            # AND v4+ (.ant-select-item-option or .ant-select-item) AND a
            # role-based fallback. For each strategy we then also filter
            # by text match.
            strategies = [
                # v3 exact
                (By.XPATH, f"//li[contains(@class, 'ant-select-dropdown-menu-item') and text()='{value}']"),
                # v4 exact (div-based)
                (By.XPATH, f"//div[contains(@class, 'ant-select-item-option') and "
                           f".//*[normalize-space(text())='{value}']]"),
                # v3 case-insensitive contains
                (By.XPATH, f"//li[contains(@class, 'ant-select-dropdown-menu-item') and "
                           f"contains({v_translate}, '{v_lower}')]"),
                # v4 case-insensitive contains (any nested element)
                (By.XPATH, f"//div[contains(@class, 'ant-select-item-option') and "
                           f"contains({v_translate}, '{v_lower}')]"),
                # role=option (works for some custom Ant variants)
                (By.XPATH, f"//*[@role='option' and contains({v_translate}, '{v_lower}')]"),
                # Last resort: any visible li or div in the dropdown panel
                # with the value text
                (By.XPATH, f"//div[contains(@class, 'ant-select-dropdown') and "
                           f"not(contains(@class, 'hidden')) and "
                           f"not(contains(@style, 'display: none'))]"
                           f"//*[self::li or self::div][contains({v_translate}, '{v_lower}')]"),
            ]

            for by, locator in strategies:
                try:
                    candidates = driver.find_elements(by, locator)
                    for cand in candidates:
                        if not cand.is_displayed():
                            continue
                        # Verify text actually matches
                        try:
                            if v_lower not in cand.text.strip().lower():
                                continue
                        except Exception:
                            pass
                        option = cand
                        break
                    if option:
                        break
                except Exception:
                    pass

            # Last-resort: pure text search anywhere in DOM. Site sometimes
            # renders dropdown options with non-Ant class names. We accept
            # any visible element whose normalized text exactly matches
            # the value, preferring the most recently appended one (the
            # open dropdown panel is rendered last).
            if not option:
                try:
                    candidates = driver.find_elements(
                        By.XPATH,
                        f"//*[normalize-space(text())='{value}' or "
                        f"normalize-space(text())='{value.lower()}']",
                    )
                    for cand in reversed(candidates):
                        try:
                            if cand.is_displayed() and cand.size["height"] > 0:
                                option = cand
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            if option:
                driver.execute_script("arguments[0].click();", option)
                log(f"✅ Selected option: {value}", "SUCCESS")
                time.sleep(1)

                try:
                    if value.lower() in target_dropdown.text.strip().lower():
                        return True
                except Exception:
                    return True

                return True
            else:
                # Debug: dump visible option texts AND the open dropdown's
                # outerHTML (truncated) so the next selector failure is
                # easy to diagnose without screenshots.
                visible_texts = []
                for sel in (
                    "li.ant-select-dropdown-menu-item",
                    "div.ant-select-item-option",
                    "div.ant-select-item",
                    ".ant-select-dropdown li",
                    ".ant-select-dropdown div",
                ):
                    try:
                        for el in driver.find_elements(By.CSS_SELECTOR, sel):
                            if el.is_displayed() and el.text.strip():
                                visible_texts.append(el.text.strip())
                                if len(visible_texts) >= 8:
                                    break
                    except Exception:
                        pass
                    if len(visible_texts) >= 8:
                        break
                # Also try a generic visible-element text dump so we know
                # what IS on screen when our selectors miss.
                try:
                    panels = driver.find_elements(
                        By.XPATH,
                        "//*[contains(@class,'dropdown') or contains(@class,'menu')]"
                        "[not(contains(@style,'display: none'))]",
                    )
                    for p in panels:
                        try:
                            if not p.is_displayed():
                                continue
                            html = (p.get_attribute("outerHTML") or "")[:400]
                            log(f"   [diag] dropdown-ish element: {html}",
                                "DEBUG")
                            break
                        except Exception:
                            continue
                except Exception:
                    pass
                log(f"⚠️ Option '{value}' not found in visible menu. "
                    f"Visible: {visible_texts[:5]}", "WARNING")

            # Close and Retry
            driver.find_element(By.TAG_NAME, "body").click()
            time.sleep(retry_delay)
            
        except Exception as e:
            log(f"❌ Error selecting {name}: {e}", "ERROR")
            err_str = str(e)
            if "Max retries exceeded" in err_str or "WinError 10061" in err_str or "timed out" in err_str or "script timeout" in err_str or "HTTPConnectionPool" in err_str:
                raise
            time.sleep(retry_delay)
            
    return False


def get_total_records_detail(driver, wait, current_segment=1, expected_total=None):
    """
    Extract the total number of records from Detail Mode result page.
    
    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait instance
        current_segment: int - Current segment number (1-based). 
                        Segment 1 = strict validation (exact match expected)
                        Segment 2+ = relaxed validation (total <= expected, due to date filter)
        expected_total: int - Expected total for this search (from batch_config or config).
                       If None, uses config.DETAIL_EXPECTED_TOTAL
    
    Returns:
        int: Total records, or None if not found
    """
    try:
        time.sleep(2)
        
        effective_expected = expected_total if expected_total is not None else getattr(config, 'DETAIL_EXPECTED_TOTAL', None)
        
        bg_total = None
        
        for attempt in range(5):
            # Strategy 1: Raw page source regex (Most bulletproof for React)
            import re
            source = driver.page_source
            match = re.search(r'>\s*Total\s+([\d,]+)\s*<', source, re.IGNORECASE)
            if match:
                bg_total = int(match.group(1).replace(',', ''))
                log(f"✅ Found total records (Raw Regex Attempt {attempt+1}): {bg_total:,}", "SUCCESS")
            
            # Strategy 2: Old/Generic "Total: X records" or class-based
            if bg_total is None:
                try:
                    total_element = driver.find_element(
                        By.XPATH,
                        "//div[contains(@class, 'total') or contains(text(), 'records')]"
                    )
                    total_text = total_element.text
                    
                    match = re.search(r'(\d+)', total_text.replace(',', ''))
                    if match:
                        bg_total = int(match.group(1))
                        log(f"✅ Found total records (Generic Attempt {attempt+1}): {bg_total:,}", "SUCCESS")
                except:
                    pass
            
            # If we found a total, validate it
            if bg_total is not None:
                if effective_expected and current_segment == 1:
                    if bg_total == effective_expected:
                        break # Perfect match, break the retry loop
                    else:
                        log(f"⏳ Total mismatch (Got: {bg_total:,}, Expected: {effective_expected:,}). React might still be updating, retrying...", "DEBUG")
                        bg_total = None # Invalidate and retry
                        time.sleep(2)
                else:
                    break # Not in strict validation mode, accept it
                    
            if bg_total is None:
                time.sleep(2)
        
        if bg_total is not None:
            total = bg_total
            
            # Validate against expected total (segment-aware)
            if effective_expected:
                if current_segment == 1:
                    # Segment 1: Strict validation (exact match)
                    if total == effective_expected:
                        log(f"✅ Total matches expected exactly: {total:,}", "SUCCESS")
                    else:
                        log(f"⚠️ Total mismatch! Expected exactly: {effective_expected:,}, Got: {total:,}", "WARNING")
                        return None # Fail to trigger retry
                else:
                    # Segment 2+: Decrease max bound by 9990 per segment 
                    # Date boundaries overlap slightly, so we allow a tolerance of 5000 records
                    expected_max_bound = effective_expected - (current_segment - 1) * 9990
                    tolerance = 10000

                    if total > (expected_max_bound + tolerance):
                        log(f"⚠️ Segment {current_segment} anomaly: found {total:,} records.", "WARNING")
                        log(f"   Expected approx: <= {expected_max_bound + tolerance:,} (Global {effective_expected:,} - {(current_segment-1)*9990:,} scraped, tolerance {tolerance:,})", "WARNING")
                        log(f"   Gap exceeds tolerance but continuing anyway (filter may have minor date overlap).", "WARNING")
                        # Do NOT return None — allow scraping to continue
                        
                    else:
                        log(f"✅ Segment {current_segment} total validated: {total:,} (Upper bound: {expected_max_bound + tolerance:,})", "SUCCESS")
            
            return total
            
    except Exception as e:
        log(f"⚠️ Error validating total records: {e}", "WARNING")
        return None

def click_all_clear(driver, wait):
    """
    Click 'All clear' button to reset form.
    """
    try:
        # Button often has text "All clear" inside a span
        btn = wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[contains(., 'All clear')]"
        )))
        human_click(driver, btn)
        time.sleep(1.5) # Wait for clear action and UI reset
        log("✅ Clicked 'All clear'", "DEBUG")
        return True
    except Exception as e:
        log(f"⚠️ Failed to click 'All clear': {e}", "WARNING")
        return False

def reset_pagination_to_page_one(driver, wait):
    """
    Force click Page 1 in pagination if active.
    """
    try:
        # Check if we are already on page 1
        # Active page usually has class 'ant-pagination-item-active'
        try:
            active_page = driver.find_elements(By.CSS_SELECTOR, "li.ant-pagination-item-active")
            if active_page and active_page[0].get_attribute("title") == "1":
                log("ℹ️ Already on Page 1", "DEBUG")
                return True
        except:
            pass

        # Find Page 1 Link
        # Title="1" is standard in Ant Design
        page_one = wait.until(EC.element_to_be_clickable((
            By.CSS_SELECTOR, "li[title='1']"
        )))
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_one)
        time.sleep(0.5)
        
        human_click(driver, page_one)
        time.sleep(2.0) # Wait for reload
        log("✅ Reset pagination to Page 1", "SUCCESS")
        return True
    except Exception as e:
        # Using debug because sometimes pagination is not visible (if < 1 page)
        log(f"ℹ️ Could not click Page 1 (might be single page result): {e}", "DEBUG")
        return False


def click_analysis_tab(driver, wait, analysis_type):
    """
    Click on a specific analysis tab (Buyer, Supplier, etc.) after search results are loaded.
    Uses text matching as the primary strategy since 'analyse_X' indexes change between Import and Export data.
    
    Args:
        driver: Selenium WebDriver
        wait: WebDriverWait
        analysis_type: str - One of: buyer, buyer_country, supplier, supplier_country, pol, pod, hs_code, shipping, market_dynamics
        
    Returns:
        bool: True if tab clicked successfully
    """
    try:
        log(f"📍 Clicking Analysis Tab: {analysis_type}...", "PROCESS")
        
        # Wait for loading to ensure tabs are interactive
        wait_for_loading_to_disappear(driver, wait, timeout=10)
        
        # Map analysis_type to exact text patterns (case-insensitive checks)
        text_map = {
            "buyer": ["Buyer "], # With space to avoid matching 'Buyer country'
            "buyer_country": ["Buyer country"],
            "supplier": ["Supplier "],
            "supplier_country": ["Supply country", "Supplier country"],
            "country": ["Supply country", "Buyer country"], # Fallback
            "pol": ["POL"],
            "pod": ["POD"],
            "hs_code": ["HS code"],
            "shipping": ["Shipping methods"],
            "market_dynamics": ["Dynamic Analysis"],
        }
        
        target_texts = text_map.get(analysis_type.lower())
        if not target_texts:
            log(f"❌ Unknown analysis type: {analysis_type}", "ERROR")
            return False
            
        try:
            # Find the scrollable box containing the tabs
            scrollable_box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".scrollable-box")))
            labels = scrollable_box.find_elements(By.TAG_NAME, "label")
            
            target_label = None
            for label in labels:
                label_text = label.text.strip().lower()
                # Also check inner span texts directly to avoid whitespace issues
                spans = label.find_elements(By.TAG_NAME, "span")
                span_texts = [s.text.strip().lower() for s in spans]
                combo_text = " ".join(span_texts) + " " + label_text
                
                # We need exact match for buyer vs buyer country
                if analysis_type.lower() == "buyer":
                    # Exact match "buyer"
                    if "buyer" in span_texts and "buyer country" not in span_texts:
                        target_label = label
                        break
                elif analysis_type.lower() == "supplier":
                    if "supplier" in span_texts and "supplier country" not in span_texts and "supply country" not in span_texts:
                        target_label = label
                        break
                else:
                    # Regular matching for other types
                    for expected in target_texts:
                        if expected.lower() in combo_text.lower():
                            target_label = label
                            break
                
                if target_label:
                    break
                    
            if not target_label:
                log(f"❌ Could not find tab for {analysis_type} based on text matching.", "ERROR")
                return False
                
            # Check if already active
            if "ant-radio-button-wrapper-checked" in target_label.get_attribute("class"):
                log(f"✅ Analysis tab '{analysis_type}' already active", "DEBUG")
                return True
                
            # Scroll and click
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_label)
            time.sleep(0.5)
            
            human_click(driver, target_label)
            log(f"✅ Clicked analysis tab: {analysis_type}", "SUCCESS")
            
            # Wait for content refresh
            wait_for_loading_to_disappear(driver, wait, timeout=30)
            time.sleep(1) # Extra stability wait
            
            return True
            
        except Exception as e:
            log(f"⚠️ Text finding strategy failed for {analysis_type}: {e}", "WARNING")

        log(f"❌ Failed to find analysis tab: {analysis_type}", "ERROR")
        return False
        
    except Exception as e:
        log(f"❌ Error verifying analysis tab: {e}", "ERROR")
        return False
