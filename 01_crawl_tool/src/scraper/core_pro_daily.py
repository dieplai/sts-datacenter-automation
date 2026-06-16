"""
Daily Detail Scraper for Pro 2026 - Customs Data
=================================================
Scrapes transaction details day-by-day within a date range.

Key Features:
- Iterates through each calendar day in the configured date range
- Outputs one CSV + XLSX file per day
- Validates UI render via DOM Total cross-check (hits from API == HTML "Total N" div)
- Validates data correctness via First-Detail-Guard (checks date & hs fields of 1st record)
- No "expected_total" required - uses the above two validations instead
- Resume-safe: skips days that already have a complete file

Output path:
    output/daily/{country}/{datatype}/{hs_code}/{YYYY}/{MM}/
        {country}_{datatype}_{hs_code}_{YYYY}_{MM}_{DD}.csv
        {country}_{datatype}_{hs_code}_{YYYY}_{MM}_{DD}.xlsx
"""

import os
import re
import time
import json
import csv
import pandas as pd
from datetime import datetime, timedelta, date as date_type
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

try:
    from ..utils import log, Timer, human_click
    from . import api_client, navigator_pro
    from .core_pro_detail import ScraperProDetail
    from .. import config
except ImportError:
    import sys
    sys.path.append('../..')
    from src.utils import log, Timer, human_click
    from src.scraper import api_client, navigator_pro
    from src.scraper.core_pro_detail import ScraperProDetail
    from src import config


# ============================================================
# HELPERS
# ============================================================

def _safe_name(s):
    """Sanitize string for use in filenames."""
    return re.sub(r'[^a-zA-Z0-9]', '_', str(s)).strip('_')


def _get_day_output_dir(batch_item, target_date: date_type) -> str:
    """
    Build the output directory path for a given batch item and date.
    Pattern: output/daily/{country}/{datatype}/{hs_code}/{YYYY}/{MM}/
    """
    country = _safe_name(batch_item.get('country', 'unknown'))
    data_type = batch_item.get('data_type', '')
    datatype_short = 'import' if 'import' in data_type.lower() else 'export'
    hs_code = _safe_name(batch_item.get('hs_code', 'all'))
    year = target_date.strftime('%Y')
    month = target_date.strftime('%m')

    return os.path.join(
        config.OUTPUT_DIR, 'daily',
        country, datatype_short, hs_code,
        year, month
    )


def _get_day_file_stem(batch_item, target_date: date_type) -> str:
    """
    Build the filename stem (no extension) for a day's output.
    Pattern: {country}_{datatype}_{hs_code}_{YYYY}_{MM}_{DD}
    """
    country = _safe_name(batch_item.get('country', 'unknown'))
    data_type = batch_item.get('data_type', '')
    datatype_short = 'import' if 'import' in data_type.lower() else 'export'
    hs_code = _safe_name(batch_item.get('hs_code', 'all'))
    return f"{country}_{datatype_short}_{hs_code}_{target_date.strftime('%Y_%m_%d')}"


def _is_day_complete(batch_item, target_date: date_type) -> bool:
    """
    Check if a day has already been scraped and saved completely.
    A day is considered complete if both CSV and Excel files exist and the CSV is non-empty.
    """
    out_dir = _get_day_output_dir(batch_item, target_date)
    stem = _get_day_file_stem(batch_item, target_date)
    csv_path = os.path.join(out_dir, stem + '.csv')
    xlsx_path = os.path.join(out_dir, stem + '.xlsx')

    if not os.path.exists(csv_path):
        return False

    try:
        size = os.path.getsize(csv_path)
        if size < 20:  # Empty or header-only
            return False
        # Quick row count
        df = pd.read_csv(csv_path, encoding='utf-8-sig', nrows=2)
        return len(df) >= 1
    except Exception:
        return False


def _iter_dates(start_str: str, end_str: str):
    """Yield date objects from start_str to end_str (inclusive)."""
    start = datetime.strptime(start_str, '%Y-%m-%d').date()
    end = datetime.strptime(end_str, '%Y-%m-%d').date()
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _date_str(d: date_type) -> str:
    return d.strftime('%Y-%m-%d')


# ============================================================
# DAILY SCRAPER CLASS
# ============================================================

class DailyDetailScraper:
    """
    Wraps ScraperProDetail to iterate day-by-day.
    For each day:
      1. Set start_date = end_date = that day in the batch_config
      2. Call prepare_and_validate_search() which does:
         a. Fill form & click search
         b. DOM cross-check: HTML Total == API hits (ensures table rendered)
         c. Capture first detail → validate date & hs_code (First-Detail-Guard)
      3. Iterate pages, scrape all rows, save to daily file
      4. Convert to XLSX
    """

    MAX_PAGES_PER_SEGMENT = ScraperProDetail.MAX_PAGES_PER_SEGMENT  # 333
    ROWS_PER_PAGE = ScraperProDetail.ROWS_PER_PAGE  # 30

    def __init__(self, driver, wait, batch_item: dict):
        self.driver = driver
        self.wait = wait
        self.batch_item = batch_item

        # Reuse ScraperProDetail for actual page scraping & CSV logic
        # csv_file will be set per-day before scraping
        self._detail = ScraperProDetail(driver, wait, csv_file=None)

    # ----------------------------------------------------------
    # VALIDATION: DOM cross-check
    # ----------------------------------------------------------

    def get_dom_total(self) -> int | None:
        """
        Read the "Total N" value from the HTML DOM.
        Targets: <div style="margin-bottom: 15px; color: rgb(30, 30, 30);">Total 512</div>
        Falls back to page_source regex.
        Returns int or None.
        """
        try:
            # Strategy 1: Page source regex (fastest, most reliable for React)
            source = self.driver.page_source
            match = re.search(r'>\s*Total\s+([\d,]+)\s*<', source, re.IGNORECASE)
            if match:
                return int(match.group(1).replace(',', ''))

            # Strategy 2: XPATH on the known div style
            els = self.driver.find_elements(
                By.XPATH,
                "//div[contains(@style,'margin-bottom: 15px') and contains(text(),'Total')]"
            )
            for el in els:
                txt = el.text.strip()
                m = re.search(r'Total\s+([\d,]+)', txt, re.IGNORECASE)
                if m:
                    return int(m.group(1).replace(',', ''))
        except Exception as e:
            log(f"⚠️ DOM Total read failed: {e}", "WARNING")
        return None

    def get_api_hits(self, flush_first=True) -> int | None:
        """
        Capture the 'hits' field from the list API response via performance logs.
        Returns int or None.
        """
        try:
            if flush_first:
                try:
                    _ = self.driver.get_log('performance')
                except Exception:
                    pass

            # Wait briefly for network traffic to settle
            time.sleep(0.5)

            logs = self.driver.get_log('performance')
            for entry in reversed(logs):
                try:
                    msg = json.loads(entry['message'])['message']
                    if msg.get('method') != 'Network.responseReceived':
                        continue
                    url = msg.get('params', {}).get('response', {}).get('url', '')
                    if '/api/' not in url and '/list' not in url.lower():
                        continue
                    req_id = msg['params']['requestId']
                    body = self.driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': req_id})
                    data = json.loads(body.get('body', '{}'))
                    hits = data.get('data', {}).get('hits')
                    if hits is not None:
                        return int(hits)
                except Exception:
                    continue
        except Exception as e:
            log(f"⚠️ API hits read failed: {e}", "WARNING")
        return None

    def wait_for_table_rendered(self, api_hits: int | None, timeout: float = 30.0) -> bool:
        """
        Wait until DOM Total matches api_hits.
        If api_hits is unavailable, just wait for DOM Total to appear.
        Returns True when stable, False on timeout.
        """
        start = time.time()
        poll = 0.8

        # If hits = 0 (no data for that day), DOM should also show 0
        # We accept that as "rendered" too.

        while time.time() - start < timeout:
            dom_total = self.get_dom_total()

            if dom_total is None:
                # Table might not have rendered yet
                time.sleep(poll)
                continue

            if api_hits is None:
                # No API reference — just accept first non-None DOM total
                log(f"   ✅ DOM Total appeared: {dom_total} (no API reference)", "DEBUG")
                return True

            if dom_total == api_hits:
                log(f"   ✅ DOM Total confirmed: {dom_total:,} == API hits {api_hits:,}", "DEBUG")
                return True

            log(f"   ⏳ DOM={dom_total} ≠ API hits={api_hits}, waiting...", "DEBUG")
            time.sleep(poll)

        log("   ⚠️ Timeout waiting for DOM Total to match API hits", "WARNING")
        return False

    # ----------------------------------------------------------
    # VALIDATION: First-Detail-Guard
    # ----------------------------------------------------------

    def validate_first_detail(self, target_date: date_type, hs_code: str) -> bool:
        """
        Click the first "Details" link, capture the detail record, and validate:
          - record['date'] matches target_date (YYYY-MM-DD)
          - record['hs'] starts with hs_code (if hs_code is set)

        Returns True if validated OK, False if mismatch (caller should re-search).
        """
        try:
            # Flush performance logs before clicking
            try:
                _ = self.driver.get_log('performance')
            except Exception:
                pass

            detail_links = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Details')]")
            if not detail_links:
                log("   ⚠️ First-Detail-Guard: No 'Details' links found on page", "WARNING")
                return False

            first_link = detail_links[0]
            response_data = self._detail.click_details_and_capture(first_link, row_num=1)

            if not response_data:
                log("   ⚠️ First-Detail-Guard: Could not capture detail response", "WARNING")
                return False

            tx = response_data.get('detail', {})
            if not tx:
                log("   ⚠️ First-Detail-Guard: Empty detail data", "WARNING")
                return False

            target_str = _date_str(target_date)

            # -- Date check --
            tx_date = tx.get('date', '')
            if not tx_date:
                log("   ⚠️ First-Detail-Guard: 'date' field missing in detail", "WARNING")
                return False

            # Normalize date (some responses may include time)
            tx_date_normalized = str(tx_date).strip()[:10]

            if tx_date_normalized != target_str:
                log(f"   ❌ First-Detail-Guard DATE MISMATCH: record={tx_date_normalized}, expected={target_str}", "WARNING")
                return False

            # -- HS Code check (if configured) --
            if hs_code:
                tx_hs = str(tx.get('hs', '')).strip()
                if not tx_hs.startswith(hs_code):
                    log(f"   ❌ First-Detail-Guard HS MISMATCH: record={tx_hs}, expected prefix={hs_code}", "WARNING")
                    return False

            log(f"   ✅ First-Detail-Guard PASSED: date={tx_date_normalized}, hs={tx.get('hs', 'N/A')}", "SUCCESS")
            return True

        except Exception as e:
            log(f"   ⚠️ First-Detail-Guard error: {e}", "WARNING")
            return False

    # ----------------------------------------------------------
    # SEARCH + VALIDATE LOOP
    # ----------------------------------------------------------

    def prepare_and_validate_search(self, target_date: date_type) -> bool:
        """
        Fill form for a single day, click search, then run two validation layers:
          1. DOM cross-check (wait for UI render)
          2. First-Detail-Guard (check date + hs of first record)

        Retries indefinitely until both pass (caller handles KeyboardInterrupt).

        Returns True when validated, False only on catastrophic error.
        """
        hs_code = self.batch_item.get('hs_code', '')
        date_str = _date_str(target_date)

        # Build a one-day batch_config for fill_search_form_detail
        day_batch_config = {
            'country': self.batch_item.get('country', 'Vietnam'),
            'data_type': self.batch_item.get('data_type', 'Import data'),
            'hs_code': hs_code,
            'start_date': date_str,
            'end_date': date_str,
            # Pass through optional filters
            'buyer':    self.batch_item.get('buyer', ''),
            'supplier': self.batch_item.get('supplier', ''),
            'product':  self.batch_item.get('product', ''),
        }

        attempt = 0
        while True:
            attempt += 1
            log(f"\n🔍 [Day {date_str}] Search attempt {attempt}...", "PROCESS")

            # ---- Step 1: Fill form ----
            # Clear form first (if not first attempt)
            if attempt > 1:
                try:
                    navigator_pro.clear_search_form_detail(self.driver, self.wait)
                except Exception:
                    pass

            form_ok = navigator_pro.fill_search_form_detail(
                self.driver, self.wait,
                end_date_override=date_str,  # Use single day as both start+end
                batch_config=day_batch_config
            )
            if not form_ok:
                log(f"   ⚠️ Form fill failed (attempt {attempt}), retrying...", "WARNING")
                time.sleep(3)
                self._try_soft_recovery(day_batch_config)
                continue

            # ---- Step 2: Click Search ----
            try:
                # Flush performance logs BEFORE clicking search
                try:
                    _ = self.driver.get_log('performance')
                except Exception:
                    pass

                navigator_pro.click_search_button_detail(self.driver, self.wait)
                time.sleep(2.0)  # Give browser time to fire the API request
            except Exception as e:
                log(f"   ⚠️ Search click failed: {e}", "WARNING")
                time.sleep(3)
                continue

            # ---- Step 3: Capture API hits (before Wait so we have a reference) ----
            api_hits = self.get_api_hits(flush_first=False)
            log(f"   📡 API hits: {api_hits}", "DEBUG")

            # ---- Step 4: DOM Cross-check ----
            log(f"   ⏳ Waiting for DOM Total to match API hits ({api_hits})...", "DEBUG")
            dom_ok = self.wait_for_table_rendered(api_hits, timeout=30)

            if not dom_ok:
                log(f"   ⚠️ DOM cross-check failed (attempt {attempt}), retrying search...", "WARNING")
                time.sleep(2)
                continue

            dom_total = self.get_dom_total()
            log(f"   📋 DOM Total confirmed: {dom_total}", "INFO")

            # ---- Special case: 0 records for this day ----
            if dom_total == 0:
                log(f"   ℹ️ Day {date_str} has 0 records. Marking complete (empty day).", "INFO")
                return True  # Let caller handle empty-day logic

            # ---- Step 5: First-Detail-Guard ----
            log(f"   🔎 Running First-Detail-Guard...", "INFO")
            guard_ok = self.validate_first_detail(target_date, hs_code)

            if not guard_ok:
                log(f"   ❌ First-Detail-Guard FAILED (attempt {attempt}). Re-searching...", "WARNING")
                time.sleep(3)
                # Re-clear and retry
                try:
                    navigator_pro.click_all_clear(self.driver, self.wait)
                    time.sleep(2)
                except Exception:
                    pass
                continue

            log(f"   ✅ Search validated for day {date_str} ({dom_total:,} records)", "SUCCESS")
            return True

    def _try_soft_recovery(self, day_batch_config: dict):
        """Attempt a soft recovery, and escalate to deep recovery if browser is dead or session expired/wrong page."""
        try:
            log("   🔄 Attempting soft recovery (refresh)...", "INFO")
            self.driver.refresh()
            time.sleep(5)
            api_client.wait_for_loading_overlay(self.driver, timeout=30)
            api_client.handle_popup(self.driver, self.wait)
            
            # Check if we were kicked out to login or another page
            current_url = self.driver.current_url.lower()
            needs_relogin = False
            try:
                login_form = self.driver.find_element(By.ID, "formLogin")
                if login_form.is_displayed():
                    needs_relogin = True
            except:
                pass
                
            if needs_relogin or "customsdata" not in current_url:
                log("   ⚠️ Session expired or wrong page detected after refresh. Escalating to DEEP recovery...", "WARNING")
                success = self._detail.perform_deep_recovery(batch_config=day_batch_config)
                if success:
                    log("   ✅ Deep recovery restored browser session.", "SUCCESS")
                    self.driver = self._detail.driver
                    self.wait = self._detail.wait
                    return True
                else:
                    log("   ❌ Deep recovery failed to restore session.", "ERROR")
                    return False

            return True
        except Exception as e:
            err_str = str(e)
            log(f"   ⚠️ Soft recovery error: {err_str}", "WARNING")
            
            # Detect dead socket / crashed browser
            if "Max retries exceeded" in err_str or "WinError 10061" in err_str or "disconnected" in err_str or "not reachable" in err_str:
                log("   ⬆️ Browser connection dead! Escalating to DEEP recovery...", "ERROR")
                success = self._detail.perform_deep_recovery(batch_config=day_batch_config)
                
                if success:
                    log("   ✅ Deep recovery restored browser session.", "SUCCESS")
                    # Vital: synchronize driver and wait references!
                    self.driver = self._detail.driver
                    self.wait = self._detail.wait
                    return True
                else:
                    log("   ❌ Deep recovery failed to restore session.", "ERROR")
                    raise e # Bubble up to abort day
            return False

    # ----------------------------------------------------------
    # SCRAPE ONE DAY
    # ----------------------------------------------------------

    def scrape_day(self, target_date: date_type) -> bool:
        """
        Scrape all records for a single day.
        Returns True on success (including empty day), False on abort.
        """
        date_str = _date_str(target_date)
        out_dir = _get_day_output_dir(self.batch_item, target_date)
        stem = _get_day_file_stem(self.batch_item, target_date)
        csv_path = os.path.join(out_dir, stem + '.csv')
        xlsx_path = os.path.join(out_dir, stem + '.xlsx')
        os.makedirs(out_dir, exist_ok=True)

        log(f"\n{'='*65}", "PROCESS")
        log(f"📅 DAILY SCRAPER: {date_str}", "PROCESS")
        log(f"{'='*65}", "PROCESS")

        # ---- Validate + set up search ----
        ok = self.prepare_and_validate_search(target_date)
        if not ok:
            log(f"❌ Fatal error setting up search for {date_str}", "ERROR")
            return False

        # ---- Check if 0 records ----
        dom_total = self.get_dom_total()
        if dom_total == 0:
            log(f"   ℹ️ Skipping day {date_str} — no records.", "INFO")
            # Write an empty CSV with just a header to mark day as "done"
            self._write_empty_day_marker(csv_path)
            return True

        # ---- Attach the day's CSV file to the detail scraper ----
        self._detail.csv_file = csv_path
        self._detail.excel_file = xlsx_path
        self._detail.current_segment = 1
        self._detail.current_page = 1
        self._detail.current_stt = 1
        self._detail.total_scraped = 0
        self._detail.segment_end_date = None
        self._detail.last_known_transaction = None
        self._detail.first_transaction_of_segment = None

        # ---- Initialize CSV ----
        self._detail.initialize_csv()

        # ---- Page scraping loop ----
        total_scraped = 0
        current_page = 1
        max_pages = self.MAX_PAGES_PER_SEGMENT  # 333 hard limit per segment (day)

        # Ensure pagination starts from page 1
        try:
            navigator_pro.reset_pagination_to_page_one(self.driver, self.wait)
        except Exception:
            pass

        import math
        expected_total_pages = min(math.ceil(dom_total / self.ROWS_PER_PAGE) if dom_total else max_pages, max_pages)
        day_timer = Timer()

        while current_page <= max_pages:
            eta_str = ""
            if current_page > 1:
                elapsed_day = (datetime.now() - day_timer.start_time).total_seconds()
                avg_per_page = elapsed_day / (current_page - 1)
                remaining_pages = max(0, expected_total_pages - current_page + 1)
                eta_secs = avg_per_page * remaining_pages
                eta_h = int(eta_secs // 3600)
                eta_m = int((eta_secs % 3600) // 60)
                eta_s = int(eta_secs % 60)
                if eta_h > 0:
                    eta_str = f"| ETA: {eta_h}h {eta_m}m {eta_s}s"
                else:
                    eta_str = f"| ETA: {eta_m}m {eta_s}s"

            log(f"\n   📄 Page {current_page}/{expected_total_pages} (Day {date_str}) {eta_str}", "INFO")

            page_txs = self._detail.scrape_page(current_page, segment_num=1, start_stt=1)

            if not page_txs:
                if current_page == 1:
                    log(f"   ⚠️ No data on page 1. May be rendering issue.", "WARNING")
                    # Re-validate search (guard will retry internally)
                    ok = self.prepare_and_validate_search(target_date)
                    if not ok:
                        return False
                    # After re-validate, reset pagination and retry page 1
                    try:
                        navigator_pro.reset_pagination_to_page_one(self.driver, self.wait)
                    except Exception:
                        pass
                    page_txs = self._detail.scrape_page(current_page, segment_num=1, start_stt=1)
                    if not page_txs:
                        log(f"   ❌ Still no data after re-validation. Marking day complete.", "WARNING")
                        break
                else:
                    log(f"   ⚠️ 0 rows detected on page {current_page} - possible session expiry.", "WARNING")
                    log("   🔄 Attempting recovery before confirming end of data...", "INFO")
                    
                    day_batch_config = {
                        'country': self.batch_item.get('country', 'Vietnam'),
                        'data_type': self.batch_item.get('data_type', 'Import data'),
                        'hs_code': self.batch_item.get('hs_code', ''),
                        'start_date': _date_str(target_date),
                        'end_date': _date_str(target_date),
                        'buyer': self.batch_item.get('buyer', ''),
                        'supplier': self.batch_item.get('supplier', ''),
                        'product': self.batch_item.get('product', ''),
                    }
                    
                    recover_ok = self._try_soft_recovery(day_batch_config)
                    if recover_ok:
                        # Need to re-fill and re-search after recovery to restore page state
                        ok = self.prepare_and_validate_search(target_date)
                        if ok:
                            # Jump back to current page
                            log(f"   ⏭️  Jumping back to page {current_page}...", "INFO")
                            if current_page > 1:
                                self._detail.go_to_page(current_page)
                            
                            # Retry scrape
                            page_txs = self._detail.scrape_page(current_page, segment_num=1, start_stt=1)
                            
                    if not page_txs:
                        log(f"   ℹ️ Still no data at page {current_page} after recovery. End of day.", "INFO")
                        break
                    else:
                        log(f"   ✅ Recovery successful! Resuming from page {current_page}.", "SUCCESS")

            # ---- Validate scraped records (date + hs filter) ----
            valid_txs = self._validate_page_records(page_txs, target_date)

            if valid_txs:
                # Add segment/page/stt metadata
                for i, tx in enumerate(valid_txs):
                    tx['segment'] = 1
                    tx['page'] = current_page
                    tx['stt'] = i + 1

                self._detail.append_to_csv(valid_txs)
                total_scraped += len(valid_txs)
                log(f"   ✅ Page {current_page}: {len(valid_txs)} records (total so far: {total_scraped:,})", "SUCCESS")
            else:
                log(f"   ⚠️ Page {current_page}: 0 valid records after filtering. Stopping.", "WARNING")
                break

            # ---- Check next page ----
            if not self._detail.has_next_page():
                log(f"   🏁 No more pages. Day {date_str} complete: {total_scraped:,} records.", "SUCCESS")
                break

            current_page += 1
            if not self._detail.go_to_next_page():
                log(f"   ⚠️ Could not navigate to page {current_page}.", "WARNING")
                break

            time.sleep(1.5)

        # ---- NOTE on >10k records ----
        if current_page >= max_pages:
            log(f"   ⚠️ Day {date_str} hit 10k limit (page {max_pages}). "
                f"Consider splitting by sub-HS code for future development.", "WARNING")

        log(f"\n   📊 Day {date_str}: {total_scraped:,} records scraped.", "SUCCESS")

        # ---- Convert to Excel ----
        if total_scraped > 0:
            self._convert_to_excel(csv_path, xlsx_path)

        return True

    def _validate_page_records(self, transactions: list, target_date: date_type) -> list:
        """
        Filter page transactions to only include records whose date matches target_date.
        Also checks that hs starts with the configured hs_code (if set).
        Logs any mismatches as warnings (data drift detection).
        """
        target_str = _date_str(target_date)
        hs_code = self.batch_item.get('hs_code', '')
        valid = []
        drift_count = 0

        for tx in transactions:
            tx_date = str(tx.get('date', '')).strip()[:10]
            tx_hs = str(tx.get('hs', '')).strip()

            date_ok = (tx_date == target_str)
            hs_ok = (not hs_code) or tx_hs.startswith(hs_code)

            if date_ok and hs_ok:
                valid.append(tx)
            else:
                drift_count += 1
                if drift_count <= 3:  # Limit log noise
                    log(f"   ⚠️ DATA DRIFT: date={tx_date} (expected {target_str}), "
                        f"hs={tx_hs} (prefix {hs_code})", "WARNING")

        if drift_count > 3:
            log(f"   ⚠️ ... and {drift_count - 3} more drift records suppressed.", "WARNING")

        return valid

    def _write_empty_day_marker(self, csv_path: str):
        """Write a zero-row CSV (header only) to mark an empty day as processed."""
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['segment', 'page', 'stt', 'date', 'hs', 'note'])
                writer.writerow([1, 1, 0, '', '', 'empty_day'])
        except Exception as e:
            log(f"   ⚠️ Could not write empty day marker: {e}", "WARNING")

    def _convert_to_excel(self, csv_path: str, xlsx_path: str):
        """Convert day CSV to Excel."""
        try:
            import re as _re

            def sanitize(value):
                if pd.isna(value) or not isinstance(value, str):
                    return value
                return _re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', value)

            df = pd.read_csv(csv_path, encoding='utf-8-sig', on_bad_lines='skip', low_memory=False)
            try:
                df = df.applymap(sanitize) if hasattr(df, 'applymap') else df.map(sanitize)
            except Exception:
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = df[col].apply(sanitize)

            try:
                import xlsxwriter
                engine = 'xlsxwriter'
            except ImportError:
                engine = 'openpyxl'

            df.to_excel(xlsx_path, index=False, engine=engine)
            log(f"   📊 Excel saved: {os.path.basename(xlsx_path)} ({len(df):,} rows)", "SUCCESS")
        except Exception as e:
            log(f"   ⚠️ Excel conversion failed: {e}", "WARNING")

    # ----------------------------------------------------------
    # BATCH RUNNER
    # ----------------------------------------------------------

    def run_batch(self) -> bool:
        """
        Run the daily scraper for the configured batch_item date range.
        Iterates each day from start_date to end_date, skipping completed days.
        """
        start_str = self.batch_item.get('start_date', '')
        end_str = self.batch_item.get('end_date', '')
        name = self.batch_item.get('name', 'unnamed')

        if not start_str or not end_str:
            log(f"❌ Daily batch '{name}': missing start_date or end_date", "ERROR")
            return False

        all_dates = list(_iter_dates(start_str, end_str))
        total_days = len(all_dates)

        # Pre-scan: show status
        pending = []
        done = []
        for d in all_dates:
            if _is_day_complete(self.batch_item, d):
                done.append(d)
            else:
                pending.append(d)

        log(f"\n{'='*65}", "PROCESS")
        log(f"📋 DAILY BATCH: {name}", "PROCESS")
        log(f"   Range: {start_str} → {end_str} ({total_days} days)", "INFO")
        log(f"   ✅ Complete: {len(done)} days | ⏳ Pending: {len(pending)} days", "INFO")
        log(f"{'='*65}\n", "PROCESS")

        if not pending:
            log(f"✅ All days already complete for batch '{name}'", "SUCCESS")
            return True

        timer = Timer()
        days_done = 0
        days_failed = 0

        for day_idx, target_date in enumerate(all_dates, 1):
            if _is_day_complete(self.batch_item, target_date):
                log(f"⏭️  [{day_idx}/{total_days}] {_date_str(target_date)} — already complete, skipping.", "INFO")
                continue

            log(f"\n📅 [{day_idx}/{total_days}] Processing {_date_str(target_date)}...", "PROCESS")

            try:
                success = self.scrape_day(target_date)
                if success:
                    days_done += 1
                    elapsed = (datetime.now() - timer.start_time).total_seconds()
                    if days_done > 0:
                        avg_per_day = elapsed / days_done
                        remaining_days = len([d for d in all_dates[day_idx:] if not _is_day_complete(self.batch_item, d)])
                        eta_secs = avg_per_day * remaining_days
                        eta_h = int(eta_secs // 3600)
                        eta_m = int((eta_secs % 3600) // 60)
                        log(f"   📈 Progress: {days_done}/{len(pending)} pending days done | ETA: {eta_h}h {eta_m}m", "INFO")
                else:
                    days_failed += 1
                    log(f"   ❌ Day {_date_str(target_date)} failed.", "ERROR")

            except KeyboardInterrupt:
                log("\n🛑 User interrupted daily batch.", "WARNING")
                raise

            except Exception as e:
                log(f"   ❌ Unexpected error for {_date_str(target_date)}: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                days_failed += 1

        # Summary
        elapsed = (datetime.now() - timer.start_time).total_seconds()
        log(f"\n{'='*65}", "SUCCESS")
        log(f"✅ DAILY BATCH COMPLETE: {name}", "SUCCESS")
        log(f"   ✅ Days done: {days_done} | ❌ Failed: {days_failed}", "INFO")
        log(f"   ⏱️  Total time: {int(elapsed//3600)}h {int((elapsed%3600)//60)}m", "INFO")
        log(f"{'='*65}\n", "SUCCESS")

        return days_failed == 0


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def main_pro_detail_daily():
    """
    Main entry point for Daily Detail Mode.
    Loops through DAILY_BATCH items, running day-by-day scraping for each.
    Reuses the same browser session for all items.
    """
    try:
        log("\n" + "="*65, "PROCESS")
        log("🚀 PRO 2026 DAILY DETAIL MODE SCRAPER (SINGLE CONFIG)", "PROCESS")
        log("="*65 + "\n", "PROCESS")

        # Create a single batch item from DETAIL_* config
        daily_config = {
            'name': 'daily_single_run',
            'country': getattr(config, 'DETAIL_COUNTRY', 'Vietnam'),
            'data_type': getattr(config, 'DETAIL_DATA_TYPE', 'Import data'),
            'hs_code': getattr(config, 'DETAIL_HS_CODE', ''),
            'start_date': getattr(config, 'DETAIL_START_DATE', ''),
            'end_date': getattr(config, 'DETAIL_END_DATE', ''),
            'buyer': getattr(config, 'DETAIL_BUYER', ''),
            'supplier': getattr(config, 'DETAIL_SUPPLIER', ''),
            'product': getattr(config, 'DETAIL_PRODUCT', ''),
        }

        if not daily_config['start_date'] or not daily_config['end_date']:
            log("❌ DETAIL_START_DATE or DETAIL_END_DATE is missing. Check config.py.", "ERROR")
            return False

        daily_batch = [daily_config]

        log(f"📋 Running Daily Mode for:", "INFO")
        log(f"   Country: {daily_config['country']} | Type: {daily_config['data_type']}", "INFO")
        log(f"   HS Code: {daily_config['hs_code']}", "INFO")
        log(f"   Range  : {daily_config['start_date']} → {daily_config['end_date']}", "INFO")

        # ---- Driver setup ----
        try:
            from ..driver_setup import get_driver
        except ImportError:
            from src.driver_setup import get_driver

        from selenium.webdriver.support.ui import WebDriverWait

        driver = get_driver(headless=False)
        wait = WebDriverWait(driver, 20)

        # ---- Login ----
        log("🔐 Logging in...", "PROCESS")
        try:
            pro_login_url = getattr(config, 'PRO_LOGIN_URL', "https://pro.52wmb.com/user/login?redirect=%2FWorkbenches")
            log(f"📍 Navigating to Pro Login: {pro_login_url}", "INFO")
            driver.get(pro_login_url)
            time.sleep(3)

            if "/Workbenches" in driver.current_url:
                log("✅ Already logged in", "SUCCESS")
            else:
                from selenium.webdriver.support.ui import WebDriverWait as _WDW
                slow_wait = _WDW(driver, 60)
                user_field = None
                for attempt in range(3):
                    try:
                        user_field = slow_wait.until(EC.element_to_be_clickable((By.ID, "username")))
                        break
                    except Exception:
                        log(f"⚠️ Login form not ready (attempt {attempt+1}/3), refreshing...", "WARNING")
                        try:
                            driver.refresh()
                            time.sleep(5)
                        except Exception:
                            pass

                if not user_field:
                    raise Exception("Login form never appeared after 3 refreshes")

                log("Filling credentials...", "INFO")
                # Username
                user_field.click()
                time.sleep(0.5)
                user_field.clear()
                time.sleep(0.5)
                user_field.send_keys(config.USERNAME)
                time.sleep(1)

                # Password
                pass_field = slow_wait.until(EC.element_to_be_clickable((By.ID, "password")))
                pass_field.click()
                time.sleep(0.5)
                pass_field.clear()
                time.sleep(0.5)
                pass_field.send_keys(config.PASSWORD)
                
                # Critical wait before submit for React state refresh
                time.sleep(2)
                
                log("Submitting login form...", "PROCESS")
                submit_btn = slow_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".login-button")))
                try:
                    submit_btn.click()
                except:
                    driver.execute_script("arguments[0].click();", submit_btn)
                time.sleep(1)

                log("Waiting for authentication...", "INFO")
                try:
                    slow_wait.until(EC.url_contains("/Workbenches"))
                    log("✅ Login successful", "SUCCESS")
                except Exception:
                    if "/login" in driver.current_url:
                        log("❌ Still on login page. Check credentials.", "ERROR")
                        driver.quit()
                        return False

            api_client.handle_popup(driver, wait, timeout=3)

        except Exception as e:
            log(f"❌ Login error: {e}", "ERROR")
            driver.quit()
            return False

        # ---- Navigate to Customs Data ----
        log("📍 Navigating to Customs Data...", "PROCESS")
        if not navigator_pro.navigate_from_home_pro(driver, wait, pro_mode="detail"):
            log("❌ Navigation failed", "ERROR")
            driver.quit()
            return False

        # ---- Process each daily batch item ----
        total_success = 0
        total_failed = 0

        for idx, batch_item in enumerate(daily_batch, 1):
            item_name = batch_item.get('name', f'item_{idx}')
            log(f"\n{'='*65}", "PROCESS")
            log(f"📋 BATCH ITEM [{idx}/{len(daily_batch)}]: {item_name}", "PROCESS")
            log(f"{'='*65}", "PROCESS")

            # Clear form between batch items
            if idx > 1:
                try:
                    log("🔄 Clearing search form...", "INFO")
                    navigator_pro.clear_search_form_detail(driver, wait)
                except Exception as e:
                    log(f"⚠️ Clear form failed: {e}", "WARNING")

            try:
                daily_scraper = DailyDetailScraper(driver, wait, batch_item)
                success = daily_scraper.run_batch()

                if success:
                    total_success += 1
                else:
                    total_failed += 1

            except KeyboardInterrupt:
                log("\n🛑 User interrupted. Stopping.", "WARNING")
                break
            except Exception as e:
                log(f"❌ Batch item '{item_name}' failed: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                total_failed += 1

        # ---- Final summary ----
        log(f"\n{'='*65}", "SUCCESS")
        log(f"📊 DAILY MODE COMPLETE", "SUCCESS")
        log(f"   ✅ Successful batches: {total_success}/{len(daily_batch)}", "INFO")
        if total_failed > 0:
            log(f"   ❌ Failed batches: {total_failed}/{len(daily_batch)}", "WARNING")
        log(f"{'='*65}\n", "SUCCESS")

        log("🔄 Closing browser in 10 seconds...", "INFO")
        time.sleep(10)
        driver.quit()

        return total_failed == 0

    except Exception as e:
        log(f"❌ Daily main failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    main_pro_detail_daily()
