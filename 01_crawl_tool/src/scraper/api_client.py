import json
import time
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as ShortWait

def enable_network_capture(driver):
    """Enable network request/response capture"""
    try:
        # Give browser a moment to initialize CDP
        time.sleep(1)
        
        # Enable Network domain for Chrome DevTools Protocol
        driver.execute_cdp_cmd('Network.enable', {})
        print("   ✅ Network capture enabled")
        return True
    except Exception as e:
        print(f"   ⚠️ Could not enable network capture: {e}")
        return False


def capture_network_response_sync(driver, timeout=3):
    """Capture network response by polling performance logs (synchronous)
    Fast strategy: Catch either request or response, poll very frequently
    
    Returns:
        dict: Parsed detail data from API response, or None if not found
    """
    start_time = time.time()
    detail_api_url = "/async/raw/bill/detail"
    seen_request_ids = set()  # Track which requests we've tried
    
    while time.time() - start_time < timeout:
        try:
            # Get performance logs
            logs = driver.get_log('performance')
            
            for log in logs:
                try:
                    log_message = json.loads(log['message'])
                    message = log_message.get('message', {})
                    method = message.get('method', '')
                    
                    # Look for Network.responseReceived for our API
                    if method == 'Network.responseReceived':
                        response = message.get('params', {}).get('response', {})
                        url = response.get('url', '')
                        
                        if detail_api_url in url:
                            request_id = message['params']['requestId']
                            
                            # Skip if we already tried this request
                            if request_id in seen_request_ids:
                                continue
                            seen_request_ids.add(request_id)
                            
                            # Try to get response body immediately
                            try:
                                response_body = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
                                body_json = json.loads(response_body['body'])
                                
                                # Check if successful response
                                if body_json.get('state') == 0 and body_json.get('data'):
                                    detail_data = body_json['data']['detail']
                                    print(f"   ✅ Captured API response: {len(detail_data)} fields")
                                    return detail_data  # RETURN IMMEDIATELY!
                                elif body_json.get('state') in [3001, 4003]:
                                    log_msg = "Session expired (3001)" if body_json.get('state') == 3001 else "Permission/Session error (4003)"
                                    print(f"   ⚠️ {log_msg.upper()}")
                                    return {"_needs_refresh": True, "_error_state": body_json.get('state')}
                            except:
                                # Response body not available yet, will retry on next poll
                                pass
                
                except:
                    continue
            
            # Poll very frequently for fast detection
            time.sleep(0.03)
        
        except Exception as e:
            print(f"   ⚠️ Error reading logs: {e}")
            time.sleep(0.2)
    
    print(f"   ⚠️ Network response not captured within {timeout}s")
    return None


def wait_for_loading_overlay(driver, timeout=15):
    """Wait for Layui loading overlay to disappear"""
    try:
        # Selector covering various Layui loading styles and Ant Design (Pro 2026) spinners
        selector = ".layui-layer-loading, .layui-layer-loading0, .layui-layer-loading1, .layui-layer-loading2, .layui-layer-shade, .ant-spin-spinning"
        
        # Fast check first
        if not driver.find_elements(By.CSS_SELECTOR, selector):
            return

        print("   ⏳ Loading overlay detected. Waiting...")
        start_wait = time.time()
        
        # Wait for invisibility
        ShortWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, selector))
        )
        
        # Double check to ensure it's truly gone (Layui sometimes flickers)
        time.sleep(0.5)
        print(f"   ✅ Loading overlay cleared ({time.time() - start_wait:.1f}s).")
        
    except Exception as e:
        # If timeout, we verify if it's actually blocking or just a glitch
        print(f"   ⚠️ Wait for loading overlay timed out or failed: {e}")

def handle_popup(driver, wait, timeout=0.1):
    """Wait for and close ALL popups that block interaction - ULTRA AGGRESSIVE"""
    try:
        # Give a small moment for popup to appear if it's dynamic
        time.sleep(1)
        
        # Broad list of selectors, now including user-provided specifics
        selectors = [
            # Login error popup - "请输入账号或密码" (Please enter account/password)
            "//div[contains(@class, 'layui-layer-dialog')]//div[contains(text(), '请输入账号或密码')]/..//a[contains(@class, 'layui-layer-btn0')]",  # "I Know" button
            "//div[contains(@class, 'layui-layer-dialog')]//a[contains(text(), 'I Know')]",  # Direct "I Know" button match
            "//div[contains(@class, 'layui-layer-content') and contains(text(), '请输入')]/..//a[contains(@class, 'layui-layer-close')]",  # Close X button on login error
            
            # User specific & Top priority
            "//a[contains(@class, 'layui-layer-close2')]",
            "//span[contains(@class, 'layui-layer-setwin')]/a",
            "//a[contains(@class, 'layui-layer-close')]", 
            "//a[contains(@class, 'layui-layer-ico')]",
            "//a[contains(@class, 'close')]",
            "//button[@class='ant-modal-close']", # NEW: Ant modal close button
            "//span[contains(@class, 'ant-modal-close-x')]", # NEW: Ant modal close span
            "//div[contains(@class, 'ant-modal')]//button[contains(., 'OK')]", # Ant OK button
            "//div[contains(@class, 'ant-modal')]//button[contains(., 'Close')]", # Ant Close button
            # CSS variants (Specific PRO modal close buttons)
            ".layui-layer-ico.layui-layer-close1",
            ".layui-layer-ico.layui-layer-close2",
            "a.layui-layer-close2",
            "a.layui-layer-btn0",
            ".layui-layer-setwin a",
            "div.new-register a.close",
            "div.new-register .close-btn",
            ".modal-close",
            "a[onclick*='close']",
            "button.ant-modal-close",
            "span.ant-modal-close-x",
        ]

        
        found_any = False
        
        for sel in selectors:
            try:
                # Use XPath or CSS
                if sel.startswith("//") or sel.startswith("("):
                    elements = driver.find_elements(By.XPATH, sel)
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, sel)
                
                if elements:
                    # print(f"   [DEBUG] Found {len(elements)} matches for {sel}")
                    for el in elements:
                        try:
                            # Force click regardless of visibility reports
                            driver.execute_script("arguments[0].click();", el)
                            print(f"   🔔 Force-closed popup dengan (CSS/XPath): {sel}")
                            found_any = True
                            time.sleep(0.5) # Wait for animation
                        except:
                            continue
            except:
                continue
        
        # NUCLEAR OPTION: JS fallback for stubborn overlays
        try:
            driver.execute_script("""
                const selectors = ['.layui-layer', '.new-register', '.modal-backdrop', '.layui-layer-shade', '.pop-up', '.layui-layer-move'];
                selectors.forEach(sel => {
                    const elements = document.querySelectorAll(sel);
                    elements.forEach(el => {
                        el.style.display = 'none';
                        el.style.opacity = '0';
                        el.style.zIndex = '-1000';
                        el.style.pointerEvents = 'none'; // Ensure no interference
                    });
                });
            """)
        except:
            pass

                
        return found_any
    except:
        return False





def capture_network_response_optimized(driver, wait, timeout=1.5):
    """OPTIMIZED: Capture network response with concurrent popup handling
    
    This function captures API responses while handling popups in parallel,
    eliminating the 1-2s delay caused by sequential popup handling.
    """
    start_time = time.time()
    detail_api_url = "/async/raw/bill/detail"
    seen_request_ids = set()
    last_popup_check = 0
    POPUP_CHECK_INTERVAL = 0.5  # Check popup every 0.5s
    
    while time.time() - start_time < timeout:
        # Handle popup concurrently with very small timeout to avoid blocking
        if time.time() - last_popup_check >= POPUP_CHECK_INTERVAL:
            handle_popup(driver, wait, timeout=0.1)
            last_popup_check = time.time()
        
        try:
            # Get performance logs
            logs = driver.get_log('performance')
            
            for log in logs:
                try:
                    log_message = json.loads(log['message'])
                    message = log_message.get('message', {})
                    method = message.get('method', '')
                    
                    # Look for Network.responseReceived for our API
                    if method == 'Network.responseReceived':
                        response = message.get('params', {}).get('response', {})
                        url = response.get('url', '')
                        
                        if detail_api_url in url:
                            request_id = message['params']['requestId']
                            
                            # Skip if we already tried this request
                            if request_id in seen_request_ids:
                                continue
                            seen_request_ids.add(request_id)
                            
                            # Try to get response body immediately
                            try:
                                response_body = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
                                body_json = json.loads(response_body['body'])
                                
                                # Check if successful response
                                if body_json.get('state') == 0 and body_json.get('data'):
                                    detail_data = body_json['data']['detail']
                                    return detail_data  # RETURN IMMEDIATELY!
                                elif body_json.get('state') in [3001, 4003]:
                                    log_msg = "Session expired (3001)" if body_json.get('state') == 3001 else "Permission/Session error (4003)"
                                    print(f"   ⚠️ {log_msg.upper()}")
                                    return {"_needs_refresh": True, "_error_state": body_json.get('state')}
                            except:
                                # Response body not available yet, will retry on next poll
                                pass
                
                except:
                    continue
            
            # Poll very frequently for fast detection
            time.sleep(0.03)
        
        except Exception as e:
            print(f"   ⚠️ Error reading logs: {e}")
            time.sleep(0.2)
    
    print(f"   ⚠️ Network response not captured within {timeout}s")
    return None

def close_detail_modal(driver, wait):
    """Close the detail modal without redundant logs"""
    try:
        from src.utils import random_sleep # Import locally to avoid circular dep if utils is top level, but wait, I can just use time.sleep or import random_sleep from ..utils?
        # Let's import random_sleep relative to package root or just replicate it?
        # The plan is to have src/utils.py or just use imports
        pass
    except:
        pass
    
    # Simple sleep implementation to avoid complex imports here if possible, 
    # but maintaining consistency is better. 
    # Let's assume passed in 'random_sleep' or simple sleep.
    # The original code uses `random_sleep` from global utils.
    # I should import `random_sleep` correctly.
    # Assuming `src/utils.py` will be created.
    
    try:
        # Find close button
        close_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a.cancel.model-cancel"))
        )
        driver.execute_script("arguments[0].click();", close_btn)
        time.sleep(0.3)
    except Exception as e:
        # Fallback to direct JS without error logging unless both fail
        try:
            driver.execute_script("document.querySelector('a.cancel.model-cancel').click();")
            time.sleep(0.3)
        except:
            pass

def capture_network_response_with_reopen(driver, wait, detail_btn, max_loading_time=3, max_total_time=30):
    """Capture network response with smart modal reopening on slow loading"""
    attempt = 0
    total_start_time = time.time()
    
    while True:  # Retry indefinitely
        attempt += 1
        
        # Check if total time exceeded
        elapsed_total = time.time() - total_start_time
        if elapsed_total > max_total_time:
            print(f"   ⏱️ Total retry time exceeded {max_total_time}s ({elapsed_total:.1f}s)")
            print(f"   🔄 Triggering page refresh...")
            return {"_needs_refresh": True}
        
        if attempt > 1:
            print(f"   🔄 Attempt {attempt}: Closing and reopening modal... (elapsed: {elapsed_total:.1f}s)")
            
            # Close modal
            try:
                close_detail_modal(driver, wait)
                time.sleep(0.2)
            except:
                pass
            
            # Reopen modal by clicking detail button
            try:
                # User Request: Capture screenshot on 5th retry for debugging
                if attempt == 5:
                    screenshot_dir = "debug_screenshots"
                    os.makedirs(screenshot_dir, exist_ok=True)
                    screenshot_path = f"{screenshot_dir}/retry5_stt_{getattr(driver, '_last_stt', 'unknown')}_{time.strftime('%H%M%S')}.png"
                    driver.save_screenshot(screenshot_path)
                    print(f"   📸 Attempt 5: Saved debug screenshot to {screenshot_path}")

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", detail_btn)
                time.sleep(0.1)
                driver.execute_script("arguments[0].click();", detail_btn)
                time.sleep(0.5)
            except Exception as e:
                print(f"   ❌ Failed to reopen modal: {e}")
                continue
        
        # Wait for modal to appear
        try:
            wait.until(EC.presence_of_element_located((By.ID, "trade_detail")))
        except:
            print("   ⚠️ Modal did not appear")
            continue
        
        # CRITICAL: Handle popup that blocks loading
        handle_popup(driver, wait)
        time.sleep(0.2)
        
        # Try to capture response with timeout
        if attempt == 1:
            print(f"   🌐 Waiting for API response (max {max_loading_time}s)...")
        
        api_data = capture_network_response_sync(driver, timeout=max_loading_time)
        
        if api_data:
            print(f"   ✅ Response captured on attempt {attempt}! (total time: {elapsed_total:.1f}s)")
            return api_data
        else:
            print(f"   ⚠️ No response after {max_loading_time}s, will retry...")
            # Loop continues - will close and reopen

def check_network_activity(driver):
    """Check if network is stuck (302 redirect hung, no responses)"""
    try:
        # Get recent network activity from performance API
        script = """
        const entries = performance.getEntriesByType('resource');
        const recent = entries.slice(-10);  // Last 10 requests
        const now = Date.now();
        const last5Seconds = recent.filter(e => now - e.fetchStart < 5000);
        return {
            hasRecent: last5Seconds.length > 0,
            total: entries.length,
            recent: last5Seconds.length
        };
        """
        result = driver.execute_script(script)
        
        # If we have recent network activity, session is healthy
        if result and result.get('hasRecent'):
            print(f"   ℹ️ Network active: {result.get('recent')} requests in last 5s")
            return True
        else:
            print(f"   ⚠️ No network activity detected (possible inactivity)")
            return False
    except Exception as e:
        print(f"   ⚠️ Network check failed: {e}")
        return False  # Assume inactive if check fails
