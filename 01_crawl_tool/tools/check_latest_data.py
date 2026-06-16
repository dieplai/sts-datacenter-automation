import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.browser import get_driver
from src.core.auth import login_pro
import src.config as config
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def main():
    print(f"Logging in with {config.USERNAME}...")
    driver = get_driver(headless=False)
    try:
        if not login_pro(driver):
            print("Login failed.")
            return

        print("Login successful. Checking latest data for Vietnam Import...")
        # URL for Vietnam Import (country=110), data_type=2 (import), sorted by date desc
        url = "https://pro.52wmb.com/trades?data_type=2&country=110"
        driver.get(url)
        
        wait = WebDriverWait(driver, 30)
        try:
            # Wait for table
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.ant-table-body table tbody tr:nth-child(1)")))
            time.sleep(5) # Let JS settle
            
            rows = driver.find_elements(By.CSS_SELECTOR, "div.ant-table-body table tbody tr.ant-table-row")
            print(f"Found {len(rows)} rows on first page.")
            for i, row in enumerate(rows[:5]):
                 print(f"ROW {i+1}:", row.text.replace('\n', ' | '))
            
        except Exception as e:
            print(f"Could not read table data: {e}")
            
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
