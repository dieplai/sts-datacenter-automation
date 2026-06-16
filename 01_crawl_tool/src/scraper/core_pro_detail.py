"""
Detail Mode Scraper for Pro 2026 - Customs Data
Scrapes transaction details from Market Analysis > Customs Data page
Uses checkpoint system like legacy mode with segment/page/stt tracking
"""

import time
import json
import os
import csv
import threading
import pandas as pd
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import zipfile
import subprocess
import undetected_chromedriver as uc
from selenium import webdriver

try:
    from ..observability import log, Timer, SessionExpired, ApiError, RateMeter
    from ..utils import human_click, random_sleep
    from . import api_client, navigator_pro
    from ..extract import http_fetcher as _http_client_mod
    from ..extract import DetailCapture
    from ..extract.async_fetcher import fetch_many
    from ..parsing import (
        FIELD_MAPPING as _PARSING_FIELD_MAPPING,
        ALIASES as _PARSING_ALIASES,
        update_mapping_from_server as _parsing_update_mapping,
        extract_transaction_date as _parsing_extract_date,
        get_transaction_id as _parsing_get_tx_id,
    )
    from ..storage import (
        generate_output_filename as _storage_generate_filename,
        detect_resume_point as _storage_detect_resume,
        CsvSink,
        convert_to_excel as _storage_convert_to_excel,
    )
    from ..nav import pagination as _nav_pagination
    from .. import config
except ImportError:
    import sys
    sys.path.append('..')
    from src.observability import log, Timer, SessionExpired, ApiError, RateMeter
    from src.utils import human_click, random_sleep
    from src.scraper import api_client, navigator_pro
    from src.extract import http_fetcher as _http_client_mod
    from src.extract import DetailCapture
    from src.extract.async_fetcher import fetch_many
    from src.parsing import (
        FIELD_MAPPING as _PARSING_FIELD_MAPPING,
        ALIASES as _PARSING_ALIASES,
        update_mapping_from_server as _parsing_update_mapping,
        extract_transaction_date as _parsing_extract_date,
        get_transaction_id as _parsing_get_tx_id,
    )
    from src.storage import (
        generate_output_filename as _storage_generate_filename,
        detect_resume_point as _storage_detect_resume,
        CsvSink,
        convert_to_excel as _storage_convert_to_excel,
    )
    from src.nav import pagination as _nav_pagination
    from src import config

def force_kill_chrome():
    try:
        # Tắt ép buộc mọi tiến trình chromedriver trên hệ thống để chặn kẹt RAM
        subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe', '/T'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except:
        pass


_FILTER_PUNCT_RE = None  # lazy-init


def _hs_prefix_matches(expected_hs, actual_hs):
    """OR-aware HS code prefix check.

    `DETAIL_HS_CODE` có thể chứa `|` cho nhiều HS prefix (vd `"52|55"`
    crawl cả chapter 52 và 55). Server 52WMB hiểu `|` là OR; client-side
    filter guard cũng phải hỗ trợ.

    Trả về True nếu `actual_hs` startswith BẤT KỲ alternative nào của
    `expected_hs`. Mỗi alternative strip + lowercase. Alt rỗng skip.
    """
    if not expected_hs:
        return True
    actual = (actual_hs or '').strip().lower()
    if not actual:
        return True  # no data = let through
    alternatives = [
        a.strip().lower()
        for a in expected_hs.split('|')
        if a.strip()
    ]
    if not alternatives:
        return True
    return any(actual.startswith(alt) for alt in alternatives)


def _tokenize_for_filter(s):
    """Lowercase + whitespace-normalize + split on punctuation (keeping `&`).

    `'B&E Bio-Technology Co., Ltd.'` → `['b&e', 'bio', 'technology', 'co', 'ltd']`

    Giữ `&` vì là một phần của brand name (vd. `'b&e'`). Split hyphen/dot/
    comma/semicolon/colon/underscore/slash/parens vì 52WMB data có thể
    join hoặc tách các token này tùy nguồn (list vs detail endpoint).
    """
    global _FILTER_PUNCT_RE
    if _FILTER_PUNCT_RE is None:
        import re as _re
        _FILTER_PUNCT_RE = _re.compile(r'[\-_./,;:()\[\]\\/]+')
    s = ' '.join(str(s or '').lower().split())
    s = _FILTER_PUNCT_RE.sub(' ', s)
    return s.split()


def _common_prefix_len(a, b):
    n = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            n += 1
        else:
            break
    return n


def _token_fuzzy_match(et, actual_tokens, fuzzy_threshold=0.85,
                       prefix_min_chars=5, prefix_min_ratio=0.70):
    """True nếu expected token `et` có substring / fuzzy / prefix-overlap
    match với bất kỳ token nào trong `actual_tokens`.

    3 fallback (theo thứ tự rẻ → đắt):
    1. Substring 2 chiều (et in at hoặc at in et).
    2. Common prefix ≥ `prefix_min_chars` ký tự VÀ ≥ `prefix_min_ratio` × max(len)
       — bắt plural/singular variant (vd. `'technologies'` vs `'technology'`
       chia sẻ prefix 9 ký tự `'technolog'` = 75% max-len).
    3. SequenceMatcher ratio ≥ `fuzzy_threshold` — bắt typo (vd.
       `'nettherlands'` vs `'netherlands'` ratio ≈ 0.96).
    """
    from difflib import SequenceMatcher
    for at in actual_tokens:
        if et in at or at in et:
            return True
    for at in actual_tokens:
        cp = _common_prefix_len(et, at)
        if cp >= prefix_min_chars and cp / max(len(et), len(at)) >= prefix_min_ratio:
            return True
    best = max(
        (SequenceMatcher(None, et, at).ratio() for at in actual_tokens),
        default=0.0,
    )
    return best >= fuzzy_threshold


def _filter_matches(expected, actual_strs, fuzzy_threshold=0.85):
    """acc6: OR-aware substring filter + tokenized fuzzy fallback.

    52WMB search syntax cho phép nhiều alternatives ngăn cách bởi `|` (vd.
    `DETAIL_BUYER = "trần hiệp thành|tran hiep thanh|tht textiles"`). Server
    coi `|` là OR — bất kỳ alternative nào khớp đều trả về.

    Hai pass:
    1. **Strict substring** — nhanh, xử lý 99% trường hợp.
    2. **Tokenized fuzzy fallback** — xử lý 52WMB data inconsistency giữa
       list endpoint và detail endpoint:
       - Spelling typo (`'Nettherlands'` vs `'netherlands'`)
       - Plural/singular (`'technologies'` vs `'technology'`)
       - Punctuation join/split (`'bio-technology'` vs `'bio technology'`)

       Mỗi token expected (≥3 ký tự) phải tìm được token actual khớp qua
       substring / common-prefix / SequenceMatcher ratio. Tất cả token phải
       khớp → alternative match. Alternatives chỉ có 1 token bỏ qua fuzzy
       (quá mơ hồ — đã có pass 1 lo).
    """
    if not expected:
        return True

    alternatives = [
        ' '.join(a.lower().split())
        for a in expected.split('|')
        if a.strip()
    ]
    if not alternatives:
        return True

    normalized_actuals = [
        ' '.join(str(a or '').lower().split())
        for a in actual_strs
    ]
    if not any(normalized_actuals):
        return True

    # Pass 1: strict substring on FULL string (handles "exact match" case).
    for actual in normalized_actuals:
        if not actual:
            continue
        for alt in alternatives:
            if alt in actual:
                return True

    # Pass 2: token-level fallback (handles list/detail data inconsistency).
    for actual in normalized_actuals:
        if not actual:
            continue
        actual_tokens = _tokenize_for_filter(actual)
        if not actual_tokens:
            continue
        for alt in alternatives:
            alt_tokens = _tokenize_for_filter(alt)
            if len(alt_tokens) < 2:
                continue  # 1-token expected: fuzzy quá rủi ro
            all_matched = True
            for et in alt_tokens:
                if len(et) < 3:
                    # Token rất ngắn: yêu cầu exact substring (tránh noise
                    # từ token 1-2 ký tự kiểu 'bv', 'co').
                    if not any(et in at for at in actual_tokens):
                        all_matched = False
                        break
                    continue
                if not _token_fuzzy_match(et, actual_tokens, fuzzy_threshold):
                    all_matched = False
                    break
            if all_matched:
                log(f"[filter] fuzzy match: '{alt}' ≈ '{actual[:80]}'",
                    "DEBUG")
                return True
    return False

class ScraperProDetail:
    """
    Scraper for Pro 2026 Detail Mode (Market Analysis > Customs Data)
    Uses CSV-based resume detection (no JSON checkpoint needed)
    
    Segment Handling:
    - 10,000 records limit per search
    - 30 rows per page = 333 pages max per segment
    - At page 333, extracts last transaction date as end_date for next segment
    """
    
    # Pro Detail Mode: 30 rows/page, 10k limit = 333.33 pages max
    MAX_PAGES_PER_SEGMENT = 333
    ROWS_PER_PAGE = 30
    
    # Field maps now live in src/parsing/field_mapping.py; class attrs point
    # at the shared dicts so any ScraperProDetail.FIELD_MAPPING access keeps
    # working. update_mapping_from_server mutates these in place.
    FIELD_MAPPING = _PARSING_FIELD_MAPPING
    ALIASES = _PARSING_ALIASES
    
    def __init__(self, driver, wait, csv_file=None):
        self.driver = driver
        self.wait = wait
        self.timer = Timer()
        self.total_scraped = 0
        
        # Resume tracking (detected from CSV)
        self.current_segment = 1
        self.current_page = 1
        self.current_stt = 1
        
        # Segment shift tracking (like Legacy Mode)
        # When reaching page 333, use this date as end_date for next segment
        self.segment_end_date = None
        self.last_known_transaction = None  # Track last scraped tx for boundary detection
        self.first_transaction_of_segment = None # Track FIRST tx of current segment for overlap verification
        
        self.csv_file = csv_file if csv_file else self.generate_output_filename()
        self.excel_file = self.csv_file.replace('.csv', '.xlsx')

        # Enable network capture once globally
        try:
            driver.execute_cdp_cmd('Network.enable', {})
        except:
            pass

        # --- FAST API MODE (hybrid) -----------------------------------------
        self._fast_api_enabled = bool(getattr(config, 'FAST_API_MODE', False))
        self._http_client = None
        self._fast_api_consecutive_failures = 0
        self._rate_meter = RateMeter(window_sec=30, label='detail') if self._fast_api_enabled else None

        # --- API-DIRECT LIST PATH (form-fill bypass) -----------------------
        # When the UI form fill (date picker, country dropdown) breaks
        # repeatedly, we flip to API-only mode for the rest of the current
        # segment. The flag is reset on segment shift so each new segment
        # gets a fresh chance at the UI path.
        self._api_only_until_segment_end = False
        self._api_specs_cache = None  # populated by _fetch_list_via_api

        # Sticky flag: once we observe that the detail endpoint is
        # rejecting cold (un-clicked) bill_ids with state=40, stop
        # wasting 5–7s per page on the httpx pre-fetch and go straight
        # to the UI click path. Doesn't affect _fetch_list_via_api,
        # which uses a different endpoint not gated by warm-up.
        self._fast_api_detail_cold_disabled = False

        # --- Composed components (PR4 refactor) ------------------------------
        self._detail_capture = DetailCapture(driver)
        self._csv_sink = CsvSink(self.csv_file, self.FIELD_MAPPING, self.ALIASES)
        # Expose the sink's dedupe set under the old name for any external access
        self._seen_bill_ids = self._csv_sink.seen_bill_ids

        # --- Dead-letter log: rows/pages we gave up on -----------------------
        # (segment, page, stt) → number of recovery attempts that did NOT
        # unstick this row. After MAX_RECOVERIES_PER_ROW, we skip the row
        # and append a JSONL entry to output/failed_rows.jsonl so the
        # operator can re-scrape it manually later.
        self._recovery_attempts_by_row = {}
        self.MAX_RECOVERIES_PER_ROW = 2
        self._failed_log_path = os.path.join(
            os.path.dirname(self.csv_file) or ".", "failed_rows.jsonl",
        )

    def _log_failed(self, kind, segment, page, stt, reason, **extra):
        """Append a JSONL entry to `output/failed_rows.jsonl` so the
        operator can re-scrape this chunk manually later.

        `kind` is one of: "row" (single stt within a page),
        "page" (whole page aborted).
        """
        try:
            record = {
                "kind": kind,
                "segment": segment,
                "page": page,
                "stt": stt,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "csv_file": os.path.basename(self.csv_file),
                "reason": reason,
            }
            record.update(extra)
            os.makedirs(os.path.dirname(self._failed_log_path) or ".", exist_ok=True)
            with open(self._failed_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            log(f"📝 Logged {kind} failure → {self._failed_log_path}", "WARNING")
        except Exception as e:
            log(f"⚠️ Could not write failed-row log: {e}", "WARNING")

    @staticmethod
    def generate_output_filename():
        """Delegate to src.storage.filename.generate_output_filename."""
        return _storage_generate_filename()
        
    @staticmethod
    def detect_resume_point(csv_file):
        """Delegate to src.storage.checkpoint.detect_resume_point."""
        return _storage_detect_resume(csv_file)
    
    def get_ui_pagination_progress(self):
        """Delegate to src.nav.pagination.get_ui_pagination_progress."""
        return _nav_pagination.get_ui_pagination_progress(self.driver)

    def close_tips_modal(self):
        """Delegate to src.nav.pagination.close_tips_modal."""
        return _nav_pagination.close_tips_modal(self.driver, self.wait)
    
    def prepare_search_results(self, batch_config=None, strict_validation=True):
        """
        Executes the Setup Loop:
        1. Fill Search Form
        2. Click Search
        3. Validate Total Records

        If env INTERACTIVE_SEARCH=1 is set, the auto-fill step is skipped —
        the operator fills the form manually in the open browser and presses
        Enter to resume. Useful when Ant Design's date picker or HS-code
        input is in one of its broken states across Chrome versions.

        Args:
            batch_config: The batch item config
            strict_validation: If True, enforces strict record count matching (for Transactions).
                               If False, only ensures > 0 records (for Analysis).

        Returns:
            bool: True if setup succeeded, False otherwise
        """
        interactive = os.environ.get("INTERACTIVE_SEARCH", "0") == "1"

        setup_attempts = 0
        MAX_SETUP_ATTEMPTS = 3

        while setup_attempts < MAX_SETUP_ATTEMPTS:
            setup_attempts += 1
            setup_success = True

            # Segment Date Check
            if self.current_segment > 1 and not self.segment_end_date:
                log("❌ CRITICAL ERROR: Resuming into Segment > 1 but segment_end_date is None!", "ERROR")
                return False

            if self.segment_end_date:
                log(f"📍 Using segment boundary date for search: {self.segment_end_date}", "INFO")

            # 1. Fill Form — try auto-fill first; fall back to operator if
            #    INTERACTIVE_SEARCH=1 and auto failed.
            auto_filled = navigator_pro.fill_search_form_detail(
                self.driver, self.wait,
                end_date_override=self.segment_end_date,
                batch_config=batch_config,
            )
            if auto_filled:
                log("🔍 Clicking Search button...", "INFO")
                navigator_pro.click_search_button_detail(self.driver, self.wait)
            elif self._is_driver_dead():
                raise RuntimeError(
                    "WebDriver session dead during initial form fill — "
                    "supervisor will restart with fresh Chrome.")
            elif interactive:
                log("⚠️ Auto-fill failed — falling back to interactive prompt", "WARNING")
                self._notify_operator_prompt(
                    "operator_prompt",
                    "Initial search form fill failed (driver alive)")
                print("\n" + "=" * 64)
                print("[!] AUTO-FILL FAILED -- fill the Search form manually in the browser,")
                print("   click Search, wait for the results table, then press Enter here.")
                if self.segment_end_date:
                    print(f"   (Segment boundary date: {self.segment_end_date})")
                print("=" * 64)
                try:
                    input("   [Press Enter once results table has loaded] > ")
                except EOFError:
                    time.sleep(30)
                api_client.wait_for_loading_overlay(self.driver, timeout=30)
                time.sleep(1)
            else:
                log(f"❌ Failed to fill search form (Attempt {setup_attempts})", "WARNING")
                setup_success = False

            # Search has already been clicked above (auto path) or by the
            # operator (interactive fallback). Now validate the total.
            total_records = None

            # 3. Validate total (runs in BOTH auto and interactive branches)
            if setup_success:
                expected_for_validation = batch_config.get('expected') if batch_config else getattr(config, 'DETAIL_EXPECTED_TOTAL', None)
                total_records = navigator_pro.get_total_records_detail(
                    self.driver, self.wait,
                    current_segment=self.current_segment,
                    expected_total=expected_for_validation,
                )

                if total_records is None:
                    log("❌ Total records validation failed", "WARNING")
                    setup_success = False

                if setup_success and total_records is not None:
                    effective_expected = expected_for_validation if expected_for_validation else getattr(config, 'DETAIL_EXPECTED_TOTAL', None)

                    if total_records == 0:
                        log("🛑 SAFETY CHECK: Found 0 records.", "ERROR")
                        setup_success = False

                    elif strict_validation and effective_expected and (
                        total_records > (effective_expected * 2) or
                        total_records < (effective_expected * 0.5)
                    ):
                        log(f"⚠️ SAFETY CHECK FAILED: Mismatch Detected! Expected {effective_expected:,}, Found {total_records:,}", "WARNING")
                        setup_success = False

            if setup_success:
                self.last_total_records = total_records
                return True
            
            # Recovery
            log(f"🔄 Setup failed. Attempting recovery ({setup_attempts}/{MAX_SETUP_ATTEMPTS})...", "PROCESS")
            if self.perform_soft_recovery(batch_config=batch_config):
                continue
            if self.perform_deep_recovery(batch_config=batch_config):
                continue
            
            # If we get here, recovery failed or loops exhausted
        
        log("❌ All recovery attempts failed.", "ERROR")
        return False


    def scrape_detail_transactions(self, batch_config=None):
        """
        Main entry point for transaction pipeline.
        """
        if getattr(config, 'TEST_MODE', False):
            # Override batch_config with TEST_SEARCH_CONFIG
            test_batch = getattr(config, 'TEST_SEARCH_CONFIG', {})
            return self.run_test_scraping_sequence(batch_config=test_batch)
            
        # Resume detection (Always needed for segment info)
        if not hasattr(self, 'current_segment') or not self.current_segment:
             result = self.detect_resume_point(self.csv_file)
             self.current_segment = result[0]
             self.current_page = result[1]
             self.current_stt = result[2]
             self.total_scraped = result[3]
             self.segment_end_date = result[4] if len(result) > 4 else None
             self.last_scraped_date = result[5] if len(result) > 5 else None
        
        self.close_tips_modal()

        return self.run_transaction_pipeline(batch_config)

    def run_transaction_pipeline(self, batch_config=None):
        """
        Dedicated pipeline for Transaction Mode.
        """
        log("🚀 Starting Transaction Pipeline...", "PROCESS")
        
        # Wrap in try block to maintain indentation compatibility with legacy code
        # (Original code body is indented 12-16 spaces)
        try:
            # 1. Prepare Search Results (Strict validation)
            if not self.prepare_search_results(batch_config, strict_validation=True):
                return False
                
            # 2. Navigation to Resume Page
            total_records = self.last_total_records
            
            if self.current_page > 1:
                segment_scraped = (self.current_page - 1) * self.ROWS_PER_PAGE
                log(f"📊 Resume: Estimated {segment_scraped:,} scraped in Segment {self.current_segment}", "INFO")
            else:
                segment_scraped = 0
            
            max_pages = config.DETAIL_MAX_PAGES if config.DETAIL_MAX_PAGES else None
            log(f"📊 Segment {self.current_segment} has {total_records:,} records", "INFO")
            
            if self.current_page > 1:
                log(f"⏭️  Jumping to resume page {self.current_page}...", "INFO")
                if not self.go_to_page(self.current_page):
                    return False
            else:
                log("🔄 Ensuring pagination is set to Page 1...", "INFO")
                navigator_pro.reset_pagination_to_page_one(self.driver, self.wait)


            # 3. Scraping Loop
            log("🔄 Starting Transaction Scraping Loop...", "INFO")
            first_page_of_session = True
            session_scraped = 0
            
            while True:

                log(f"\n{'='*60}", "INFO")
                log(f"📄 Page {self.current_page}/{self.MAX_PAGES_PER_SEGMENT} (Segment {self.current_segment})", "PROCESS")
                log(f"{'='*60}", "INFO")
                
                # Use current_stt for the first page, then reset to 1
                start_from_stt = self.current_stt if first_page_of_session else 1
                
                page_transactions = self.scrape_page(self.current_page, self.current_segment, start_stt=start_from_stt)
                
                # Capture FIRST transaction of the segment (if on page 1, stt 1)
                if self.current_page == 1 and start_from_stt == 1 and page_transactions:
                     self.first_transaction_of_segment = page_transactions[0]
                     log(f"📍 Captured reference tx for Segment {self.current_segment}: {self._get_transaction_id(self.first_transaction_of_segment)}", "DEBUG")
                
                # ============================================================
                # 0 ROWS BRANCHING: distinguish "session expired" from
                # "segment naturally ended" (genuine end-of-data on a
                # short segment, e.g. Jan 1-13 with only 41 pages).
                #
                # Heuristic for natural-end:
                #   - We're not on the first page of the session
                #     (current_page > 1, or > start_page on resume)
                #   - We've already scraped >= 1 page worth of rows in
                #     this run AND in this segment
                #   - total_records is known and segment_scraped is
                #     "close enough" (within 5% or 1 page) — the server
                #     reports total_records of THIS query, so once we've
                #     scraped that count, next page IS empty.
                # If natural-end → break out of the page loop, parent
                # logic will trigger segment shift to next segment.
                # Otherwise → real recovery.
                # ============================================================
                is_api_bug_boundary = (not page_transactions and not first_page_of_session and self.current_page >= self.MAX_PAGES_PER_SEGMENT)

                # Natural end-of-segment detection (works for short segments)
                NEAR_END_TOLERANCE = max(
                    self.ROWS_PER_PAGE,
                    int((total_records or 0) * 0.05),
                )
                natural_end = (
                    not page_transactions
                    and not first_page_of_session
                    and total_records
                    and segment_scraped > 0
                    and segment_scraped >= total_records - NEAR_END_TOLERANCE
                )
                if natural_end:
                    log(f"🏁 Segment {self.current_segment} naturally ended at "
                        f"page {self.current_page}: scraped {segment_scraped:,} "
                        f"≥ {total_records:,} − tolerance {NEAR_END_TOLERANCE}. "
                        f"Triggering segment shift.", "SUCCESS")
                    self._auto_upload_to_drive(
                        f"after segment {self.current_segment} (natural end at page {self.current_page})")
                    # Force segment-shift logic by jumping to MAX_PAGES_PER_SEGMENT
                    # so the existing shift-trigger block at the bottom of this
                    # loop fires. Cleaner than copy-pasting shift logic here.
                    self.current_page = self.MAX_PAGES_PER_SEGMENT
                    page_transactions = []  # ensure shift block sees no data
                    is_api_bug_boundary = True  # so downstream code does shift

                if not page_transactions and not first_page_of_session and not is_api_bug_boundary:
                    log("⚠️  0 rows detected on non-first page — could be "
                        "session expired OR true end-of-segment for short "
                        "queries. Attempting SOFT recovery first.", "WARNING")
                    log("🔄 Attempting SOFT recovery (refresh + refill form)...", "PROCESS")
                    
                    # Attempt 1: Soft recovery
                    recovery_success = self.perform_soft_recovery(batch_config=batch_config)
                    
                    if recovery_success:
                        # Retry scrape_page
                        log(f"🔄 Retrying page {self.current_page} after soft recovery...", "INFO")
                        page_transactions = self.scrape_page(self.current_page, self.current_segment, start_stt=1)
                        
                        if page_transactions:
                            log(f"✅ Recovery successful! Got {len(page_transactions)} rows", "SUCCESS")
                        else:
                            # Still 0 rows after soft recovery
                            log("⚠️  Still 0 rows after soft recovery", "WARNING")
                            log("🔄 Escalating to DEEP recovery (relogin)...", "WARNING")
                            
                            # Attempt 2: Deep recovery
                            if self.perform_deep_recovery(batch_config=batch_config):
                                log(f"🔄 Retrying page {self.current_page} after deep recovery...", "INFO")
                                page_transactions = self.scrape_page(self.current_page, self.current_segment, start_stt=1)

                                if page_transactions:
                                    log(f"✅ Deep recovery successful! Got {len(page_transactions)} rows", "SUCCESS")
                                else:
                                    # Page N empty after SOFT+DEEP recovery. Before raising
                                    # (which loops forever if page N is genuinely empty —
                                    # supervisor restart → checkpoint resumes at N → same
                                    # 0-row → same recovery → same raise), probe up to 3
                                    # subsequent pages:
                                    #   - Any has data → page N was a sparse-gap / transient
                                    #     empty (rare but real). Skip the gap, jump to the
                                    #     first page with data, continue normally.
                                    #   - All 3 also empty → very likely real end-of-segment.
                                    #     Trigger segment shift instead of raising.
                                    SKIP_PROBE_LIMIT = 3
                                    log(f"⚠️ Page {self.current_page} still empty after "
                                        f"both SOFT+DEEP — probing up to {SKIP_PROBE_LIMIT} "
                                        f"subsequent pages to distinguish 'sparse gap' from "
                                        f"'end-of-segment'.", "WARNING")
                                    skipped_empty_pages = [self.current_page]
                                    found_data_on_probe = False
                                    for probe_offset in range(1, SKIP_PROBE_LIMIT + 1):
                                        probe_page = self.current_page + probe_offset
                                        log(f"🔍 Probing page {probe_page}...", "INFO")
                                        try:
                                            probe_transactions = self.scrape_page(
                                                probe_page, self.current_segment,
                                                start_stt=1)
                                        except Exception as probe_err:
                                            log(f"⚠️ Probe of page {probe_page} threw: "
                                                f"{probe_err}", "WARNING")
                                            probe_transactions = []
                                        if probe_transactions:
                                            log(f"✅ Page {probe_page}: "
                                                f"{len(probe_transactions)} rows — "
                                                f"pages {skipped_empty_pages} were a "
                                                f"sparse gap. Skipping them.", "SUCCESS")
                                            self.current_page = probe_page
                                            page_transactions = probe_transactions
                                            found_data_on_probe = True
                                            break
                                        skipped_empty_pages.append(probe_page)
                                    if not found_data_on_probe:
                                        log(f"🏁 Pages {skipped_empty_pages} all empty "
                                            f"after recovery — treating as end-of-segment "
                                            f"and forcing segment shift instead of "
                                            f"crashing.", "WARNING")
                                        self._auto_upload_to_drive(
                                            f"after segment {self.current_segment} "
                                            f"(forced shift at page {self.current_page} "
                                            f"after {SKIP_PROBE_LIMIT} consecutive empty "
                                            f"probes)")
                                        self.current_page = self.MAX_PAGES_PER_SEGMENT
                                        page_transactions = []
                                        is_api_bug_boundary = True
                            else:
                                log("❌ Deep recovery failed — raising to force supervisor "
                                    "restart (CSV checkpoint will resume).", "ERROR")
                                raise RuntimeError(
                                    f"DEEP recovery failed at segment "
                                    f"{self.current_segment} page {self.current_page}")
                    else:
                        # Soft recovery failed before getting to deep
                        log("❌ Soft recovery failed — raising to force supervisor restart.",
                            "ERROR")
                        raise RuntimeError(
                            f"SOFT recovery failed at segment "
                            f"{self.current_segment} page {self.current_page}")
                
                if page_transactions or is_api_bug_boundary:
                    if is_api_bug_boundary:
                        log(f"⚠️ 0 rows detected exactly at segment boundary (page {self.current_page}). Assuming API bug, forcing segment shift...", "WARNING")
                    
                    page_count = len(page_transactions)
                    self.total_scraped += page_count
                    segment_scraped += page_count  # Track per-segment progress
                    session_scraped += page_count  # Track this session only (for ETA)
                    
                    log(f"✅ Page {self.current_page}: {page_count} transactions", "SUCCESS")
                    log(f"📊 Segment {self.current_segment}: {segment_scraped:,} / {total_records:,} | Global: {self.total_scraped:,}", "INFO")
                    
                    # ============================================================
                    # ETA CALCULATION (real-time monitoring)
                    # Uses session_scraped for accurate speed calculation
                    # Uses batch_config expected for multi mode
                    # ============================================================
                    # ============================================================
                    # UNIFIED PROGRESS TRACKING (Single & Multi Mode)
                    # ============================================================
                    try:
                        elapsed_seconds = (datetime.now() - self.timer.start_time).total_seconds()
                        
                        if elapsed_seconds > 10 and session_scraped > 0:  # Only calc after 10s warmup
                            # 1. Calculate standardized speed (Records/Hour) based on CURRENT SESSION
                            records_per_second = session_scraped / elapsed_seconds
                            records_per_hour = records_per_second * 3600
                            
                            # 2. Determine Scope (Grand Total Expected vs Scraped)
                            grand_total_expected = 0
                            grand_total_scraped_so_far = 0
                            
                            batch_items = []
                            if getattr(config, 'DETAIL_SUBMODE', 'single') == 'multi':
                                job_type = getattr(config, 'PRO_JOB_TYPE', 'transactions')
                                if job_type == 'transactions':
                                    batch_items = getattr(config, 'TRANSACTIONS_BATCH', [])
                                else:
                                    batch_items = getattr(config, 'ANALYSIS_BATCH', [])

                            if batch_config and batch_items:
                                # --- MULTI MODE ---
                                # Grand Total = Sum of all expected counts in batch
                                grand_total_expected = sum(item.get('expected', 0) for item in batch_items)
                                
                                # Scraped So Far = (Sum of expected for COMPLETED batches) + (Current batch progress)
                                current_batch_name = batch_config.get('name')
                                found_current = False
                                
                                for item in batch_items:
                                    if item.get('name') == current_batch_name:
                                        found_current = True
                                        # Add current actual progress (self.total_scraped)
                                        # Note: self.total_scraped tracks total progress for *current* batch item across all segments
                                        grand_total_scraped_so_far += self.total_scraped
                                        break # Stop at current
                                    else:
                                        # Assume previous batches completed fully (add their expected count)
                                        grand_total_scraped_so_far += item.get('expected', 0)
                                        
                            else:
                                # --- SINGLE MODE ---
                                grand_total_expected = getattr(config, 'DETAIL_EXPECTED_TOTAL', 0)
                                grand_total_scraped_so_far = self.total_scraped
                                
                            # 3. Calculate Metrics
                            remaining = max(0, grand_total_expected - grand_total_scraped_so_far)
                            progress_pct = (grand_total_scraped_so_far / grand_total_expected * 100) if grand_total_expected > 0 else 0.0
                            
                            eta_str = "N/A"
                            completion_time_str = ""
                            
                            if records_per_second > 0 and remaining > 0:
                                eta_seconds = remaining / records_per_second
                                eta_hours = int(eta_seconds // 3600)
                                eta_mins = int((eta_seconds % 3600) // 60)
                                eta_str = f"{eta_hours}h {eta_mins}m"
                                
                                completion_dt = datetime.now() + timedelta(seconds=eta_seconds)
                                completion_time_str = f"(~{completion_dt.strftime('%H:%M')})"
                            
                            # 4. Display Unified Log
                            mode_label = f"Batch [{batch_config.get('name')}]" if batch_config else "Progress"
                            
                            log(f"📈 {mode_label}: {progress_pct:.1f}% | Remaining: {remaining:,} | Speed: {records_per_hour:,.0f}/hr | ETA: {eta_str} {completion_time_str}", "INFO")

                            # 5. UI Pagination Progress (Auxiliary)
                            try:
                                ui_current, ui_last, ui_pct = self.get_ui_pagination_progress()
                                if ui_current and ui_last:
                                    ui_text = f"Page {ui_current:,}/{ui_last:,} ({ui_pct:.1f}%)"
                                    # Optional: Estimate UI remaining
                                    ui_rem_pages = ui_last - ui_current
                                    ui_rem_records = ui_rem_pages * 30
                                    
                                    # Calculate UI-based ETA (often more accurate effectively)
                                    ui_eta_str = ""
                                    if records_per_second > 0 and ui_rem_records > 0:
                                        ui_sec = ui_rem_records / records_per_second
                                        ui_h = int(ui_sec // 3600)
                                        ui_m = int((ui_sec % 3600) // 60)
                                        ui_eta_str = f" | ETA: {ui_h}h {ui_m}m"

                                    log(f"🖥️  UI Progress: {ui_text} | ~{ui_rem_records:,} left in segment{ui_eta_str}", "INFO")
                            except:
                                pass

                    except Exception as e:
                        # Don't let progress calculation crash the scraper
                        # log(f"⚠️ Progress calc error: {e}", "DEBUG")
                        pass

                    
                    # Track last transaction for segment boundary detection
                    if page_transactions:
                        self.last_known_transaction = page_transactions[-1]
                    
                    # Update last scraped date to the last transaction on the page
                    last_tx_date = self._extract_transaction_date(self.last_known_transaction)
                    if last_tx_date:
                        self.last_scraped_date = last_tx_date
                    
                    # Save to CSV after whole page is done
                    self.append_to_csv(page_transactions)
                    self._write_status(
                        self.current_page,
                        self.total_scraped,
                        self.current_segment,
                        None,
                        self.segment_end_date,
                    )

                    # ============================================================
                    # SEGMENT SHIFT CHECK: At page 333, trigger segment shift
                    # ============================================================
                    if self.current_page >= self.MAX_PAGES_PER_SEGMENT:
                        log(f"🎯 10K LIMIT HIT at page {self.current_page}. Initiating segment shift...", "PROCESS")
                        
                        # Extract boundary date from last transaction
                        boundary_date = self._extract_transaction_date(self.last_known_transaction)
                        
                        # Fallback for when script resumed exactly at segment boundary and got empty list
                        if not boundary_date and hasattr(self, 'last_scraped_date') and self.last_scraped_date:
                            boundary_date = self.last_scraped_date
                            log(f"📍 Used fallback boundary_date from last_scraped_date: {boundary_date}", "DEBUG")
                            
                        # Double fallback to segment_end_date (inherited from CSV during resume)
                        if not boundary_date and self.segment_end_date:
                            boundary_date = self.segment_end_date
                            log(f"📍 Used fallback boundary_date from segment_end_date: {boundary_date}", "DEBUG")
                        
                        if boundary_date:
                            log(f"📍 Segment {self.current_segment} complete. Got {self.MAX_PAGES_PER_SEGMENT * self.ROWS_PER_PAGE} records.", "SUCCESS")
                            log(f"📍 New segment end date: {boundary_date}", "INFO")

                            # ===== Auto-upload after segment complete =====
                            # User wants the CSV pushed to Drive at every
                            # segment boundary, not just on final exit.
                            # Sleep ~1s to let the CSV writer flush, then
                            # upload (best-effort; never raises).
                            self._auto_upload_to_drive(
                                f"after segment {self.current_segment}")

                            # Update state for new segment
                            self.segment_end_date = boundary_date
                            self.current_segment += 1
                            self.current_page = 1
                            self.current_stt = 1  # Start from row 1 in new segment
                            
                            # Store previous segment's first tx for verification
                            prev_segment_first_tx = self.first_transaction_of_segment
                            self.first_transaction_of_segment = None # Reset for new segment
                            
                            log(f"🚀 Starting Segment {self.current_segment} (data up to {boundary_date})...", "PROCESS")
                            
                            # ============================================================
                            # SEGMENT SHIFT: Use "All clear" button + refill (faster than refresh)
                            # ============================================================
                            segment_shift_success = False
                            
                            try:
                                log("🔄 Clearing search form for new segment...", "INFO")

                                interactive_shift = os.environ.get("INTERACTIVE_SEARCH") == "1"

                                # Reset API-only flag at segment boundary —
                                # give the UI a fresh chance for the new
                                # segment (sometimes the next segment's
                                # state happens to work).
                                self._api_only_until_segment_end = False

                                # API-FIRST shift: try API list path with
                                # the new boundary_date BEFORE the UI
                                # form-fill dance. If the API works,
                                # next segment runs in API mode; no UI
                                # date picker pain.
                                auto_shift_ok = False
                                # Reset state=40 sticky flag at segment
                                # boundary — new segment might have
                                # different bills that ARE warm.
                                self._fast_api_detail_cold_disabled = False
                                if (self._fast_api_enabled
                                        and self._ensure_http_client()):
                                    log("📡 Segment shift: trying API-direct "
                                        "list path FIRST...", "PROCESS")
                                    try:
                                        self._refresh_http_cookies()
                                        probe = self._fetch_list_via_api(
                                            end_date=boundary_date,
                                            page_num=1)
                                        if probe is not None:
                                            log("✅ API list path works — "
                                                "skipping UI segment-shift "
                                                "form fill", "SUCCESS")
                                            self._api_only_until_segment_end = True
                                            auto_shift_ok = True
                                    except Exception as e:
                                        log(f"⚠️ API probe raised "
                                            f"(falling back to UI): {e}",
                                            "WARNING")

                                # Reduced UI retries — when API didn't work
                                # we just try UI 2× max, not 4×.
                                SHIFT_RETRY_WAITS = [10, 60]
                                SHIFT_MAX_ATTEMPTS = len(SHIFT_RETRY_WAITS) + 1
                                if auto_shift_ok:
                                    SHIFT_MAX_ATTEMPTS = 0  # skip UI loop
                                for shift_attempt in range(1, SHIFT_MAX_ATTEMPTS + 1):
                                    log(f"📝 Segment shift fill attempt "
                                        f"{shift_attempt}/{SHIFT_MAX_ATTEMPTS}",
                                        "PROCESS")
                                    if navigator_pro.click_all_clear(
                                            self.driver, self.wait):
                                        time.sleep(2)
                                        log(f"📝 Refilling form with end date: "
                                            f"{boundary_date}", "INFO")
                                        if navigator_pro.fill_search_form_detail(
                                            self.driver, self.wait,
                                            end_date_override=boundary_date,
                                            batch_config=batch_config,
                                        ):
                                            navigator_pro.click_search_button_detail(
                                                self.driver, self.wait)
                                            api_client.wait_for_loading_overlay(
                                                self.driver, timeout=5)
                                            auto_shift_ok = True
                                            log("✅ Segment shift complete "
                                                "(Clear + Refill)", "SUCCESS")
                                            break

                                    if shift_attempt < SHIFT_MAX_ATTEMPTS:
                                        wait_s = SHIFT_RETRY_WAITS[shift_attempt - 1]
                                        log(f"⚠️ Shift fill attempt "
                                            f"{shift_attempt} failed — "
                                            f"network probe + refresh + "
                                            f"retry in {wait_s}s",
                                            "WARNING")
                                        self._probe_network_and_log()
                                        try:
                                            self.driver.refresh()
                                        except Exception:
                                            pass
                                        time.sleep(wait_s)
                                        try:
                                            self.close_tips_modal()
                                        except Exception:
                                            pass
                                        try:
                                            api_client.wait_for_loading_overlay(
                                                self.driver, timeout=15)
                                        except Exception:
                                            pass

                                if auto_shift_ok:
                                    segment_shift_success = True
                                    self._api_only_until_segment_end = False

                                    # CRITICAL FIX: Reset Pagination to Page 1
                                    log("🔄 Resetting pagination to Page 1...", "INFO")
                                    if navigator_pro.reset_pagination_to_page_one(self.driver, self.wait):
                                        time.sleep(2)
                                        api_client.wait_for_loading_overlay(self.driver)
                                        api_client.handle_popup(self.driver, self.wait)
                                        log("✅ Page 1 loaded and ready for scraping", "INFO")
                                    else:
                                        log("⚠️ Could not reset pagination (maybe only 1 page?)", "WARNING")

                                elif self._fast_api_enabled and self._ensure_http_client():
                                    # UI segment shift broken — use API path
                                    # for the rest of this new segment.
                                    log(f"⚠️ UI segment shift failed "
                                        f"{SHIFT_MAX_ATTEMPTS}× — switching "
                                        f"to API-direct list path for "
                                        f"segment {self.current_segment + 1}",
                                        "WARNING")
                                    self._api_only_until_segment_end = True
                                    self._refresh_http_cookies()
                                    segment_shift_success = True
                                    # No UI pagination reset needed —
                                    # _fetch_list_via_api uses page_num
                                    # parameter directly.

                                elif self._is_driver_dead():
                                    raise RuntimeError(
                                        "WebDriver session dead during "
                                        "segment shift — supervisor will "
                                        "restart with fresh Chrome.")
                                elif interactive_shift:
                                    log(f"⚠️ Auto segment shift failed after "
                                        f"{SHIFT_MAX_ATTEMPTS} attempts "
                                        f"(API path unavailable) — "
                                        f"interactive prompt", "WARNING")
                                    self._notify_operator_prompt(
                                        "operator_prompt",
                                        f"Segment shift: failed "
                                        f"{SHIFT_MAX_ATTEMPTS}× (driver alive)")
                                    print("\n" + "=" * 66)
                                    print(f"👉 SEGMENT SHIFT {self.current_segment} → {self.current_segment + 1}")
                                    print(f"   End date mới: {boundary_date}")
                                    print(f"   In browser: click 'All clear', then re-fill:")
                                    print(f"     Country={config.DETAIL_COUNTRY}, Type={config.DETAIL_DATA_TYPE}")
                                    print(f"     Start={config.DETAIL_START_DATE}, End={boundary_date}")
                                    print(f"     HS={config.DETAIL_HS_CODE}")
                                    print(f"   Bấm Search, đợi bảng kết quả, rồi Enter ở đây.")
                                    print("=" * 66)
                                    try:
                                        input("   [Press Enter once new segment results have loaded] > ")
                                    except EOFError:
                                        time.sleep(30)
                                    api_client.wait_for_loading_overlay(self.driver, timeout=30)
                                    time.sleep(1)
                                    segment_shift_success = True
                                    log("✅ Segment shift complete (interactive)", "SUCCESS")
                                    log("🔄 Resetting pagination to Page 1...", "INFO")
                                    if navigator_pro.reset_pagination_to_page_one(self.driver, self.wait):
                                        time.sleep(2)
                                        api_client.wait_for_loading_overlay(self.driver)
                                        api_client.handle_popup(self.driver, self.wait)
                                        log("✅ Page 1 loaded and ready for scraping", "INFO")
                                    else:
                                        log("⚠️ Could not reset pagination (maybe only 1 page?)", "WARNING")

                                else:
                                    log("❌ Auto segment shift failed and no INTERACTIVE_SEARCH "
                                        "fallback available", "ERROR")
                            except Exception as e:
                                log(f"⚠️ Clear+Refill failed: {e}", "WARNING")
                            
                            # ============================================================
                            # VERIFY SEGMENT SHIFT (Anti-Loop Check)
                            # ============================================================
                            if segment_shift_success and prev_segment_first_tx:
                                log("🔎 Verifying new segment content...", "PROCESS")
                                try:
                                    # Scrape just the first row to check
                                    check_txs = self.scrape_page(1, self.current_segment, start_stt=1)
                                    if check_txs:
                                        new_first_tx = check_txs[0]
                                        # Compare IDs
                                        prev_id = self._get_transaction_id(prev_segment_first_tx)
                                        new_id = self._get_transaction_id(new_first_tx)
                                        
                                        if prev_id and new_id and prev_id == new_id:
                                            log(f"\n{'!'*60}", "ERROR")
                                            log(f"🛑 SEGMENT SHIFT FAILED: DATA LOOP DETECTED", "ERROR")
                                            log(f"   Record ID: {prev_id}", "ERROR")
                                            log(f"   Action: Aborting.", "ERROR")
                                            log(f"{'!'*60}\n", "ERROR")
                                            return False
                                        
                                        # DATE INTEGRITY CHECK
                                        # Ensure we aren't seeing data newer than our requested boundary
                                        tx_date_str = self._extract_transaction_date(new_first_tx)
                                        if tx_date_str and self.segment_end_date:
                                            # Compare dates (ISO format YYYY-MM-DD compares correctly as string)
                                            if tx_date_str > self.segment_end_date:
                                                log(f"\n{'!'*60}", "ERROR")
                                                log(f"🛑 SEGMENT DATE BOUNDARY VIOLATION", "ERROR")
                                                log(f"   Expected End Date: {self.segment_end_date}", "ERROR")
                                                log(f"   Actual Record Date: {tx_date_str} (NEWER!)", "ERROR")
                                                log(f"   Reason: Date filter NOT applied/reset correctly.", "ERROR")
                                                log(f"   Action: Triggering RECOVERY to re-apply filter.", "ERROR")
                                                log(f"{'!'*60}\n", "ERROR")
                                                segment_shift_success = False # Force recovery path below
                                            else:
                                                log("✅ Segment verification passed: Content is different and within Key Date boundary.", "SUCCESS")
                                        else:
                                            log("✅ Segment verification passed: Content is different.", "SUCCESS")
                                    else:
                                        log("⚠️ Could not scrape page 1 for verification (empty?)", "WARNING")
                                except Exception as ex:
                                    log(f"⚠️ Verification logic error: {ex}", "WARNING")
                            
                            # Fallback to soft recovery if clear+fill failed
                            if not segment_shift_success:
                                log("⚠️ Clear+Refill failed. Trying soft recovery...", "WARNING")
                                if not self.perform_soft_recovery(batch_config=batch_config):
                                    log("❌ Segment shift failed completely", "ERROR")
                                    break
                                # After soft recovery, also reset page
                                self.current_page = 1
                            
                            # Reset segment tracking for new segment
                            segment_scraped = 0
                            
                            # Get new total_records for this segment
                            expected_for_validation = batch_config.get('expected') if batch_config else getattr(config, 'DETAIL_EXPECTED_TOTAL', None)
                            new_total = navigator_pro.get_total_records_detail(
                                self.driver, self.wait, 
                                current_segment=self.current_segment,
                                expected_total=expected_for_validation
                            )
                            if new_total:
                                total_records = new_total
                                log(f"📊 Segment {self.current_segment} has {total_records:,} records", "INFO")
                            
                            first_page_of_session = True  # Reset for new segment
                            continue
                        else:
                            log(f"⚠️ Could not extract boundary date. Cannot shift segment.", "WARNING")
                            # Continue without shift - may hit API limit
                
                first_page_of_session = False
                
                # Check if reached segment's total records
                if total_records and segment_scraped >= total_records:
                    log(f"🏁 Segment {self.current_segment} complete: {segment_scraped:,} / {total_records:,} records.", "SUCCESS")
                    log(f"📊 Global total: {self.total_scraped:,}", "INFO")
                    break
                    
                if max_pages and self.current_page >= max_pages:
                    log(f"🏁 Reached max pages ({max_pages}). Finished.", "SUCCESS")
                    break
                
                # Try to go to next page
                if not self.go_to_next_page():
                    # Distinguish "natural end of segment" from "real failure":
                    #   - Natural end: pagination's Next button is gone because
                    #     there really are no more pages. segment_scraped is
                    #     near total_records (within one page tolerance).
                    #     Don't trigger recovery — server reports total_records
                    #     can be ±a-few-rows off, and rows may be deduped on
                    #     resume. Trust the missing Next button.
                    #   - Real failure: we're nowhere close to total_records;
                    #     pagination probably broke.
                    NEAR_END_TOLERANCE = max(self.ROWS_PER_PAGE,
                                              int((total_records or 0) * 0.05))
                    near_end = (
                        total_records
                        and segment_scraped >= total_records - NEAR_END_TOLERANCE
                    )
                    if total_records and segment_scraped < total_records and not near_end:
                        log(f"⚠️ Next button not found but only "
                            f"{segment_scraped:,}/{total_records:,} scraped "
                            f"(>{NEAR_END_TOLERANCE} rows missing). Trying "
                            f"soft recovery...", "WARNING")

                        # Try SOFT recovery first
                        if self.perform_soft_recovery(batch_config=batch_config):
                            # After recovery, try again
                            if self.go_to_next_page():
                                self.current_page += 1
                                time.sleep(2)
                                continue

                        # Soft recovery failed - escalate to DEEP recovery
                        log("⚠️ Soft recovery failed. Escalating to DEEP recovery...", "WARNING")
                        if self.perform_deep_recovery(batch_config=batch_config):
                            # After deep recovery, try again
                            if self.go_to_next_page():
                                self.current_page += 1
                                time.sleep(2)
                                continue

                        # Both recoveries failed
                        log("❌ Both SOFT and DEEP recovery failed. Ending segment.", "ERROR")
                    elif near_end:
                        log(f"🏁 Segment {self.current_segment} naturally "
                            f"complete: {segment_scraped:,}/{total_records:,} "
                            f"(within tolerance, Next button gone).", "SUCCESS")
                        self._auto_upload_to_drive(
                            f"after segment {self.current_segment} (natural end)")
                    else:
                        log("🏁 No more next button - end of data.", "INFO")
                        self._auto_upload_to_drive("at end of data")
                    break
                
                self.current_page += 1
                time.sleep(2)
            
            # Summary
            elapsed_seconds = (datetime.now() - self.timer.start_time).total_seconds()
            elapsed_str = f"{int(elapsed_seconds//3600)}h {int((elapsed_seconds%3600)//60)}m {int(elapsed_seconds%60)}s"
            
            log(f"\n{'='*60}", "SUCCESS")
            log(f"✅ Detail Mode complete!", "SUCCESS")
            log(f"📊 Total: {self.total_scraped:,}", "SUCCESS")
            log(f"⏱️  Time: {elapsed_str}", "SUCCESS")
            log(f"{'='*60}\n", "SUCCESS")
            
            # Transaction pipeline complete
            self.convert_to_excel()
            return True
        except KeyboardInterrupt:
            log("\n🛑 Scraping interrupted by user. Saving progress...", "WARNING")
            self.convert_to_excel()
            # Re-raise to let outer loop handle graceful exit (don't retry)
            raise
        except Exception as e:
            log(f"❌ Scraping failed: {e}", "ERROR")
            # Ensure we still try to save what we have
            try:
                self.convert_to_excel()
            except:
                pass
            import traceback
            traceback.print_exc()
            return False
    
    def _is_driver_dead(self):
        """Quick liveness check: try to read driver.current_url. If it
        raises (invalid session id, no such window, connection refused),
        the WebDriver session is dead and recovery via 'fill form again'
        is futile — we need to raise out so supervisor restarts python
        with a fresh driver. Returns True iff driver looks dead."""
        try:
            _ = self.driver.current_url
            return False
        except Exception as e:
            msg = str(e).lower()
            for marker in ("invalid session id", "no such window",
                           "session deleted", "chrome not reachable",
                           "connection refused", "session not created"):
                if marker in msg:
                    log(f"💀 driver session dead ({marker}). Will raise to "
                        f"force supervisor restart.", "ERROR")
                    return True
            return False

    def _notify_operator_prompt(self, kind, reason):
        """Send an email alert right before showing the
        'fill form manually' prompt — operator-needed events
        otherwise pass under the hang-watcher's radar (log keeps
        getting updated by the prompt line). This is the actual
        'crawl is stuck waiting for human' moment."""
        try:
            import sys, os
            scripts_dir = os.path.join(
                os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))),
                "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            import notify  # type: ignore
            scraper_dir = os.path.dirname(scripts_dir)
            log_files = sorted(
                [f for f in os.listdir(os.path.join(scraper_dir, "logs"))
                 if f.startswith("crawl_") and f.endswith(".log")],
                reverse=True)
            log_path = (os.path.join(scraper_dir, "logs", log_files[0])
                        if log_files else "")
            subject, body = notify.build_failure_email(
                scraper_dir, log_path, kind, reason)
            body += (f"\n\n═══ Operator action ═══\n"
                     f"Scraper is waiting at the {kind} prompt for you to "
                     f"fill the search form manually in the open Chrome "
                     f"window, then press Enter in the terminal. To "
                     f"automatic-restart instead, Ctrl+C the supervisor and "
                     f"re-launch — the driver may have died (invalid "
                     f"session id) and a fresh Python process fixes it.\n")
            notify.send(subject, body, attachment_path=log_path)
        except Exception as e:
            log(f"⚠️ operator-prompt notify failed (non-fatal): {e}",
                "WARNING")

    def _probe_network_and_log(self):
        """Quick TCP probe to pro.52wmb.com:443 — surfaces whether a
        recovery failure is "site/network down" vs "form fill UI bug".
        Best-effort, never raises. Logs the outcome so the operator
        (or email alert) can tell from the log what was happening."""
        import socket
        try:
            t0 = time.time()
            with socket.create_connection(
                    ("pro.52wmb.com", 443), timeout=5) as s:
                pass
            ms = int((time.time() - t0) * 1000)
            log(f"🌐 network probe: pro.52wmb.com:443 reachable ({ms}ms)",
                "DEBUG")
            return True
        except Exception as e:
            log(f"🌐 network probe FAILED: pro.52wmb.com:443 unreachable: "
                f"{e}", "WARNING")
            return False

    def _auto_upload_to_drive(self, reason=""):
        """Spawn cumulative + per-segment Drive upload in a daemon thread
        so the scrape loop NEVER blocks on upload.

        Why background: 2026-05-05 incident — Drive resumable upload of a
        50MB xlsx hung for >1h, blocking the scraper thread because the
        upload was synchronous. User had to Ctrl+C and restart, losing
        ~1h of potential scrape time. Now upload is fire-and-forget;
        worst case the thread hangs forever (daemon, dies with process)
        and the scraper keeps moving.

        Concurrency: only one upload thread at a time. If the previous
        upload is still alive when this fires (e.g., last segment's
        upload still uploading and segment N+1 just finished), this call
        is skipped — the next segment boundary will trigger a fresh
        upload that includes the missed segment's data (cumulative is a
        full snapshot anyway).

        Best-effort — any failure inside the thread is logged but never
        propagated.
        """
        prev = getattr(self, '_upload_thread', None)
        if prev is not None and prev.is_alive():
            log(f"⏭️ Previous Drive upload still running — skipping this "
                f"trigger ({reason}); next segment will re-trigger",
                "WARNING")
            return

        csv_path = self.csv_file
        seg_num = self.current_segment

        def _bg_upload():
            try:
                time.sleep(1)  # let CSV writer flush
                log(f"📤 [bg] Auto-uploading to Drive ({reason})...",
                    "PROCESS")
                from pathlib import Path as _P
                import sys as _sys
                scripts_dir = _P(csv_path).resolve().parent.parent / "scripts"
                if str(scripts_dir) not in _sys.path:
                    _sys.path.insert(0, str(scripts_dir))
                try:
                    import upload_to_drive as _u
                    _u.upload_latest(csv_path=csv_path)
                except Exception as e:
                    log(f"⚠️ [bg] Drive cumulative upload skipped: {e}",
                        "WARNING")
                try:
                    self._upload_segment_slice(seg_num)
                except Exception as e:
                    log(f"⚠️ [bg] Segment slice failed: {e}", "WARNING")
                log(f"✅ [bg] Drive upload finished ({reason})", "SUCCESS")
            except Exception as e:
                log(f"⚠️ [bg] Drive upload outer error: {e}", "WARNING")

        t = threading.Thread(
            target=_bg_upload, daemon=True, name="drive-upload")
        t.start()
        self._upload_thread = t
        log(f"📤 Drive upload spawned in background ({reason}) — "
            f"scraper continues without waiting", "INFO")

    def _upload_segment_slice(self, segment_num):
        """Slice the cumulative CSV by `segment == N`, write an
        immutable per-segment file to output/segments/, and upload it
        to Drive under hs<code>/segments/.

        Filename: <cumulative_stem>_seg<N>_<dateMin>_to_<dateMax>.csv
        (date range derived from this segment's actual rows, not config
        — handles cases where segment ends mid-day).
        """
        from pathlib import Path as _P
        import sys as _sys
        try:
            import pandas as _pd
        except ImportError:
            log("⚠️ pandas not available — skipping segment slice", "WARNING")
            return

        cum_csv = _P(self.csv_file)
        if not cum_csv.is_file():
            log(f"⚠️ Slice skipped: cumulative CSV missing: {cum_csv}",
                "WARNING")
            return

        try:
            df = _pd.read_csv(cum_csv, low_memory=False, dtype=str)
        except Exception as e:
            log(f"⚠️ Slice skipped: cannot read cumulative CSV: {e}",
                "WARNING")
            return

        if "segment" not in df.columns:
            log("⚠️ Slice skipped: 'segment' column missing in CSV",
                "WARNING")
            return

        seg_mask = df["segment"].astype(str).str.strip() == str(segment_num)
        seg_df = df[seg_mask]
        if seg_df.empty:
            log(f"⚠️ Slice skipped: segment {segment_num} has 0 rows in CSV",
                "WARNING")
            return

        # Date range from this segment's rows (not config) — segments may
        # end mid-day if the previous segment's last row dictated the
        # boundary, so config dates won't always match actual coverage.
        date_col = "Transaction Date"
        if date_col not in seg_df.columns:
            log(f"⚠️ Slice skipped: '{date_col}' column missing", "WARNING")
            return
        dates = seg_df[date_col].dropna().astype(str).str.strip()
        dates = dates[dates != ""]
        if dates.empty:
            log(f"⚠️ Slice skipped: segment {segment_num} has no dates",
                "WARNING")
            return
        date_min, date_max = dates.min(), dates.max()

        slice_dir = cum_csv.parent / "segments"
        slice_dir.mkdir(parents=True, exist_ok=True)
        slice_name = (f"{cum_csv.stem}_seg{segment_num}_"
                      f"{date_min}_to_{date_max}.csv")
        slice_path = slice_dir / slice_name
        try:
            seg_df.to_csv(slice_path, index=False)
        except Exception as e:
            log(f"⚠️ Slice write failed: {e}", "WARNING")
            return
        log(f"📑 Segment slice: {slice_name} ({len(seg_df):,} rows, "
            f"{date_min} → {date_max})", "SUCCESS")

        scripts_dir = cum_csv.resolve().parent.parent / "scripts"
        if str(scripts_dir) not in _sys.path:
            _sys.path.insert(0, str(scripts_dir))
        try:
            import upload_to_drive as _u
            _u.upload_segment_slice(slice_path)
        except Exception as e:
            log(f"⚠️ Slice upload skipped: {e}", "WARNING")

    def _ensure_http_client(self):
        """Lazily build ProHttpClient from the current Selenium cookies."""
        if self._http_client is None and self._fast_api_enabled:
            try:
                self._http_client = _http_client_mod.ProHttpClient.from_selenium(self.driver)
                log("🚀 FAST_API_MODE enabled — built httpx client from Selenium cookies", "SUCCESS")
            except Exception as e:
                log(f"⚠️ Could not build http client, disabling FAST mode: {e}", "WARNING")
                self._fast_api_enabled = False
        return self._http_client

    def _refresh_http_cookies(self):
        """Re-inject access-token / auth-pd-user from Selenium into httpx
        (after soft/deep recovery). Name kept for backward-compat with
        existing recovery hooks.
        """
        if self._http_client:
            try:
                self._http_client.refresh_tokens(self.driver)
                log("🔁 Refreshed httpx tokens from Selenium localStorage", "INFO")
            except Exception as e:
                log(f"⚠️ refresh_tokens failed: {e}", "WARNING")

    def _fetch_list_via_api(self, end_date, page_num):
        """Direct API list fetch — bypasses the broken UI form-fill path.

        Returns list[(bill_id, trade_date)] on success, [] when the
        segment has no more rows (end-of-segment), or None on transport
        failure (caller should fall back to UI).

        Why this exists: the Ant Design v3 date picker on pro.52wmb.com
        rejects programmatic input when the form is loaded with default
        preset values (2025-03-31 / 2026-03-31). Selenium-driven typing,
        grid-clicks, and clear+retry all hit dead ends after 4+ attempts.
        The list endpoint takes the same filter params directly — so we
        skip the UI entirely and ask the server for what we want.
        """
        if not self._fast_api_enabled:
            return None
        client = self._ensure_http_client()
        if not client:
            return None

        size = 30
        params = {
            "country": "vietnam",
            "ie": 0,
            "start": (max(page_num, 1) - 1) * size,
            "size": size,
            "start_date": getattr(config, "DETAIL_START_DATE", None),
            "end_date": end_date or getattr(config, "DETAIL_END_DATE", None),
        }
        hs_code = getattr(config, "DETAIL_HS_CODE", None)
        if hs_code:
            params["hs"] = hs_code
        # Optional filter passthrough — only include if config has them set.
        for cfg_key, api_key in [
            ("DETAIL_BUYER", "buyer"),
            ("DETAIL_SUPPLIER", "supplier"),
            ("DETAIL_PRODUCT", "product"),
            ("DETAIL_BILL_NUMBER", "bill_number"),
            ("DETAIL_BUYER_COUNTRY", "buyer_country"),
            ("DETAIL_POL", "pol"),
            ("DETAIL_POD", "pod"),
            ("DETAIL_SHIPPING_METHOD", "shipping_method"),
        ]:
            v = getattr(config, cfg_key, None)
            if v not in (None, ""):
                params[api_key] = v

        log(f"📡 Fetching list via API: end_date={params['end_date']}, "
            f"page={page_num} (start={params['start']})", "PROCESS")

        def _do_fetch():
            return client.fetch_list(**params)

        try:
            data = _do_fetch()
        except SessionExpired as e:
            log(f"🔒 SessionExpired (state={e.state}) during list fetch — "
                f"refreshing tokens + retry", "WARNING")
            try:
                self._refresh_http_cookies()
                data = _do_fetch()
            except Exception as e2:
                log(f"❌ List API retry after token refresh failed: {e2}",
                    "ERROR")
                return None
        except ApiError as e:
            log(f"❌ List API error: state={getattr(e, 'state', '?')}, "
                f"msg={getattr(e, 'message', str(e))}", "ERROR")
            return None
        except Exception as e:
            # Detect proxy 407 (e.g. expired BrightData creds or zone block).
            err_str = str(e)
            if (("ProxyError" in type(e).__name__
                 or "407" in err_str
                 or "Auth failed" in err_str)
                    and getattr(client, "proxy", None)):
                # acc6: thay vì disable_proxy() (lộ IP thật), rotate session-id
                # qua ProxyRotator để Brightdata cấp IP residential mới. Chỉ
                # disable_proxy nếu rotation disabled hoặc PROXY_ROTATE_ON_407=0.
                rotator = None
                rotate_on_407 = getattr(config, "PROXY_ROTATE_ON_407", False)
                try:
                    from ..core.proxy_rotator import get_rotator
                    rotator = get_rotator()
                except Exception:
                    pass
                if rotator and rotator.enabled and rotate_on_407:
                    rotator.rotate(reason="407_list_api")
                    new_url = rotator.current_proxy_url()
                    log(f"🔄 List API 407 → rotated session, retrying with "
                        f"new IP: {err_str[:80]}", "WARNING")
                    try:
                        client.rebuild_with_proxy(new_url)
                        data = _do_fetch()
                    except Exception as e2:
                        log(f"❌ List API retry after rotate failed: {e2}",
                            "ERROR")
                        return None
                else:
                    log(f"🚫 List API hit proxy 407 — disabling proxy and "
                        f"retrying once: {err_str[:100]}", "WARNING")
                    try:
                        client.disable_proxy()
                        data = _do_fetch()
                    except Exception as e2:
                        log(f"❌ List API retry without proxy failed: {e2}",
                            "ERROR")
                        return None
            else:
                log(f"❌ List API unexpected error: {e}", "ERROR")
                return None

        rows = data.get("list") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            log(f"⚠️ List API returned no 'list' field: keys="
                f"{list(data.keys()) if isinstance(data, dict) else type(data)}",
                "WARNING")
            return None

        specs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            bid = row.get("bill_id")
            tdate = row.get("date")
            if bid is None or not tdate:
                continue
            specs.append((str(bid), str(tdate)))

        # Empty list = end of segment (no more rows). Return [] not None
        # so caller can distinguish "segment done" from "transport failed".
        log(f"📡 List API returned {len(specs)} specs", "INFO")
        return specs

    def _extract_bill_specs_from_list_log(self):
        """Scan recent CDP performance logs for the most recent
        /api/raw/trade/list XHR and extract ordered `(bill_id, trade_date)`
        tuples for the current page.

        Returns list[tuple[str, str]] or None. If `self._api_specs_cache`
        is set (from a recent direct API call), prefers that over the
        CDP log scan — same shape, more reliable.
        """
        cached = getattr(self, "_api_specs_cache", None)
        if cached:
            return cached
        try:
            logs = self.driver.get_log('performance')
        except Exception:
            return None

        latest_rows = None
        for entry in reversed(logs):
            try:
                msg = json.loads(entry['message'])['message']
                if msg.get('method') != 'Network.responseReceived':
                    continue
                url = msg.get('params', {}).get('response', {}).get('url', '')
                if '/trade/list' not in url.lower() and '/raw/trade/list' not in url.lower():
                    continue
                req_id = msg['params']['requestId']
                body = self.driver.execute_cdp_cmd(
                    'Network.getResponseBody', {'requestId': req_id}
                )
                data = json.loads(body.get('body', '{}')).get('data', {})
                rows = data.get('list')
                if isinstance(rows, list) and rows:
                    latest_rows = rows
                    break
            except Exception:
                continue

        if not latest_rows:
            return None

        specs = []
        for row in latest_rows:
            if not isinstance(row, dict):
                continue
            bid = row.get('bill_id')
            tdate = row.get('date')
            if bid is None or not tdate:
                continue
            specs.append((str(bid), str(tdate)))
        return specs or None

    def _fast_fetch_page(self, current_links, page_num, segment_num, start_stt):
        """Fetch details for the current page via httpx parallel GET calls.

        Falls back to UI click for any bill_id that fails. Returns list of
        transactions or None on hard failure (caller retries via UI path).
        """
        # Sticky early-exit: if a previous page proved the detail endpoint
        # rejects un-warmed bills with state=40, stop wasting 5-7s per
        # page on doomed httpx attempts. Caller will UI-click directly.
        if getattr(self, "_fast_api_detail_cold_disabled", False):
            return None

        self._ensure_http_client()
        if not self._http_client:
            return None

        specs = self._extract_bill_specs_from_list_log()
        if not specs or len(specs) < len(current_links):
            log(f"⚠️ List XHR had {len(specs) if specs else 0} specs but page has "
                f"{len(current_links)} rows — aborting fast path for this page", "WARNING")
            return None

        target_specs = specs[start_stt - 1:]
        if not target_specs:
            return []

        # Use the http_client's CURRENT proxy state — disable_proxy() may
        # have set it to None mid-session after a 407, in which case
        # rebuilding from config would re-enable a known-broken proxy.
        proxy = self._http_client.proxy
        access = self._http_client.access_token
        pd_user = self._http_client.pd_user
        ua = self._http_client.user_agent
        if not access or not pd_user:
            log("⚠️ Missing access-token/auth-pd-user, skipping fast path", "WARNING")
            return None

        log(f"⚡ Fast-fetching {len(target_specs)} records via httpx "
            f"(c={config.FAST_API_CONCURRENCY}, rps={config.FAST_API_RATE_LIMIT})",
            "PROCESS")
        try:
            results, errors = fetch_many(
                access_token=access,
                pd_user=pd_user,
                proxy=proxy,
                bill_specs=target_specs,
                user_agent=ua,
                concurrency=config.FAST_API_CONCURRENCY,
                rps=config.FAST_API_RATE_LIMIT,
                attempts=config.FAST_API_RETRIES,
            )
        except SessionExpired as e:
            log(f"🔒 SessionExpired (state={e.state}) during fast fetch — recovering",
                "WARNING")
            if self.perform_soft_recovery(batch_config=getattr(self, 'batch_config', None)):
                self._refresh_http_cookies()
            else:
                self.perform_deep_recovery(batch_config=getattr(self, 'batch_config', None))
                self._refresh_http_cookies()
            return None

        # Detect persistent proxy auth failure (BrightData 407 etc).
        # acc6: Thay vì disable_proxy() (lộ IP thật, dễ ban tài khoản hơn),
        # rotate session-id qua ProxyRotator để cấp IP residential mới.
        if proxy and errors and len(errors) == len(target_specs):
            proxy_errs = sum(
                1 for err in errors.values()
                if isinstance(err, tuple) and err and err[0] == "proxy"
            )
            if proxy_errs == len(target_specs):
                rotator = None
                rotate_on_407 = getattr(config, "PROXY_ROTATE_ON_407", False)
                try:
                    from ..core.proxy_rotator import get_rotator
                    rotator = get_rotator()
                except Exception:
                    pass
                if rotator and rotator.enabled and rotate_on_407:
                    log(f"🔄 All {len(target_specs)} fast-fetch tasks 407 — "
                        f"rotating Brightdata session-id (caller will retry)",
                        "WARNING")
                    rotator.rotate(reason="407_fast_fetch_all")
                    try:
                        self._http_client.rebuild_with_proxy(
                            rotator.current_proxy_url())
                    except Exception as e:
                        log(f"⚠️ rebuild_with_proxy failed: {e}", "WARNING")
                    return None  # caller retries with rotated session
                log(f"🚫 All {len(target_specs)} fast-fetch tasks failed "
                    f"with proxy 407 — disabling proxy for the rest of "
                    f"the session (next page will retry without proxy)",
                    "WARNING")
                try:
                    self._http_client.disable_proxy()
                except Exception as e:
                    log(f"⚠️ disable_proxy() failed: {e}", "WARNING")
                return None  # caller will retry next page (no proxy)

        # acc6: Detect rate-limit (429) — async_fetcher đã backoff exponential
        # nhưng nếu vẫn fail → log session bị throttled, cooldown + rotate.
        if errors:
            rate_limit_errs = sum(
                1 for err in errors.values()
                if isinstance(err, tuple) and err and err[0] == "429"
            )
            # Threshold: ≥30% of target_specs hit 429 → session bị throttle.
            if rate_limit_errs >= max(3, int(len(target_specs) * 0.3)):
                rotator = None
                try:
                    from ..core.proxy_rotator import get_rotator
                    rotator = get_rotator()
                except Exception:
                    pass
                if rotator and rotator.enabled:
                    log(f"⚠️ {rate_limit_errs}/{len(target_specs)} fast-fetch "
                        f"hit 429 → cooldown + rotate session", "WARNING")
                    rotator.cooldown_on_block(reason="429_fast_fetch")
                    try:
                        self._http_client.rebuild_with_proxy(
                            rotator.current_proxy_url())
                    except Exception as e:
                        log(f"⚠️ rebuild_with_proxy failed: {e}", "WARNING")
                    return None  # caller retries with new IP

        # Detect state=40 cold-API limitation. The server rejects detail
        # GETs for any bill_id that hasn't been warmed up by a UI click,
        # returning state=40 with empty message. Documented in
        # src/config/settings.py:33-35. When ≥80% of bills on a page
        # come back state=40, the parallel-fetch optimization is just
        # wasting time before falling back to UI click anyway. Set the
        # sticky flag so future pages skip httpx entirely.
        if errors:
            state40_count = sum(
                1 for err in errors.values()
                if isinstance(err, tuple) and len(err) >= 1 and err[0] == 40
            )
            if state40_count >= len(target_specs) * 0.8:
                log(f"⚠️ {state40_count}/{len(target_specs)} bills returned "
                    f"state=40 (cold API: bills must be UI-clicked first). "
                    f"Disabling fast detail path for the rest of the run; "
                    f"future pages will UI-click directly without the "
                    f"5-7s httpx pre-fetch.", "WARNING")
                self._fast_api_detail_cold_disabled = True

                # CRITICAL: in api-only mode, the UI table is NOT aligned
                # with our API specs — falling back to UI click would
                # scrape wrong rows. So we must abort api-only mode AND
                # signal scrape_page to trigger SOFT recovery (which
                # refills the UI form correctly), then retry the page.
                # Without this, 29/30 rows would silently be logged as
                # failed and lost.
                if getattr(self, "_api_only_until_segment_end", False):
                    log("🔁 State=40 in API-only mode → abandoning "
                        "api-only, page will retry after UI form fill",
                        "WARNING")
                    self._api_only_until_segment_end = False
                    return None  # signal scrape_page to recover + retry

                # Otherwise (UI mode): let the existing UI fallback below
                # finish this page's stragglers. Next page will skip
                # httpx via the early-exit check at the top.

        transactions = []
        ui_fallback_indices = []
        wrong_filter_drops = []  # (stt, bid, reason) — for abort decision
        # Filter guards: any row that fails ANY configured filter
        # (HS / buyer / supplier) is poison data — write it and the CSV
        # becomes unreliable downstream. Originally added for the
        # 2026-05-04 hs58 incident (API list returned wrong HS chapters).
        # Extended to buyer/supplier so buyer-only crawls (acc5 austgrow)
        # are also protected.
        expected_hs_prefix = str(
            getattr(config, 'DETAIL_HS_CODE', '') or '').strip()
        expected_buyer = str(
            getattr(config, 'DETAIL_BUYER', '') or '').strip().lower()
        expected_supplier = str(
            getattr(config, 'DETAIL_SUPPLIER', '') or '').strip().lower()

        for offset, (bid, _tdate) in enumerate(target_specs):
            stt = start_stt + offset
            if self._rate_meter:
                self._rate_meter.tick(ok=bid in results)
            if bid not in results:
                ui_fallback_indices.append((stt, bid))
                continue

            data_obj = results[bid]
            tx = dict(data_obj.get('detail') or {})
            if not tx or len(tx) <= 3:
                ui_fallback_indices.append((stt, bid))
                continue

            # Filter validation — drop rows that don't match configured
            # filters. Both display columns ('HS Code', 'Buyer') and raw
            # API fields ('hs', 'importer_name_en') checked since different
            # code paths populate different keys.
            _drop_reason = None
            if expected_hs_prefix:
                actual_hs = (
                    str(tx.get('HS Code') or tx.get('hs_code')
                        or tx.get('hs') or '').strip()
                )
                # OR-aware — DETAIL_HS_CODE có thể chứa `|` (vd "52|55").
                if actual_hs and not _hs_prefix_matches(
                        expected_hs_prefix, actual_hs):
                    _drop_reason = (
                        f"HS={actual_hs}, expected prefix "
                        f"'{expected_hs_prefix}'")
            if not _drop_reason and expected_buyer:
                # acc6: OR-aware match — `DETAIL_BUYER` có thể chứa `|` cho
                # nhiều alternatives (server coi `|` là OR).
                _vi_buyer = str(tx.get('buyer') or tx.get('Buyer') or '')
                _en_buyer = str(tx.get('importer_name_en') or '')
                if not _filter_matches(expected_buyer, [_vi_buyer, _en_buyer]):
                    _actual = (_vi_buyer or _en_buyer).strip().lower()
                    _drop_reason = (
                        f"Buyer='{_actual[:60]}' doesn't contain any of "
                        f"'{expected_buyer}'")
            if not _drop_reason and expected_supplier:
                # acc6: OR-aware match cho supplier (cùng `|` syntax).
                _vi_sup = str(tx.get('Supplier') or tx.get('seller') or '')
                _en_sup = str(tx.get('exporter_name_en') or '')
                if not _filter_matches(expected_supplier, [_vi_sup, _en_sup]):
                    _actual_sup = (_vi_sup or _en_sup).strip().lower()
                    _drop_reason = (
                        f"Supplier='{_actual_sup[:60]}' doesn't contain "
                        f"any of '{expected_supplier}'")
            if _drop_reason:
                log(f"⚠️ Filter guard: bill {bid} {_drop_reason} "
                    f"— dropping (stt={stt}).", "WARNING")
                wrong_filter_drops.append((stt, bid, _drop_reason))
                continue

            server_titles = data_obj.get('title', [])
            if server_titles:
                self.update_mapping_from_server(server_titles)

            tx['segment'] = segment_num
            tx['page'] = page_num
            tx['stt'] = stt
            tx.setdefault('bill_id', bid)
            transactions.append(tx)

        if errors:
            log(f"⚠️ Fast path errors for {len(errors)} bills: "
                f"sample={list(errors.items())[:3]}", "WARNING")

        # If a meaningful chunk of this page came back with wrong filter
        # values while in API-only mode, the list endpoint isn't honoring
        # filter params for this query — abandon API-only path and let
        # the caller re-fill the UI form (which DOES filter correctly)
        # before touching another page. Threshold low (≥3) because even
        # 1 wrong row is a red flag — we'd rather pay a UI refill than
        # risk corrupting more data.
        if (getattr(self, "_api_only_until_segment_end", False)
                and len(wrong_filter_drops) >= 3):
            log(f"❌ Filter guard: {len(wrong_filter_drops)} wrong-filter rows on "
                f"page {page_num} in API-only mode — server list endpoint "
                f"is NOT filtering by HS. Abandoning API-only path; "
                f"caller will refill UI form.", "ERROR")
            self._api_only_until_segment_end = False
            return None  # signal scrape_page to SOFT recover + retry

        if ui_fallback_indices:
            # Skip UI fallback in API-only mode — the table isn't filled
            # via UI search, so detail links don't match the API specs.
            # Just log the failed rows; they're recoverable via re-run.
            if getattr(self, "_api_only_until_segment_end", False):
                log(f"⚠️ {len(ui_fallback_indices)} rows failed API detail "
                    f"fetch (skipping UI fallback in API-only mode); "
                    f"logging to failed_rows.jsonl", "WARNING")
                for stt, bid in ui_fallback_indices:
                    self._log_failed("row", segment_num, page_num, stt,
                                     reason="api_detail_failed_in_api_only_mode",
                                     bill_id=bid)
            else:
                log(f"🔁 Falling back to UI click for "
                    f"{len(ui_fallback_indices)} rows", "WARNING")
                for stt, _bid in ui_fallback_indices:
                    try:
                        fresh_links = self.driver.find_elements(
                            By.XPATH, "//a[contains(text(), 'Details')]"
                        )
                        if stt - 1 >= len(fresh_links):
                            continue
                        resp = self.click_details_and_capture(
                            fresh_links[stt - 1], stt, max_retries=3,
                        )
                        if resp:
                            tx = dict(resp.get('detail') or {})
                            if tx:
                                tx['segment'] = segment_num
                                tx['page'] = page_num
                                tx['stt'] = stt
                                transactions.append(tx)
                    except Exception as e:
                        log(f"   ❌ UI fallback for STT {stt} failed: {e}",
                            "ERROR")

        transactions.sort(key=lambda t: t.get('stt', 0))
        return transactions

    def scrape_page(self, page_num, segment_num, start_stt=1):
        """
        Scrape transactions from current page starting from start_stt.
        Returns a list of transactions for per-page saving.
        """
        try:
            # acc6: Page-boundary IP rotation. Mỗi `PROXY_ROTATION_INTERVAL_PAGES`
            # page → cycle session-id để Brightdata cấp IP mới. Chỉ rebuild
            # httpx client (Selenium giữ nguyên proxy — restart Chrome quá đắt).
            try:
                from ..core.proxy_rotator import get_rotator
                _rot = get_rotator()
                if _rot.enabled and _rot.should_rotate_by_page_count(page_num):
                    _rot.rotate(reason=f"page_boundary_p{page_num}")
                    _rot.mark_rotated_at_page(page_num)
                    if getattr(self, "_http_client", None):
                        try:
                            self._http_client.rebuild_with_proxy(
                                _rot.current_proxy_url())
                        except Exception as e:
                            log(f"[ProxyRotator] rebuild httpx failed: {e}",
                                "WARNING")
            except Exception:
                pass

            # Stability wait for table load (Plan E: reduced 0.5 -> 0.2)
            time.sleep(0.2)

            # --- API-DIRECT PATH (form-fill bypass) ----------------------
            # When UI form fill broke and we flipped to API-only mode,
            # skip DOM reads entirely and call the list endpoint directly.
            if (getattr(self, "_api_only_until_segment_end", False)
                    and self._fast_api_enabled):
                api_specs = self._fetch_list_via_api(
                    end_date=self.segment_end_date, page_num=page_num)
                if api_specs is None:
                    log("⚠️ API list fetch failed — disabling API-only mode "
                        "for this segment, dropping back to UI", "WARNING")
                    self._api_only_until_segment_end = False
                    self._api_specs_cache = None
                    # fall through to UI path below
                elif not api_specs:
                    log(f"✅ API list returned 0 rows on page {page_num} — "
                        f"end of segment {segment_num}", "SUCCESS")
                    return []
                else:
                    # Cache so _extract_bill_specs_from_list_log returns
                    # these instead of scanning CDP log.
                    self._api_specs_cache = api_specs
                    # Synthetic links of matching length so _fast_fetch_page's
                    # length check passes (it doesn't actually click them
                    # in API-only mode — see UI fallback skip above).
                    synthetic_links = [None] * len(api_specs)
                    try:
                        fast_tx = self._fast_fetch_page(
                            synthetic_links, page_num, segment_num, start_stt)
                    finally:
                        self._api_specs_cache = None
                    if fast_tx is not None:
                        self._fast_api_consecutive_failures = 0
                        return fast_tx
                    # fast_tx None in api-only mode = state=40 cold
                    # detected, api-only abandoned. UI table is NOT
                    # aligned with our API specs (form not filled with
                    # current segment's filters), so falling through
                    # to UI path would scrape wrong rows (Apr 2026
                    # default page). Force SOFT recovery to refill UI
                    # form, then retry this page from scratch.
                    log("🔁 API-only abandoned — triggering SOFT recovery "
                        "to refill UI form, then retry page", "WARNING")
                    self._api_only_until_segment_end = False
                    if self.perform_soft_recovery(
                            batch_config=getattr(self, 'batch_config', None)):
                        log(f"🔄 SOFT recovery OK — retrying page {page_num}",
                            "INFO")
                        return self.scrape_page(
                            page_num, segment_num, start_stt)
                    log("❌ SOFT recovery failed after api-only abandon — "
                        "returning empty", "ERROR")
                    return []

            # --- FAST API PATH (UI-driven, hybrid) -----------------------
            if self._fast_api_enabled:
                current_links = self.driver.find_elements(
                    By.XPATH, "//a[contains(text(), 'Details')]"
                )
                if current_links:
                    fast_tx = self._fast_fetch_page(current_links, page_num, segment_num, start_stt)
                    if fast_tx is not None:
                        self._fast_api_consecutive_failures = 0
                        return fast_tx
                    # Distinguish "intentional skip" (state=40 sticky disable,
                    # proxy disabled-then-retry) from "actual failure" (httpx
                    # exception, malformed response). Intentional skips
                    # already routed us via UI fallback below — they're not
                    # failures, so don't penalize the counter that disables
                    # fast_api permanently. Otherwise 3 sticky skips would
                    # lose us the API list path used by recovery.
                    if not getattr(self, "_fast_api_detail_cold_disabled", False):
                        self._fast_api_consecutive_failures += 1
                        if (self._fast_api_consecutive_failures
                                >= config.FAST_API_FALLBACK_THRESHOLD):
                            log(f"🛑 FAST_API failed {self._fast_api_consecutive_failures} pages "
                                f"in a row — disabling for the rest of this run", "ERROR")
                            self._fast_api_enabled = False
            # --- END FAST API PATH ---------------------------------------

            
            # First, determine how many rows we need to scrape
            detail_links = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Details')]")
            total_rows = len(detail_links)
            
            if start_stt > 1:
                log(f"🔍 Resuming Page {page_num} from STT {start_stt} (found {total_rows} total rows)", "SEARCH")
            else:
                log(f"🔍 Found {total_rows} rows on Page {page_num}", "SEARCH")
            
            # Use index loop to handle potential page refreshes (recovery)
            row_idx = start_stt - 1
            transactions = []
            
            while row_idx < total_rows:
                try:
                    stt = row_idx + 1
                    
                    # Re-find links in case of stale element or refresh
                    current_links = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Details')]")
                    if row_idx >= len(current_links):
                        break
                        
                    # Request capture with 7 retries
                    response_obj = self.click_details_and_capture(current_links[row_idx], stt, max_retries=3)
                    
                    if response_obj:
                        # response_obj is now {'detail': ..., 'title': ...}
                        transaction_data = response_obj.get('detail', {})
                        
                        # Validate if the server returned an empty {} object despite state=0
                        if not transaction_data or not isinstance(transaction_data, dict):
                            log(f"   ⚠️ Row {stt}: Server returned empty detail object. Retrying...", "DEBUG")
                            continue # Try next attempt of the 7 retries, or fail
                            
                        server_titles = response_obj.get('title', [])
                        
                        if server_titles:
                            # Dynamically align our mapping with server's definitions
                            self.update_mapping_from_server(server_titles)
                        
                        transaction_data['segment'] = segment_num
                        transaction_data['page'] = page_num
                        transaction_data['stt'] = stt
                        
                        # ============================================================
                        # CRITICAL DATE INTEGRITY CHECK
                        # ============================================================
                        if self.segment_end_date:
                            tx_date_str = self._extract_transaction_date(transaction_data)
                            if tx_date_str and tx_date_str > self.segment_end_date:
                                log(f"❌ CRITICAL DATA VIOLATION: Record Date {tx_date_str} > Segment Boundary {self.segment_end_date}", "ERROR")
                                log(f"   -> The Search Filter is NOT working correctly.", "ERROR")
                                # Re-raise as ValueError to escape the row loop and trigger recovery
                                raise ValueError(f"Date Integrity Violation: {tx_date_str} > {self.segment_end_date}")
                            
                            # NEW: Check against last scraped date (Descending order conflict)
                            # To handle potential minor timestamp jitter, we enforce the rule that
                            # the newly scraped date shouldn't be drastically newer than the last scraped date.
                            if hasattr(self, 'last_scraped_date') and self.last_scraped_date:
                                if tx_date_str > self.last_scraped_date:
                                    log(f"❌ DATE CONFLICT DETECTED: Record Date {tx_date_str} > Last Scraped Date {self.last_scraped_date}", "ERROR")
                                    log(f"   -> Scraped newer data than expected (maybe wrong page loaded).", "ERROR")
                                    raise ValueError(f"Date Conflict Violation: {tx_date_str} > {self.last_scraped_date}")

                        # Filter guard — same protection as _fast_fetch_page
                        # but for UI click path. Triggered after SOFT
                        # recovery flipped api-only mode but the row-retry
                        # loop still uses UI click on a table whose filter
                        # got reset by the page refresh in SOFT recovery.
                        # Checks HS / buyer / supplier filters from config.
                        _hs_pref = str(
                            getattr(config, 'DETAIL_HS_CODE', '') or '').strip()
                        _buyer_pref = str(
                            getattr(config, 'DETAIL_BUYER', '') or ''
                        ).strip().lower()
                        _supplier_pref = str(
                            getattr(config, 'DETAIL_SUPPLIER', '') or ''
                        ).strip().lower()
                        _ui_drop_reason = None
                        if _hs_pref:
                            _actual_hs = str(
                                transaction_data.get('HS Code')
                                or transaction_data.get('hs_code')
                                or transaction_data.get('hs') or ''
                            ).strip()
                            # OR-aware HS prefix (`|` syntax).
                            if (_actual_hs
                                    and not _hs_prefix_matches(
                                        _hs_pref, _actual_hs)):
                                _ui_drop_reason = (
                                    f"HS={_actual_hs} doesn't start with "
                                    f"any of '{_hs_pref}'")
                        if not _ui_drop_reason and _buyer_pref:
                            # acc6: OR-aware — `DETAIL_BUYER` có thể có `|`.
                            _vi_b = str(
                                transaction_data.get('buyer')
                                or transaction_data.get('Buyer') or ''
                            )
                            _en_b = str(
                                transaction_data.get('importer_name_en') or ''
                            )
                            if not _filter_matches(_buyer_pref, [_vi_b, _en_b]):
                                _actual_b = (_vi_b or _en_b).strip().lower()
                                _ui_drop_reason = (
                                    f"Buyer='{_actual_b[:60]}' doesn't "
                                    f"contain any of '{_buyer_pref}'")
                        if not _ui_drop_reason and _supplier_pref:
                            # acc6: OR-aware cho supplier (cùng `|` syntax).
                            _vi_s = str(
                                transaction_data.get('Supplier')
                                or transaction_data.get('seller') or ''
                            )
                            _en_s = str(
                                transaction_data.get('exporter_name_en') or ''
                            )
                            if not _filter_matches(_supplier_pref, [_vi_s, _en_s]):
                                _actual_s = (_vi_s or _en_s).strip().lower()
                                _ui_drop_reason = (
                                    f"Supplier='{_actual_s[:60]}' doesn't "
                                    f"contain any of '{_supplier_pref}'")
                        if _ui_drop_reason:
                            log(f"⚠️ Filter guard (UI): row {stt} "
                                f"{_ui_drop_reason}. UI table likely lost "
                                f"filter after recovery — raising to trigger "
                                f"SOFT recovery + refill form.", "ERROR")
                            raise ValueError(
                                f"Filter Violation: {_ui_drop_reason} "
                                f"(UI table lost filter after recovery)")

                        transactions.append(transaction_data)
                        
                        # Log with distinct identifier (B/L No followed by Serial No if available)
                        bl_no = transaction_data.get('bill_no') or 'N/A'
                        ser_no = transaction_data.get('export_declaration_number') or \
                                 transaction_data.get('declaration_number') or ''
                        
                        display_id = bl_no
                        if ser_no and ser_no != bl_no:
                            display_id = f"{bl_no} ({ser_no})"
                            
                        log(f"✅ ✅ ✅ [Page {page_num}] [{stt}/{total_rows}] Scraped {display_id}", "SUCCESS")
                        row_idx += 1
                        # Plan E: removed 0.2s per-row sleep (saves ~6s/page)
                    else:
                        # Row failed all in-line retries. Recovery time.
                        key = (segment_num, page_num, stt)
                        self._recovery_attempts_by_row[key] = (
                            self._recovery_attempts_by_row.get(key, 0) + 1
                        )
                        attempt_n = self._recovery_attempts_by_row[key]

                        # Give up on this specific row if recovery didn't
                        # unstick it after MAX_RECOVERIES_PER_ROW tries —
                        # otherwise we loop forever (seen in production).
                        if attempt_n > self.MAX_RECOVERIES_PER_ROW:
                            log(f"🪦 Row {stt}: recovery attempt "
                                f"{attempt_n} > {self.MAX_RECOVERIES_PER_ROW} — "
                                f"giving up, skipping to next row.", "ERROR")
                            self._log_failed(
                                "row",
                                segment=segment_num,
                                page=page_num,
                                stt=stt,
                                reason=f"Row un-scrapable after "
                                       f"{self.MAX_RECOVERIES_PER_ROW} recoveries",
                            )
                            row_idx += 1
                            continue

                        log(f"💀 Row {stt} failed 3 capture attempts. "
                            f"Recovery #{attempt_n}/{self.MAX_RECOVERIES_PER_ROW}...",
                            "ERROR")

                        # 1. Try SOFT Recovery
                        if self.perform_soft_recovery(batch_config=getattr(self, 'batch_config', None)):
                            # If SOFT recovery flipped to api-only mode
                            # (UI fill failed, fell back to API-direct),
                            # the UI table is NOT aligned with current
                            # filters. Continuing UI click here = wrong
                            # rows. Abort the loop and let scrape_page's
                            # caller re-call us; the next call will see
                            # _api_only_until_segment_end=True at the top
                            # of scrape_page and route through the API
                            # list path instead.
                            if getattr(self, "_api_only_until_segment_end", False):
                                log("🔁 SOFT recovery → api-only mode. "
                                    "Aborting UI click loop on page "
                                    f"{page_num}; restarting via API path.",
                                    "WARNING")
                                return self.scrape_page(
                                    page_num, segment_num, start_stt=stt)
                            # Flush already-captured rows to CSV before
                            # restarting. The new search may return records
                            # in a different order (snapshot B != snapshot A),
                            # so we cannot safely resume from row_idx=N of
                            # the new DOM — we must restart from row 1 for a
                            # coherent snapshot. Flushing now ensures these
                            # rows are not lost if a crash occurs during the
                            # restart. The restart will re-scrape them and
                            # produce duplicates; the DA pipeline deduplicates
                            # downstream (CsvSink intentionally writes all rows).
                            if transactions:
                                self._csv_sink.append(transactions)
                                log(f"[+] Flushed {len(transactions)} "
                                    f"pre-recovery rows to CSV.", "INFO")
                            log(f"[>] SOFT recovery done. Restarting page "
                                f"{page_num} from row 1 for a consistent "
                                f"snapshot.", "INFO")
                            return self.scrape_page(
                                page_num, segment_num, start_stt=1)
                        else:
                            # 2. Try DEEP Recovery
                            log(f"⚠️ Soft Recovery failed for Row {stt}. Escalating to DEEP RECOVERY...", "WARNING")

                            batch_cfg = getattr(self, 'batch_config', None)
                            if self.perform_deep_recovery(batch_config=batch_cfg):
                                log(f"🔄 Deep Recovery done. Retrying Row {stt}...", "INFO")
                                continue
                            else:
                                log(f"❌ All recoveries failed (Socket dead) for Row {stt}. Aborting page.", "ERROR")
                                self._log_failed(
                                    "page",
                                    segment=segment_num,
                                    page=page_num,
                                    stt=stt,
                                    reason="Both soft + deep recovery failed",
                                )
                                return None
                    
                except ValueError as ve:
                    # Critical logic error (Integrity), re-raise to abort page immediately
                    raise ve
                    
                except Exception as e:
                    log(f"   ❌ Row {row_idx + 1}: {e}", "ERROR")
                    row_idx += 1
            
            return transactions
        except ValueError:
            raise
        except Exception as e:
            log(f"❌ Error scraping page {page_num}: {e}", "ERROR")
            return []

    def go_to_page(self, page_target):
        """Delegate to src.nav.pagination.go_to_page."""
        return _nav_pagination.go_to_page(self.driver, self.wait, page_target)


    def _extract_transaction_date(self, transaction):
        """Delegate to src.parsing.transaction.extract_transaction_date."""
        return _parsing_extract_date(transaction)

    def perform_soft_recovery(self, batch_config=None):
        """
        Perform SOFT recovery: Refresh page and re-apply filters.
        Uses self.segment_end_date for segment-aware recovery.
        
        Enhanced to handle re-login scenarios on Pro 2026:
        - Detects if login form appears after refresh
        - Performs re-login and navigates back to Customs Data
        - Then re-fills search form and jumps to current page
        
        Auto-escalates to DEEP recovery if SOFT fails.
        """
        try:
            log("♻️ Performing SOFT recovery (Page Refresh & Search Re-fill)...", "PROCESS")
            if self.segment_end_date:
                log(f"📍 Recovery will use segment end date: {self.segment_end_date}", "INFO")
            
            try:
                self.driver.refresh()
            except Exception as refresh_err:
                log(f"❌ Refresh Navigation Failed (Socket Die?): {refresh_err}", "ERROR")
                return self.perform_deep_recovery(batch_config=batch_config)
            
            time.sleep(3)  # Longer wait for page to settle
            self.close_tips_modal()
            
            # ============================================================
            # CHECK FOR RE-LOGIN REQUIREMENT (Pro 2026 session expiry)
            # ============================================================
            needs_relogin = False
            
            # Check 1: Login form visible on Pro 2026
            try:
                login_form = self.driver.find_element(By.ID, "formLogin")
                if login_form.is_displayed():
                    needs_relogin = True
                    log("🔐 Login form detected - session expired, need to re-login", "WARNING")
            except:
                pass
            
            # Check 2: Username/password inputs visible
            if not needs_relogin:
                try:
                    username_input = self.driver.find_element(By.ID, "username")
                    password_input = self.driver.find_element(By.ID, "password")
                    if username_input.is_displayed() and password_input.is_displayed():
                        needs_relogin = True
                        log("🔐 Login inputs detected - need to re-login", "WARNING")
                except:
                    pass
            
            # Check 3: URL contains "login"
            if not needs_relogin:
                current_url = self.driver.current_url.lower()
                if "login" in current_url or "signin" in current_url:
                    needs_relogin = True
                    log(f"🔐 Login URL detected: {current_url}", "WARNING")
            
            # ============================================================
            # PERFORM RE-LOGIN IF NEEDED
            # ============================================================
            if needs_relogin:
                log("🔐 Performing Pro 2026 re-login...", "PROCESS")
                
                try:
                    from selenium.webdriver.support.ui import WebDriverWait
                    slow_wait = WebDriverWait(self.driver, 60)
                    # Fill username
                    username_input = None
                    for attempt in range(3):
                        try:
                            username_input = slow_wait.until(
                                EC.presence_of_element_located((By.ID, "username"))
                            )
                            break
                        except Exception:
                            log(f"White screen / login form not ready (attempt {attempt+1}/3). Retrying...", "WARNING")
                            try:
                                self.driver.refresh()
                                time.sleep(5)
                            except: pass
                            
                    if not username_input:
                        raise Exception("Login form never appeared after 3 refreshes (White screen of death)")
                        
                    self.driver.execute_script("""
                        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(arguments[0], arguments[1]);
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    """, username_input, config.USERNAME)
                    
                    # Fill password
                    password_input = slow_wait.until(
                        EC.presence_of_element_located((By.ID, "password"))
                    )
                    self.driver.execute_script("""
                        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(arguments[0], arguments[1]);
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    """, password_input, config.PASSWORD)
                    
                    # Click login button
                    login_button = slow_wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "button.login-button, button[type='submit']"))
                    )
                    self.driver.execute_script("arguments[0].click();", login_button)
                    log("✅ Login form submitted", "INFO")
                    
                    slow_wait.until(EC.url_contains("/Workbenches"))
                    self.close_tips_modal()
                    
                    log("✅ Re-login successful", "SUCCESS")
                    
                except Exception as login_error:
                    log(f"❌ Re-login failed: {login_error}", "ERROR")
                    return self.perform_deep_recovery(batch_config=batch_config)
                
                # ============================================================
                # NAVIGATE BACK TO CUSTOMS DATA (after re-login)
                # ============================================================
                log("📍 Navigating back to Customs Data after re-login...", "PROCESS")
                
                # Check if we need to navigate from Workbenches
                current_url = self.driver.current_url.lower()
                
                if "customsdata" not in current_url:
                    # Need to click Market Analysis -> Customs Data
                    try:
                        # First try clicking Market Analysis
                        if not navigator_pro.click_market_analysis(self.driver, self.wait):
                            log("⚠️ Could not click Market Analysis", "WARNING")
                        
                        time.sleep(1)
                        
                        # Then click Customs Data
                        if not navigator_pro.click_customs_data(self.driver, self.wait):
                            log("❌ Could not navigate to Customs Data", "ERROR")
                            return self.perform_deep_recovery(batch_config=batch_config)
                        
                        log("✅ Navigated back to Customs Data", "SUCCESS")
                        time.sleep(2)
                        
                    except Exception as nav_error:
                        log(f"❌ Navigation failed: {nav_error}", "ERROR")
                        return self.perform_deep_recovery(batch_config=batch_config)
                
                self.close_tips_modal()
            
            # ============================================================
            # RE-FILL SEARCH FORM (normal soft recovery flow)
            # API-FIRST recovery (2026-04-29 update):
            # The UI form fill burns ~3.5 min per attempt when the date
            # picker is flaky. Doing 4 attempts × backoff = 14+ min per
            # recovery cycle is wasteful when we have a working JSON
            # endpoint. So: try the API list path FIRST (5-10s). If it
            # works, switch to API-only mode for the rest of the segment
            # — no UI date picker, no popup leaks, no flaky country
            # dropdown. UI is now the FALLBACK only when API can't work
            # ORDERING: try UI form fill FIRST. The previous "API-direct
            # FIRST" ordering (commit 75d5cab and earlier) caused real
            # data corruption: API-direct sets _api_only_until_segment_end
            # = True but the page refresh that preceded it cleared the UI
            # form filter, so the in-progress row-retry loop kept clicking
            # current_links[idx] against an UNFILTERED DOM table → wrong
            # bills (e.g., 2026-05-05 acc5 austgrow incident: rows 27-30
            # of page 2 captured non-austgrow bills 26MBAIM401163888).
            # UI fill restores the filtered table, so the row-retry loop
            # can resume safely. API-direct stays as last-resort fallback
            # ONLY when UI fill genuinely can't recover (Ant date-picker
            # DOM corruption etc.).
            FILL_RETRY_WAITS = [10, 60]  # 2 attempts, gap before retry
            FILL_MAX_ATTEMPTS = len(FILL_RETRY_WAITS) + 1  # 3 attempts max
            fill_ok = False
            for fill_attempt in range(1, FILL_MAX_ATTEMPTS + 1):
                log(f"📝 SOFT recovery UI fill attempt {fill_attempt}/"
                    f"{FILL_MAX_ATTEMPTS}", "PROCESS")
                if navigator_pro.fill_search_form_detail(
                    self.driver, self.wait,
                    end_date_override=self.segment_end_date,
                    batch_config=batch_config,
                ):
                    navigator_pro.click_search_button_detail(
                        self.driver, self.wait)
                    # Flush stale CDP perf log so _extract_bill_specs_from_list_log
                    # only sees XHRs fired AFTER this filtered search, not the
                    # unfiltered refresh XHR from driver.refresh() above.
                    try:
                        self.driver.get_log('performance')
                    except Exception:
                        pass
                    time.sleep(2)
                    fill_ok = True
                    break

                if fill_attempt < FILL_MAX_ATTEMPTS:
                    wait_s = FILL_RETRY_WAITS[fill_attempt - 1]
                    log(f"⚠️ UI fill attempt {fill_attempt} failed — "
                        f"network probe + refresh + retry in {wait_s}s",
                        "WARNING")
                    self._probe_network_and_log()
                    try:
                        self.driver.refresh()
                    except Exception as ref_err:
                        log(f"⚠️ Refresh error (non-fatal): {ref_err}",
                            "WARNING")
                    time.sleep(wait_s)
                    try:
                        self.close_tips_modal()
                    except Exception:
                        pass
                    try:
                        api_client.wait_for_loading_overlay(
                            self.driver, timeout=15)
                    except Exception:
                        pass

            if fill_ok:
                # UI fill succeeded — table is back in filtered state at
                # page 1. Clear api-only flag so any leftover from prior
                # recovery doesn't keep scrape_page in API mode.
                self._api_only_until_segment_end = False
                # CRITICAL: navigate back to self.current_page BEFORE
                # returning. After search, DOM is showing page 1 of the
                # filtered result set. Scraper's row-retry loop expects
                # to be on self.current_page (e.g. page 7) and will
                # click current_links[idx] — but those links point to
                # page 1's bills. Without this jump, every recovery
                # silently re-scrapes page 1's data while incrementing
                # current_page → CSV ends up with page 8/9 holding
                # what is actually page 1/2 content (= the 2026-05-05
                # acc5 austgrow page-7-vs-page-8 "na ná" incident).
                if self.current_page > 1:
                    log(f"⏭️  Recovery: Jumping back to page "
                        f"{self.current_page}...", "INFO")
                    if not self.go_to_page(self.current_page):
                        log(f"❌ Failed to reach page "
                            f"{self.current_page} after UI fill — "
                            f"escalating to DEEP recovery", "ERROR")
                        return self.perform_deep_recovery(
                            batch_config=batch_config)
                self._refresh_http_cookies()
                log("✅ SOFT recovery complete (UI form refilled, "
                    f"jumped to page {self.current_page})", "SUCCESS")
                return True

            # UI form fill failed. Last-resort: API-direct list path,
            # ONLY if state=40 cold-API hasn't been observed.
            if (self._fast_api_enabled
                    and self._ensure_http_client()
                    and not getattr(self, "_fast_api_detail_cold_disabled", False)):
                log(f"⚠️ UI form fill failed {FILL_MAX_ATTEMPTS}× — "
                    f"falling back to API-direct list path (api-only "
                    f"mode for rest of segment {self.current_segment}). "
                    f"Caller MUST stop clicking UI rows and let "
                    f"scrape_page restart via API path.", "WARNING")
                self._api_only_until_segment_end = True
                self._refresh_http_cookies()
                log("✅ SOFT recovery complete (API-only fallback)",
                    "SUCCESS")
                return True  # scrape_page handles list fetch via API
            elif self._is_driver_dead():
                # Chrome/chromedriver session lost (Mac sleep, crash, etc).
                # No amount of "fill form again" will work — driver is dead.
                # Raise so supervisor restarts python with a fresh driver.
                raise RuntimeError(
                    "WebDriver session dead during SOFT recovery — "
                    "supervisor will restart with fresh Chrome (CSV "
                    "checkpoint resumes from last scraped row).")
            elif getattr(self, "_fast_api_detail_cold_disabled", False):
                # UI form fill broken AND api-only path can't help
                # (state=40 cold-API limitation). Without restart, we'd
                # loop: api-only → state=40 → SOFT → UI fail → ...
                # Raise to force fresh Chrome via supervisor restart;
                # CSV resumes, fresh driver typically fixes the form.
                log(f"❌ UI form fill failed {FILL_MAX_ATTEMPTS}× AND "
                    f"api-only can't help (cold-API state=40 active). "
                    f"Raising to force supervisor restart with fresh Chrome.",
                    "ERROR")
                raise RuntimeError(
                    f"UI form fill stuck + api-only blocked at segment "
                    f"{self.current_segment} page {self.current_page} "
                    f"— supervisor will restart with fresh Chrome")
            elif os.environ.get("INTERACTIVE_SEARCH") == "1":
                log(f"⚠️ SOFT recovery auto-fill failed after "
                    f"{FILL_MAX_ATTEMPTS} attempts (API path unavailable) "
                    f"— operator fallback", "WARNING")
                # Email the operator BEFORE printing the prompt — log gets
                # updated by the prompt line so hang_watcher won't catch
                # this. This IS the "crawl needs human" moment.
                self._notify_operator_prompt(
                    "operator_prompt",
                    f"SOFT recovery: form fill failed {FILL_MAX_ATTEMPTS}× "
                    f"(API path unavailable, driver alive)")
                print("\n" + "=" * 66)
                print("[!] SOFT RECOVERY -- re-fill the search form in the browser:")
                print(f"   Country={config.DETAIL_COUNTRY}, Type={config.DETAIL_DATA_TYPE}")
                print(f"   Start={config.DETAIL_START_DATE}, "
                      f"End={self.segment_end_date or config.DETAIL_END_DATE}")
                print(f"   HS={config.DETAIL_HS_CODE}")
                print("   Bấm Search, đợi bảng hiện, rồi Enter ở đây.")
                print("=" * 66)
                try:
                    input("   [Press Enter once results table has loaded] > ")
                except EOFError:
                    time.sleep(30)
                api_client.wait_for_loading_overlay(self.driver, timeout=30)
                time.sleep(1)
            else:
                log(f"❌ Failed to re-fill search form after "
                    f"{FILL_MAX_ATTEMPTS} attempts in SOFT recovery", "ERROR")
                log("⬆️ Escalating to DEEP recovery...", "WARNING")
                return self.perform_deep_recovery(batch_config=batch_config)

            # Navigate back to self.current_page (direct jump). Skip in
            # API-only mode — pagination happens via API params, not UI.
            if (self.current_page > 1
                    and not self._api_only_until_segment_end):
                log(f"⏭️  Recovery: Jumping back to page {self.current_page}...", "INFO")
                if not self.go_to_page(self.current_page):
                    log(f"❌ Failed to reach page {self.current_page} during SOFT recovery", "ERROR")
                    log("⬆️ Escalating to DEEP recovery...", "WARNING")
                    return self.perform_deep_recovery(batch_config=batch_config)

            log("✅ SOFT recovery complete", "SUCCESS")
            self._refresh_http_cookies()
            return True

        except Exception as e:
            log(f"❌ SOFT recovery failed: {e}", "ERROR")
            log("⬆️ Escalating to DEEP recovery...", "WARNING")
            return self.perform_deep_recovery(batch_config=batch_config)

    def perform_deep_recovery(self, batch_config=None):
        """
        Perform DEEP recovery: Close browser, create new session, re-login, navigate back.
        Used when WebDriver connection is broken or session expired.
        
        Returns:
            bool: True if recovery successful
        """
        try:
            log("🔄 Performing DEEP recovery (Full Browser Restart)...", "PROCESS")
            
            # Save current state
            saved_segment = self.current_segment
            saved_page = self.current_page
            saved_stt = self.current_stt
            saved_end_date = self.segment_end_date
            saved_total_scraped = self.total_scraped
            
            log(f"💾 Saving state: Segment {saved_segment}, Page {saved_page}, STT {saved_stt}", "INFO")
            if saved_end_date:
                log(f"💾 Segment end date: {saved_end_date}", "INFO")
            
            # Try to close old browser gracefully
            try:
                self.driver.quit()
                log("🔒 Old browser closed", "INFO")
            except:
                log("⚠️ Could not close old browser (may already be crashed)", "WARNING")
            
            # Khử Zombie
            try:
                from src.driver_setup import force_kill_chrome
                force_kill_chrome()
                log("🧹 Cleaned up orphan chromedriver processes", "DEBUG")
            except: pass
            
            time.sleep(3)  # Wait for browser to fully close
            
            # Create new browser
            log("🌐 Starting new browser...", "PROCESS")
            try:
                from ..driver_setup import get_driver
            except ImportError:
                from src.driver_setup import get_driver
            
            from selenium.webdriver.support.ui import WebDriverWait
            
            new_driver = get_driver(headless=False)
            new_wait = WebDriverWait(new_driver, 30)

            # Update self references + every composed component that holds
            # a reference to the OLD driver. Without this, DetailCapture
            # keeps hitting the dead driver's CDP endpoint (port refused)
            # after deep recovery.
            self.driver = new_driver
            self.wait = new_wait
            try:
                self._detail_capture.driver = new_driver
            except Exception:
                pass
            # http client (fast api mode) cookie bridge also binds to driver;
            # force a token refresh on first use instead of holding stale.
            self._http_client = None
            try:
                new_driver.execute_cdp_cmd('Network.enable', {})
            except Exception:
                pass
            
            # Perform PRO login directly
            log("🔐 Re-logging in to Pro...", "PROCESS")
            try:
                # Navigate to Direct Pro Login
                pro_login_url = getattr(config, 'PRO_LOGIN_URL', "https://pro.52wmb.com/user/login?redirect=%2FWorkbenches")
                log(f"📍 Navigating to Pro Login: {pro_login_url}", "INFO")
                try:
                    self.driver.get(pro_login_url)
                except Exception as get_err:
                    log(f"❌ Pro Login Navigation Failed (Socket Die?): {get_err}", "ERROR")
                    return False
                time.sleep(3)
                
                if "/Workbenches" not in self.driver.current_url:
                    from selenium.webdriver.common.by import By
                    from selenium.webdriver.support import expected_conditions as EC
                    
                    slow_wait = WebDriverWait(self.driver, 60)
                    user_field = None
                    for attempt in range(3):
                        try:
                            user_field = slow_wait.until(EC.element_to_be_clickable((By.ID, "username")))
                            break
                        except Exception:
                            log(f"White screen / login form not ready (attempt {attempt+1}/3). Retrying...", "WARNING")
                            try:
                                self.driver.refresh()
                                time.sleep(5)
                            except: pass
                    
                    if not user_field:
                        raise Exception("Login form never appeared after 3 refreshes (White screen of death)")
                        
                    self.driver.execute_script("""
                        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(arguments[0], arguments[1]);
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    """, user_field, config.USERNAME)
                    
                    pass_field = slow_wait.until(EC.element_to_be_clickable((By.ID, "password")))
                    self.driver.execute_script("""
                        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        nativeInputValueSetter.call(arguments[0], arguments[1]);
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                    """, pass_field, config.PASSWORD)
                    
                    log("Submitting login form...", "PROCESS")
                    submit_btn = slow_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".login-button")))
                    self.driver.execute_script("arguments[0].click();", submit_btn) # JS Click
                    
                    log("Waiting for authentication success...", "INFO")
                    slow_wait.until(EC.url_contains("/Workbenches"))
                
                log("✅ Login successful (Landed on Workbenches)", "SUCCESS")
                api_client.handle_popup(self.driver, self.wait, timeout=3)
            except Exception as e:
                log(f"❌ Login failed in DEEP recovery: {e}", "ERROR")
                return False
            
            # Navigate to Customs Data
            log("📍 Navigating to Customs Data...", "PROCESS")
            if not navigator_pro.navigate_from_home_pro(self.driver, self.wait, pro_mode="detail"):
                log("❌ Navigation failed in DEEP recovery", "ERROR")
                return False
            
            log("✅ Navigated to Customs Data", "SUCCESS")
            
            # Close any popups
            self.close_tips_modal()
            
            # API-FIRST: same as SOFT recovery — try API list path before
            # wasting minutes on UI form fill. Skip if state=40 cold-API
            # already observed (would loop infinitely).
            api_fallback_used = False
            cold_disabled = getattr(self, "_fast_api_detail_cold_disabled", False)
            if (self._fast_api_enabled
                    and self._ensure_http_client()
                    and not cold_disabled):
                log("📡 DEEP recovery: trying API-direct list path FIRST...",
                    "PROCESS")
                try:
                    self._refresh_http_cookies()
                    probe = self._fetch_list_via_api(
                        end_date=saved_end_date,
                        page_num=max(1, saved_page - 1))
                    if probe is not None:
                        log("✅ API list path works — skipping UI fill",
                            "SUCCESS")
                        self._api_only_until_segment_end = True
                        api_fallback_used = True
                except Exception as e:
                    log(f"⚠️ API probe raised (will fall back to UI): {e}",
                        "WARNING")

            # If API didn't work, fall back to UI form fill (reduced retries).
            FILL_RETRY_WAITS = [10, 60]  # 2 retries (= 3 attempts) for UI fallback
            FILL_MAX_ATTEMPTS = len(FILL_RETRY_WAITS) + 1
            fill_ok = api_fallback_used  # if API worked, skip UI loop
            if api_fallback_used:
                log("✅ API path active — skipping UI fill loop", "INFO")
            else:
                log("📝 Re-filling search form (UI fallback)...", "PROCESS")
            for fill_attempt in range(1, FILL_MAX_ATTEMPTS + 1):
                if fill_ok:
                    break  # skip when API already succeeded
                log(f"📝 DEEP recovery fill attempt {fill_attempt}/"
                    f"{FILL_MAX_ATTEMPTS}", "PROCESS")
                if navigator_pro.fill_search_form_detail(
                    self.driver, self.wait,
                    end_date_override=saved_end_date,
                    batch_config=batch_config,
                ):
                    navigator_pro.click_search_button_detail(
                        self.driver, self.wait)
                    time.sleep(2)
                    fill_ok = True
                    break

                if fill_attempt < FILL_MAX_ATTEMPTS:
                    wait_s = FILL_RETRY_WAITS[fill_attempt - 1]
                    log(f"⚠️ Fill attempt {fill_attempt} failed — "
                        f"network probe + refresh + retry in {wait_s}s",
                        "WARNING")
                    self._probe_network_and_log()
                    try:
                        self.driver.refresh()
                    except Exception as ref_err:
                        log(f"⚠️ Refresh error (non-fatal): {ref_err}",
                            "WARNING")
                    time.sleep(wait_s)
                    try:
                        self.close_tips_modal()
                    except Exception:
                        pass
                    try:
                        api_client.wait_for_loading_overlay(
                            self.driver, timeout=15)
                    except Exception:
                        pass

            if fill_ok:
                self._api_only_until_segment_end = False
            elif (self._fast_api_enabled
                    and self._ensure_http_client()
                    and not getattr(self, "_fast_api_detail_cold_disabled", False)):
                # UI form fill broken AND state=40 NOT yet observed —
                # try api-only mode (it might work). If cold_disabled is
                # already set, skip this branch (would infinite-loop:
                # api-only → state=40 → SOFT recovery → UI broken → ...)
                log(f"⚠️ UI form fill failed {FILL_MAX_ATTEMPTS}× in DEEP "
                    f"recovery — switching to API-direct list path",
                    "WARNING")
                self._api_only_until_segment_end = True
                self._refresh_http_cookies()
                api_fallback_used = True
            elif self._is_driver_dead():
                raise RuntimeError(
                    "WebDriver session dead during DEEP recovery — "
                    "supervisor will restart with fresh Chrome.")
            elif getattr(self, "_fast_api_detail_cold_disabled", False):
                # DEEP recovery already restarted Chrome but form still
                # broken AND api-only blocked. Last resort: raise to
                # force supervisor-level restart (fully kills python
                # process, fresh Chrome, fresh state).
                log(f"❌ DEEP recovery UI fill failed AND api-only blocked "
                    f"(cold-API state=40). Raising for supervisor restart.",
                    "ERROR")
                raise RuntimeError(
                    f"DEEP recovery exhausted at segment "
                    f"{self.current_segment}: UI form stuck + state=40")
            elif os.environ.get("INTERACTIVE_SEARCH") == "1":
                log(f"⚠️ DEEP recovery auto-fill failed after "
                    f"{FILL_MAX_ATTEMPTS} attempts (API path unavailable) "
                    f"— operator fallback", "WARNING")
                self._notify_operator_prompt(
                    "operator_prompt",
                    f"DEEP recovery: form fill failed {FILL_MAX_ATTEMPTS}× "
                    f"(API path unavailable, driver alive)")
                print("\n" + "=" * 66)
                print("[!] DEEP RECOVERY -- re-fill the search form in the browser:")
                print(f"   Country={config.DETAIL_COUNTRY}, Type={config.DETAIL_DATA_TYPE}")
                print(f"   Start={config.DETAIL_START_DATE}, End={saved_end_date or config.DETAIL_END_DATE}")
                print(f"   HS={config.DETAIL_HS_CODE}")
                print("   Bấm Search, đợi bảng hiện, rồi Enter ở đây.")
                print("=" * 66)
                try:
                    input("   [Press Enter once results table has loaded] > ")
                except EOFError:
                    time.sleep(30)
                api_client.wait_for_loading_overlay(self.driver, timeout=30)
                time.sleep(1)
            else:
                log(f"❌ Failed to fill search form after "
                    f"{FILL_MAX_ATTEMPTS} attempts in DEEP recovery", "ERROR")
                return False

            # Restore state
            self.current_segment = saved_segment
            # Step back 1 page to prevent gaps (overlap is safe, gaps are not)
            resume_page = max(1, saved_page - 1)
            self.current_page = resume_page
            self.current_stt = 1 # Reset STT to 1 since we are restarting the page
            self.segment_end_date = saved_end_date
            self.total_scraped = saved_total_scraped

            # Navigate to resume page (skip in API-only mode — pagination
            # is via API params, not UI clicks)
            if resume_page > 1 and not api_fallback_used:
                log(f"⏭️  Recovery: Jumping to page {resume_page} (Stepped back from {saved_page})...", "INFO")
                if not self.go_to_page(resume_page):
                    log(f"⚠️ Could not reach page {resume_page}, starting from page 1", "WARNING")
                    self.current_page = 1
            
            log(f"✅ DEEP recovery complete! Resuming from Segment {self.current_segment}, Page {self.current_page}", "SUCCESS")
            self._refresh_http_cookies()
            return True

        except Exception as e:
            log(f"❌ DEEP recovery failed: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False


    
    def click_details_and_capture(self, detail_link, row_num, max_retries=3):
        """Delegate to src.extract.detail_capture.DetailCapture.click_and_capture."""
        return self._detail_capture.click_and_capture(detail_link, row_num, max_retries)

    def close_detail_drawer_fast(self):
        """Delegate to DetailCapture.close_drawer."""
        self._detail_capture.close_drawer()

    def capture_detail_response(self, timeout=2):
        """Delegate to DetailCapture._capture (keeps old name for callers)."""
        return self._detail_capture._capture(timeout=timeout)
    
    
    def _get_transaction_id(self, tx):
        """Delegate to src.parsing.transaction.get_transaction_id."""
        return _parsing_get_tx_id(tx)

    def update_mapping_from_server(self, server_titles):
        """Delegate to src.parsing.field_mapping.update_mapping_from_server."""
        _parsing_update_mapping(server_titles, self.ALIASES)

    def has_next_page(self):
        """Delegate to src.nav.pagination.has_next_page."""
        return _nav_pagination.has_next_page(self.driver)

    def go_to_next_page(self, is_recovery=False):
        """Delegate to src.nav.pagination.go_to_next_page."""
        return _nav_pagination.go_to_next_page(self.driver, self.wait, is_recovery)

    
    def initialize_csv(self):
        """Delegate to CsvSink.initialize (creates dir + loads dedupe set)."""
        self._csv_sink.initialize()
        # Keep the class attribute pointing at the same set for any external
        # callers that read self._seen_bill_ids.
        self._seen_bill_ids = self._csv_sink.seen_bill_ids

    def _load_seen_bill_ids(self):
        """Delegate to CsvSink._load_seen_bill_ids."""
        self._csv_sink._load_seen_bill_ids()
        self._seen_bill_ids = self._csv_sink.seen_bill_ids

    def append_to_csv(self, transactions):
        """Delegate to CsvSink.append (dedupe + dynamic header expansion)."""
        self._csv_sink.append(transactions)
    def run_test_scraping_sequence(self, batch_config=None):
        """
        Executes the test scraping sequence to validate performance and logic.
        """
        log("\n" + "="*60, "INFO")
        log("🧪 TEST MODE: EXECUTION START", "INFO")
        log("="*60 + "\n", "INFO")
        
        results = {
            "login": True, # If we got here, login passed
            "navigation": True, # Navigation passed
            "form_fill": False,
            "page_1_seg_1": False,
            "page_jump": False,
            "page_333_seg_1": False,
            "boundary_detection": False,
            "segment_shift": False,
            "page_1_seg_2": False
        }
        
        timings = {}
        boundary_date = None
        
        # 1. Prepare search results (Test: Form Fill)
        try:
            log("🧪 Test: Form Fill & Search", "PROCESS")
            if not self.prepare_search_results(batch_config, strict_validation=False):
                raise Exception("Failed to fill form or get total records")
            results['form_fill'] = True
            log("   ✅ Form filled and search successful", "SUCCESS")
        except Exception as e:
            log(f"   ❌ Form Fill Failed: {e}", "ERROR")
            self.print_test_report(results, timings)
            return False
            
        # 2. Scrape Page 1, Segment 1
        try:
            log("\n🧪 Test: Scraping Page 1, Segment 1", "PROCESS")
            t_start = time.perf_counter()
            page_data = self.scrape_page(1, 1)
            t_end = time.perf_counter()
            elapsed = t_end - t_start
            
            rows = len(page_data)
            results['page_1_seg_1'] = rows > 0
            timings['page_1_seg_1'] = {"ms": elapsed, "rows": rows}
            
            if rows > 0:
                log(f"   ✅ Scraped {rows} rows in {elapsed:.2f}s ({rows/elapsed:.1f} rows/s)", "SUCCESS")
                # Save to output file so data is persisted for inspection
                self.append_to_csv(page_data)
                self.total_scraped += rows
            else:
                log("   ❌ Failed: No rows returned", "ERROR")
        except Exception as e:
            log(f"   ❌ Scrape Page 1 Failed: {e}", "ERROR")
            
        # 3. Jump to Page 333
        if results['page_1_seg_1']:
            try:
                log("\n🧪 Test: Jumping to Page 333", "PROCESS")
                t_start = time.perf_counter()
                if not self.go_to_page(333):
                    raise Exception("go_to_page returned False")
                t_end = time.perf_counter()
                elapsed = t_end - t_start
                
                results['page_jump'] = True
                timings['page_jump'] = {"ms": elapsed}
                log(f"   ✅ Jumped to page 333 in {elapsed:.2f}s", "SUCCESS")
            except Exception as e:
                log(f"   ❌ Page Jump Failed: {e}", "ERROR")
            
        # 4. Scrape Page 333
        if results.get('page_jump'):
            try:
                log("\n🧪 Test: Scraping Page 333, Segment 1", "PROCESS")
                t_start = time.perf_counter()
                page_data = self.scrape_page(333, 1)
                t_end = time.perf_counter()
                elapsed = t_end - t_start
                
                rows = len(page_data)
                results['page_333_seg_1'] = rows > 0
                timings['page_333_seg_1'] = {"ms": elapsed, "rows": rows}
                
                if rows > 0:
                    log(f"   ✅ Scraped {rows} rows in {elapsed:.2f}s", "SUCCESS")
                    # Save to output file
                    self.append_to_csv(page_data)
                    self.total_scraped += rows
                    
                    # Boundary detection
                    last_tx = page_data[-1]
                    boundary_date = self._extract_transaction_date(last_tx)
                    if boundary_date:
                        results['boundary_detection'] = True
                        timings['boundary_date'] = boundary_date
                        log(f"   📅 Boundary Date found: {boundary_date}", "INFO")
                    else:
                        log("   ❌ Boundary Date NOT found", "ERROR")
                else:
                    log("   ❌ Failed: No rows returned", "ERROR")
            except Exception as e:
                log(f"   ❌ Scrape Page 333 Failed: {e}", "ERROR")
                
        # 5. Segment Shift
        if results.get('boundary_detection') and boundary_date:
            try:
                log("\n🧪 Test: Segment Shift", "PROCESS")
                t_start = time.perf_counter()
                
                self.current_segment = 2
                self.segment_end_date = boundary_date
                
                navigator_pro.clear_search_form_detail(self.driver, self.wait)
                # Need to use prepare_search_results again which will use self.segment_end_date
                success = self.prepare_search_results(batch_config, strict_validation=False)
                
                t_end = time.perf_counter()
                elapsed = t_end - t_start
                
                results['segment_shift'] = success
                timings['segment_shift'] = {"ms": elapsed}
                
                if success:
                    log(f"   ✅ Segment shift completed in {elapsed:.2f}s", "SUCCESS")
                else:
                    log("   ❌ Segment shift setup failed", "ERROR")
                    
            except Exception as e:
                log(f"   ❌ Segment Shift Failed: {e}", "ERROR")
                
        # 6. Scrape Page 1, Segment 2
        if results.get('segment_shift'):
            try:
                log("\n🧪 Test: Scraping Page 1, Segment 2", "PROCESS")
                t_start = time.perf_counter()
                page_data = self.scrape_page(1, 2)
                t_end = time.perf_counter()
                elapsed = t_end - t_start
                
                rows = len(page_data)
                results['page_1_seg_2'] = rows > 0
                timings['page_1_seg_2'] = {"ms": elapsed, "rows": rows}
                
                if rows > 0:
                    log(f"   ✅ Scraped {rows} rows in {elapsed:.2f}s", "SUCCESS")
                    # Save to output file
                    self.append_to_csv(page_data)
                    self.total_scraped += rows
                else:
                    log("   ❌ Failed: No rows returned", "ERROR")
            except Exception as e:
                log(f"   ❌ Scrape Page 1 Seg 2 Failed: {e}", "ERROR")

        # Report
        self.print_test_report(results, timings)
        return all(results.values())

    def print_test_report(self, results, timings):
        """Prints the final test report."""
        log("\n" + "="*80, "INFO")
        log("🧪 TEST MODE REPORT", "INFO")
        log("="*80, "INFO")
        
        # A. Logic Tests
        log("\n--- A. Logic & Stability ---", "INFO")
        for k, v in results.items():
            icon = "✅" if v else "❌"
            if k == 'boundary_detection' and 'boundary_date' in timings:
                log(f" {icon}  {k.replace('_', ' ').title()}: Passed (📅 {timings['boundary_date']})", "INFO")
            else:
                log(f" {icon}  {k.replace('_', ' ').title()}: {'Passed' if v else 'Failed'}", "INFO")
        
        # B. Performance
        log("\n--- B. Performance Benchmarks ---", "INFO")
        speed_stats = []
        for process, metrics in timings.items():
            if process == 'boundary_date':
                continue
            if 'rows' in metrics:
                ms = metrics['ms']
                r = metrics['rows']
                speed = r / ms if ms > 0 else 0
                speed_stats.append(speed)
                log(f" 📄 {process.replace('_', ' ').title():<18}: {ms:>5.2f}s | {r:>2} rows | ⚡ {speed:>5.1f} rows/s", "INFO")
            else:
                ms = metrics['ms']
                log(f" ⏩ {process.replace('_', ' ').title():<18}: {ms:>5.2f}s", "INFO")
                
        # C. Summary
        total_tests = len(results)
        passed = sum(1 for v in results.values() if v)
        log("\n--- C. Summary ---", "INFO")
        log(f" 📊 Tests: {passed}/{total_tests} passed", "INFO")
        if speed_stats:
            avg_speed = sum(speed_stats) / len(speed_stats)
            estimated_hourly = int(avg_speed * 3600)
            log(f" ⚡ Avg Speed: {avg_speed:.1f} rows/sec", "INFO")
            log(f" 🕒 Estimated hourly rate: ~{estimated_hourly:,} rows/hour", "INFO")
            
        log("="*80 + "\n", "INFO")


    def convert_to_excel(self):
        """Delegate to src.storage.excel_sink.convert_to_excel."""
        _storage_convert_to_excel(self.csv_file, self.excel_file)

    def _write_status(self, page_num, total_scraped, segment_num, segment_start, segment_end, extra=None):
        """Write live progress to data/status.json for the management tool to poll."""
        import json as _json
        status = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "account": getattr(config, "USERNAME", "unknown"),
            "batch": getattr(self, "batch_name", ""),
            "segment": segment_num,
            "segment_start": str(segment_start),
            "segment_end": str(segment_end),
            "page": page_num,
            "total_scraped": total_scraped,
            "state": "running",
        }
        if extra:
            status.update(extra)
        try:
            base_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            status_path = os.path.join(base_dir, "data", "status.json")
            os.makedirs(os.path.dirname(status_path), exist_ok=True)
            with open(status_path, "w", encoding="utf-8") as _f:
                _json.dump(status, _f, ensure_ascii=False)
        except Exception:
            pass  # status.json is best-effort — never crash crawl for it

    _SEGMENT_VERIFY_THRESHOLD = 0.95

    def _verify_segment(self, segment_num, segment_start, segment_end, expected):
        """Count CSV rows in date range and compare to website total.

        Returns True if count >= 95% of expected. Logs WARNING if below.
        Never raises — verification is best-effort and must not abort crawl.
        """
        if not expected or expected <= 0 or expected >= 900000:
            return True  # no usable baseline (0, unknown, or sentinel 999999)
        try:
            import csv as _csv
            count = 0
            seg_start_str = str(segment_start)
            seg_end_str = str(segment_end)
            with open(self.csv_file, encoding="utf-8", newline="") as _fh:
                reader = _csv.DictReader(_fh)
                date_col = next(
                    (c for c in (reader.fieldnames or []) if "ngay" in c.lower() or "date" in c.lower()),
                    None,
                )
                if not date_col:
                    return True
                for row in reader:
                    val = row.get(date_col, "")
                    if seg_start_str <= val <= seg_end_str:
                        count += 1
        except Exception as ex:
            log(f"Segment verify: could not count CSV rows: {ex}", "WARNING")
            return True
        ratio = count / expected
        if ratio < self._SEGMENT_VERIFY_THRESHOLD:
            log(
                f"SEGMENT VERIFY FAILED: seg {segment_num} "
                f"({segment_start} to {segment_end}) "
                f"got {count:,}/{expected:,} rows ({ratio:.1%}) — below 95%",
                "WARNING",
            )
            return False
        log(
            f"Segment verify OK: {count:,}/{expected:,} rows ({ratio:.1%})",
            "INFO",
        )
        return True

    _RETRY_BACKOFF = [5, 15, 45]

    def _retry_failed_rows(self):
        """Retry JSONL entries from data/failed/ with exponential backoff.

        Overwrites the JSONL file with only the entries that still failed.
        """
        import glob as _glob
        import json as _json
        import time as _time
        try:
            base_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            failed_dir = os.path.join(base_dir, "data", "failed")
            if not os.path.isdir(failed_dir):
                return
            for fpath in _glob.glob(os.path.join(failed_dir, "failed_rows_*.jsonl")):
                try:
                    with open(fpath, encoding="utf-8") as _fh:
                        entries = [_json.loads(line) for line in _fh if line.strip()]
                except Exception:
                    continue
                if not entries:
                    continue
                log(f"Retrying {len(entries)} failed rows from {os.path.basename(fpath)}", "INFO")
                still_failed = []
                for entry in entries:
                    success = False
                    for delay in self._RETRY_BACKOFF:
                        try:
                            # _fetch_one_detail is the method that fetches a single row detail.
                            # Adjust the method name to match what exists in this class.
                            if hasattr(self, '_fetch_one_detail'):
                                result = self._fetch_one_detail(entry)
                            elif hasattr(self, 'fetch_detail'):
                                result = self.fetch_detail(entry)
                            else:
                                result = None
                            if result:
                                success = True
                                break
                        except Exception as _ex:
                            log(f"Retry attempt failed: {_ex}", "WARNING")
                        _time.sleep(delay)
                    if not success:
                        still_failed.append(entry)
                with open(fpath, "w", encoding="utf-8") as _fh:
                    for e in still_failed:
                        _fh.write(_json.dumps(e, ensure_ascii=False) + "\n")
                recovered = len(entries) - len(still_failed)
                log(f"Retry result: {recovered}/{len(entries)} recovered", "INFO")
        except Exception as _ex:
            log(f"_retry_failed_rows error: {_ex}", "WARNING")


def _wait_for_login_outcome(driver, timeout=30, poll_interval=2):
    """Fast-poll the login result. Replaces a single 60s
    WebDriverWait(url_contains '/Workbenches') with a tight loop that
    exits on the first definitive signal:

    Returns one of:
      "success"      — URL changed to /Workbenches (logged in)
      "captcha"      — CAPTCHA challenge appeared (account flagged)
      "error:<msg>"  — Ant error toast visible (wrong password,
                       account locked, server error, etc)
      "stuck"        — timeout, URL still on /login (unknown failure)

    Without this, every failed login burned 60s waiting for a URL
    change that would never happen. Across 5 attempts that's ~5min
    of dead time; with poll-based checks we exit within ~2-4s of the
    server giving us its response.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            cur = driver.current_url
        except Exception:
            cur = ""

        # Definitive success
        if "/Workbenches" in cur or "/workbenches" in cur:
            return "success"

        # Captcha indicators (any visible captcha-related element)
        try:
            captcha_selectors = [
                "img[src*='captcha']",
                "iframe[src*='captcha']",
                ".captcha",
                ".verify-bar",        # slider verify common on Chinese sites
                ".verify-wrap",
                "[class*='Captcha']",
            ]
            for sel in captcha_selectors:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        return "captcha"
                except Exception:
                    continue
        except Exception:
            pass

        # Ant error toast — usually appears within 1-3s of submit
        # when the server rejects the credentials.
        try:
            for sel in (".ant-message-error",
                        ".ant-message-warning",
                        ".ant-notification-notice-error"):
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        msg = (el.text or "").strip()[:200]
                        if msg:
                            return f"error:{msg}"
                        return "error:unspecified server error"
                except Exception:
                    continue
        except Exception:
            pass

        time.sleep(poll_interval)

    # Timed out — URL still on login page or somewhere else unexpected.
    try:
        cur = driver.current_url
    except Exception:
        cur = "?"
    if "/login" in cur:
        return "stuck"
    return f"unknown:{cur}"


def main_pro_detail():
    """Main entry point for Detail Mode."""
    try:
        log("\n" + "="*60, "PROCESS")
        log("🚀 PRO 2026 DETAIL MODE SCRAPER", "PROCESS")
        log("="*60 + "\n", "PROCESS")
        
        try:
            from ..driver_setup import get_driver
        except ImportError:
            from src.driver_setup import get_driver
        
        from selenium.webdriver.support.ui import WebDriverWait
        
        # PRE-START: Generate filename and detect resume point immediately
        csv_file = ScraperProDetail.generate_output_filename()
        excel_file = csv_file.replace('.csv', '.xlsx')
        
        log(f"📁 CSV Output: {csv_file}", "INFO")
        log(f"📁 Excel Output: {excel_file}", "INFO")
        
        # Detect resume point BEFORE starting driver (now returns 6 values)
        current_segment, current_page, current_stt, total_scraped, segment_end_date, last_scraped_date = ScraperProDetail.detect_resume_point(csv_file)
        
        # Initialize driver
        driver = get_driver(headless=False)
        wait = WebDriverWait(driver, 20)
        
        # Login logic (Direct Pro Login) — wrapped in retry loop. Each
        # attempt navigates fresh to /user/login and re-fills creds. If
        # all attempts exhausted: raise so run.py exits non-zero and
        # supervisor restarts (instead of swallowing → exit 0 → loop
        # stops thinking we succeeded).
        pro_login_url = getattr(config, 'PRO_LOGIN_URL',
            "https://pro.52wmb.com/user/login?redirect=%2FWorkbenches")
        LOGIN_MAX_ATTEMPTS = 5
        LOGIN_COOLDOWN = 15
        login_success = False

        for login_attempt in range(1, LOGIN_MAX_ATTEMPTS + 1):
            log(f"🔐 Login attempt {login_attempt}/{LOGIN_MAX_ATTEMPTS}",
                "PROCESS")
            try:
                log(f"📍 Navigating to Pro Login: {pro_login_url}", "INFO")
                driver.get(pro_login_url)
                time.sleep(3)

                if "/Workbenches" in driver.current_url:
                    log("✅ Already logged in (Redirected to Workbenches)",
                        "SUCCESS")
                    login_success = True
                    break

                log("Filling credentials...", "INFO")
                slow_wait = WebDriverWait(driver, 60)

                user_field = None
                for refresh_attempt in range(3):
                    try:
                        user_field = slow_wait.until(
                            EC.element_to_be_clickable((By.ID, "username")))
                        break
                    except Exception:
                        log(f"White screen / login form not ready (refresh {refresh_attempt+1}/3). Retrying...",
                            "WARNING")
                        try:
                            driver.refresh()
                            time.sleep(5)
                        except Exception:
                            pass

                if not user_field:
                    raise Exception(
                        "Login form never appeared after 3 refreshes "
                        "(White screen of death)")

                # React native setter — atomic value write, avoids the
                # send_keys race where a controlled input rejects partial
                # characters as you type. Less bot-fingerprinted too.
                _react_set = (
                    "var el=arguments[0],v=arguments[1];"
                    "el.focus();"
                    "var setter=Object.getOwnPropertyDescriptor("
                    "  window.HTMLInputElement.prototype,'value').set;"
                    "setter.call(el,v);"
                    "el.dispatchEvent(new Event('input',{bubbles:true}));"
                    "el.dispatchEvent(new Event('change',{bubbles:true}));"
                )
                user_field.click()
                time.sleep(0.3)
                user_field.clear()
                time.sleep(0.2)
                try:
                    driver.execute_script(_react_set, user_field, config.USERNAME)
                except Exception:
                    user_field.send_keys(config.USERNAME)  # fallback
                time.sleep(0.5)

                pass_field = slow_wait.until(
                    EC.element_to_be_clickable((By.ID, "password")))
                pass_field.click()
                time.sleep(0.3)
                pass_field.clear()
                time.sleep(0.2)
                try:
                    driver.execute_script(_react_set, pass_field, config.PASSWORD)
                except Exception:
                    pass_field.send_keys(config.PASSWORD)  # fallback
                time.sleep(0.8)

                log("Submitting login form...", "PROCESS")
                submit_btn = slow_wait.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".login-button")))
                try:
                    submit_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", submit_btn)
                time.sleep(1)

                log("Waiting for authentication success...", "INFO")
                # Fast-poll login outcome (was: 60s blind wait). Saves
                # 5+ minutes total when login fails — checks every 2s
                # and exits early on either success URL or error toast.
                outcome = _wait_for_login_outcome(driver, timeout=30)
                if outcome == "success":
                    log("✅ Login successful (Landed on Workbenches)", "SUCCESS")
                    login_success = True
                    break
                elif outcome == "captcha":
                    log(f"❌ Login attempt {login_attempt}: CAPTCHA detected. "
                        f"Account likely flagged — manual login required.",
                        "ERROR")
                    # acc6: cooldown + rotate session-id. Brightdata cấp pool
                    # IP residential khác nhau cho session-id khác nhau, nên
                    # cycle session-id có cơ hội thoát zone bị block. Cooldown
                    # cho server quên fingerprint cũ. Selenium chỉ thực sự
                    # đổi IP khi restart Chrome (caller có thể restart sau N
                    # lần captcha liên tiếp).
                    try:
                        from ..core.proxy_rotator import get_rotator
                        get_rotator().cooldown_on_block(reason="captcha_login")
                    except Exception:
                        pass
                elif outcome.startswith("error:"):
                    log(f"❌ Login attempt {login_attempt} server-side error: "
                        f"{outcome[6:]}", "ERROR")
                elif outcome == "stuck":
                    log(f"❌ Login attempt {login_attempt} stuck on login "
                        f"page (URL: {driver.current_url})", "ERROR")
                else:
                    log(f"❌ Login attempt {login_attempt} unexpected outcome "
                        f"'{outcome}' (URL: {driver.current_url})", "ERROR")
            except Exception as e:
                err_msg = str(e)
                log(f"❌ Login attempt {login_attempt} error: {err_msg[:200]}",
                    "ERROR")
                # If chromedriver session is dead (Chrome closed / crashed
                # before login completed), all subsequent retries reuse
                # the same dead session and fail identically. Break out
                # immediately and raise so supervisor restarts python with
                # a fresh Chrome — no point burning 4 more retries × 15s.
                dead_markers = (
                    "no such window", "invalid session id",
                    "session deleted", "chrome not reachable",
                    "session not created", "web view not found",
                    "tab crashed",
                )
                if any(m in err_msg.lower() for m in dead_markers):
                    log("💀 Chromedriver session is dead — aborting login "
                        "retries. Raising so supervisor restarts python "
                        "with a fresh Chrome.", "ERROR")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"Chromedriver session died at login attempt "
                        f"{login_attempt}: {err_msg[:120]}")

            if login_attempt < LOGIN_MAX_ATTEMPTS:
                log(f"⏳ Waiting {LOGIN_COOLDOWN}s before login retry...",
                    "INFO")
                time.sleep(LOGIN_COOLDOWN)

        if not login_success:
            log(f"❌ Login failed after {LOGIN_MAX_ATTEMPTS} attempts. "
                f"Raising so supervisor restarts.", "ERROR")
            try:
                driver.quit()
            except Exception:
                pass
            raise RuntimeError(
                f"Login failed after {LOGIN_MAX_ATTEMPTS} attempts")

        # Post-login popup handling
        try:
            api_client.handle_popup(driver, wait, timeout=3)
        except Exception as e:
            log(f"⚠️ Post-login popup handler error (non-fatal): {e}",
                "WARNING")
        
        # Navigate to Customs Data (Simplified Check)
        log("📍 Navigating to Customs Data...", "PROCESS")
        if not navigator_pro.navigate_from_home_pro(driver, wait, pro_mode="detail"):
            log("❌ Navigation failed", "ERROR")
            driver.quit()
            return False
        
        # Create scraper instance with pre-detected info
        scraper = ScraperProDetail(driver, wait, csv_file=csv_file)
        scraper.current_segment = current_segment
        scraper.current_page = current_page
        scraper.current_stt = current_stt
        scraper.total_scraped = total_scraped
        scraper.segment_end_date = segment_end_date  # Pass segment boundary date
        scraper.last_scraped_date = last_scraped_date
        
        # Close Tips modal if it appears after navigation
        scraper.close_tips_modal()
        
        # Start scraping with retry logic
        MAX_RETRIES = 3
        success = False
        
        for retry_attempt in range(MAX_RETRIES):
            try:
                if retry_attempt > 0:
                    log(f"🔄 Retry attempt {retry_attempt + 1}/{MAX_RETRIES}...", "WARNING")
                    
                    # Re-detect resume point (in case partial progress was made)
                    current_segment, current_page, current_stt, total_scraped, segment_end_date, _last_scraped_date = ScraperProDetail.detect_resume_point(csv_file)
                    
                    # Update scraper state
                    scraper.current_segment = current_segment
                    scraper.current_page = current_page
                    scraper.current_stt = current_stt
                    scraper.total_scraped = total_scraped
                    scraper.segment_end_date = segment_end_date
                    
                    # Deep alive-check: current_url alone is not enough — it
                    # can return a cached value while chromedriver's port is
                    # already refused (seen after a DEEP-recovery raise that
                    # tore down chromedriver mid-flight). execute_script
                    # forces a CDP roundtrip so a dead port surfaces here
                    # instead of inside form fill / country select 30s later.
                    browser_alive = False
                    try:
                        _ = scraper.driver.current_url
                        scraper.driver.execute_script("return 1;")
                        browser_alive = True
                    except Exception as alive_err:
                        log(f"⚠️ Browser alive-check failed: {alive_err}",
                            "WARNING")
                    if browser_alive:
                        log("✅ Browser still alive, proceeding with retry...", "INFO")
                        # CRITICAL: Clear form before retry. Use scraper.driver
                        # (not the local `driver` var) — DEEP recovery may have
                        # rebuilt scraper.driver, leaving local `driver` pointing
                        # at the dead chromedriver port. Same for `wait`.
                        try:
                            log("🧹 Clearing form before retry...", "INFO")
                            navigator_pro.clear_search_form_detail(
                                scraper.driver, scraper.wait)
                        except Exception as clear_err:
                            log(f"⚠️ Form clear errored (non-fatal — "
                                f"scrape_detail_transactions will refill): "
                                f"{clear_err}", "WARNING")
                    else:
                        log("⚠️ Browser dead, performing deep recovery...", "WARNING")
                        if not scraper.perform_deep_recovery():
                            log(f"❌ Recovery failed for retry {retry_attempt + 1}", "ERROR")
                            continue
                
                success = scraper.scrape_detail_transactions()
                
                if success:
                    break  # Exit retry loop on success
                else:
                    log(f"⚠️ Scraping returned False (attempt {retry_attempt + 1}/{MAX_RETRIES})", "WARNING")
            
            except KeyboardInterrupt:
                log("\n🛑 User interrupted - exiting gracefully...", "WARNING")
                break  # Exit retry loop immediately
                    
            except Exception as e:
                log(f"❌ Exception (attempt {retry_attempt + 1}/{MAX_RETRIES}): {e}", "ERROR")
                import traceback
                traceback.print_exc()
        
        # ============================================================
        # SESSION STATISTICS
        # ============================================================
        try:
            elapsed_seconds = (datetime.now() - scraper.timer.start_time).total_seconds()
            elapsed_hours = elapsed_seconds / 3600
            
            log(f"\n{'='*60}", "SUCCESS")
            log(f"📊 SESSION STATISTICS", "SUCCESS")
            log(f"{'='*60}", "SUCCESS")
            log(f"⏱️  Total Time: {int(elapsed_seconds//3600)}h {int((elapsed_seconds%3600)//60)}m {int(elapsed_seconds%60)}s", "INFO")
            log(f"📊 Total Scraped: {scraper.total_scraped:,} records", "INFO")
            log(f"📄 Final Position: Segment {scraper.current_segment}, Page {scraper.current_page}", "INFO")
            
            if elapsed_hours > 0:
                records_per_hour = scraper.total_scraped / elapsed_hours
                pages_scraped = ((scraper.current_segment - 1) * scraper.MAX_PAGES_PER_SEGMENT) + scraper.current_page
                pages_per_hour = pages_scraped / elapsed_hours
                log(f"🚀 Speed: {records_per_hour:,.0f} records/hour ({pages_per_hour:.1f} pages/hour)", "INFO")
            
            if scraper.segment_end_date:
                log(f"📅 Segment End Date: {scraper.segment_end_date}", "INFO")
            
            log(f"{'='*60}\n", "SUCCESS")
        except Exception as e:
            log(f"⚠️ Could not calculate statistics: {e}", "WARNING")
        
        # Keep browser open briefly for inspection
        log("🔄 Closing browser in 10 seconds...", "INFO")
        time.sleep(10)
        driver.quit()
        
        return success
    except Exception as e:
        log(f"❌ Main failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        # Email alert with state + traceback (best-effort).
        try:
            import sys, os
            scripts_dir = os.path.join(
                os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__)))),
                "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            import notify  # type: ignore
            scraper_dir = os.path.dirname(scripts_dir)
            log_files = sorted(
                [f for f in os.listdir(os.path.join(scraper_dir, "logs"))
                 if f.startswith("crawl_") and f.endswith(".log")],
                reverse=True,
            )
            log_path = (os.path.join(scraper_dir, "logs", log_files[0])
                        if log_files else "")
            notify.notify_exception(scraper_dir, log_path, exc=e)
        except Exception as ne:
            log(f"⚠️ notify_exception failed (non-fatal): {ne}", "WARNING")
        return False


def main_pro_detail_multi():
    """
    Main entry point for Detail Mode - MULTI/BATCH mode.
    Loops through DETAIL_BATCH configs, running scraper for each.
    Reuses same browser session for all batch items.
    """
    try:
        log("\n" + "="*60, "PROCESS")
        log("🚀 PRO 2026 DETAIL MODE - MULTI/BATCH SCRAPER", "PROCESS")
        log("="*60 + "\n", "PROCESS")
        
        # Use TRANSACTIONS_BATCH directly
        batch_items = getattr(config, 'TRANSACTIONS_BATCH', [])
        log(f"📂 Using TRANSACTIONS batch list ({len(batch_items)} items)", "INFO")

        if not batch_items:
            log(f"❌ Batch list is empty. Check config.py.", "ERROR")
            return False
        
        # ============================================================
        # BATCH RESUME STATUS CHECK
        # Show current progress for each batch item at startup
        # ============================================================
        log(f"📋 Batch items status:", "INFO")
        total_expected = 0
        total_scraped = 0
        items_complete = 0
        items_resume = 0
        items_pending = 0
        
        for i, item in enumerate(batch_items, 1):
            item_name = item.get('name', 'unnamed')
            expected = item.get('expected', 0)
            total_expected += expected
            
            # Generate filename and check progress
            job_prefix = "detail_"
            
            csv_file = os.path.join(
                config.OUTPUT_DIR,
                f"{job_prefix}{config.DETAIL_COUNTRY}_{item_name}.csv"
            )
            
            # Quick check: does file exist and how many records?
            scraped = 0
            if os.path.exists(csv_file):
                try:
                    import pandas as pd
                    df = pd.read_csv(csv_file, encoding='utf-8-sig', nrows=1)
                    scraped = len(pd.read_csv(csv_file, encoding='utf-8-sig'))
                except:
                    scraped = 0
            
            total_scraped += min(scraped, expected)  # Cap at expected
            
            # Determine status
            if scraped >= expected:
                status = "✅ COMPLETE"
                items_complete += 1
            elif scraped > 0:
                status = f"🔄 RESUME ({scraped:,}/{expected:,})"
                items_resume += 1
            else:
                status = "⏸️ PENDING"
                items_pending += 1
            
            log(f"   [{i}] {item_name} - {item.get('data_type', '?')} ({expected:,} records) {status}", "INFO")
        
        # Summary
        log(f"\n📊 Batch Summary:", "INFO")
        log(f"   Total items: {len(batch_items)} ({items_complete} complete, {items_resume} resume, {items_pending} pending)", "INFO")
        log(f"   Total progress: {total_scraped:,}/{total_expected:,} ({(total_scraped/total_expected*100) if total_expected > 0 else 0:.1f}%)", "INFO")
        remaining = total_expected - total_scraped
        if remaining > 0:
            # Estimate time at ~1800 records/hour
            est_hours = remaining / 1800
            log(f"   Remaining: {remaining:,} records (~{int(est_hours)}h {int((est_hours % 1) * 60)}m at 1800/hr)", "INFO")
        log("", "INFO")
        
        try:
            from ..driver_setup import get_driver
        except ImportError:
            from src.driver_setup import get_driver
        
        from selenium.webdriver.support.ui import WebDriverWait
        
        # Initialize driver ONCE for all batch items
        driver = get_driver(headless=False)
        wait = WebDriverWait(driver, 20)
        
        # Login logic (Custom robust implementation for Pro Detail)
        log("🔐 Logging in...", "PROCESS")
        try:
            # 1. Navigate to Direct Pro Login
            pro_login_url = getattr(config, 'PRO_LOGIN_URL', "https://pro.52wmb.com/user/login?redirect=%2FWorkbenches")
            log(f"📍 Navigating to Pro Login: {pro_login_url}", "INFO")
            driver.get(pro_login_url)
            time.sleep(3)
            
            # 2. Check if already logged in (Redirected to Workbenches)
            if "/Workbenches" in driver.current_url:
                log("✅ Already logged in (Redirected to Workbenches)", "SUCCESS")
            else:
                # 3. Fill credentials
                log("Filling credentials...", "INFO")
                
                # Username (ID: username)
                # Use a specific, longer wait for the first element on slow networks
                slow_wait = WebDriverWait(driver, 60)
                
                user_field = None
                for attempt in range(3):
                    try:
                        user_field = slow_wait.until(EC.element_to_be_clickable((By.ID, "username")))
                        break
                    except Exception as wait_err:
                        log(f"White screen / login form not ready (attempt {attempt+1}/3). Retrying...", "WARNING")
                        try:
                            driver.refresh()
                            time.sleep(5)
                        except: pass
                
                if not user_field:
                    raise Exception("Login form never appeared after 3 refreshes (White screen of death)")
                
                # Check actual readiness avoiding react input dropping
                user_field.click()
                time.sleep(0.5)
                user_field.clear()
                time.sleep(0.5)
                user_field.send_keys(config.USERNAME)
                time.sleep(1)
                
                # Password (ID: password)
                pass_field = slow_wait.until(EC.element_to_be_clickable((By.ID, "password")))
                pass_field.click()
                time.sleep(0.5)
                pass_field.clear()
                time.sleep(0.5)
                pass_field.send_keys(config.PASSWORD)
                time.sleep(2)
                
                # 4. Submit (Class: login-button)
                log("Submitting login form...", "PROCESS")
                submit_btn = slow_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".login-button")))
                try:
                    submit_btn.click()
                except:
                    driver.execute_script("arguments[0].click();", submit_btn) # JS Click for safety
                time.sleep(1)
                
                # 5. Wait for success (Redirect to Workbenches)
                log("Waiting for authentication success...", "INFO")
                try:
                    slow_wait.until(EC.url_contains("/Workbenches"))
                    log("✅ Login successful (Landed on Workbenches)", "SUCCESS")
                except:
                    log("⚠️ Login might have failed or verify captcha needed. Checking URL...", "WARNING")
                    if "/login" in driver.current_url:
                        log("❌ Still on login page. Please check credentials or captcha.", "ERROR")
                        driver.quit()
                        return False
                
                # Handle potential post-login popups
                api_client.handle_popup(driver, wait, timeout=3)
                
        except Exception as e:
            log(f"❌ Login error: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            driver.quit()
            return False
        
        # Navigate to Customs Data ONCE
        log("📍 Navigating to Customs Data...", "PROCESS")
        if not navigator_pro.navigate_from_home_pro(driver, wait, pro_mode="detail"):
            log("❌ Navigation failed", "ERROR")
            driver.quit()
            return False
        
        # Process each batch item
        batch_start_time = datetime.now()
        total_records_all = 0
        successful_items = 0
        failed_items = 0
        
        for idx, batch_item in enumerate(batch_items, 1):
            item_name = batch_item.get('name', f'item_{idx}')
            expected = batch_item.get('expected', 0)
            
            log(f"\n{'='*60}", "PROCESS")
            log(f"📋 BATCH ITEM [{idx}/{len(batch_items)}]: {item_name}", "PROCESS")
            log(f"   Data Type: {batch_item.get('data_type', 'N/A')}", "INFO")
            log(f"   Buyer: {batch_item.get('buyer', '') or 'N/A'}", "INFO")
            log(f"   Supplier: {batch_item.get('supplier', '') or 'N/A'}", "INFO")
            log(f"   Expected: {expected:,} records", "INFO")
            log(f"{'='*60}\n", "PROCESS")
            
            # Generate filename for this batch item
            job_prefix = "detail_"
            if getattr(config, 'TEST_MODE', False):
                job_prefix = "test_" + job_prefix
            
            csv_file = os.path.join(
                config.OUTPUT_DIR,
                f"{job_prefix}{config.DETAIL_COUNTRY}_{item_name}.csv"
            )
            excel_file = csv_file.replace('.csv', '.xlsx')
            
            log(f"📁 Output: {csv_file}", "INFO")
            
            # Clear form before each new search (except first)
            if idx > 1:
                try:
                    log("🔄 Clearing search form...", "INFO")
                    navigator_pro.clear_search_form_detail(driver, wait)
                except Exception as e:
                    log(f"⚠️ Clear form failed, checking browser: {e}", "WARNING")
                    # Browser might have crashed, check if alive
                    try:
                        _ = driver.current_url
                    except:
                        # Browser dead, perform deep recovery
                        log("🔄 Browser crashed, performing deep recovery...", "WARNING")
                        try:
                            # Create temp scraper for recovery
                            temp_scraper = ScraperProDetail(driver, wait, csv_file=csv_file)
                            temp_scraper.batch_config = batch_item
                            
                            if temp_scraper.perform_deep_recovery(batch_config=batch_item):
                                # Update driver/wait references after recovery
                                driver = temp_scraper.driver
                                wait = temp_scraper.wait
                                log("✅ Deep recovery successful", "SUCCESS")
                            else:
                                log("❌ Deep recovery failed, skipping item", "ERROR")
                                failed_items += 1
                                continue
                        except Exception as recovery_error:
                            log(f"❌ Recovery error: {recovery_error}", "ERROR")
                            failed_items.append(item_name)
                            continue
            
            # Detect resume point for this file
            current_segment, current_page, current_stt, total_scraped, segment_end_date, last_scraped_date = ScraperProDetail.detect_resume_point(csv_file)
            
            # Check if already complete
            # Check if transactions are already complete
            detail_action = getattr(config, 'DETAIL_ACTION', 'transactions')
            
            if total_scraped >= expected:
                if detail_action == 'transactions':
                    log(f"✅ Already complete: {total_scraped:,} >= {expected:,} records", "SUCCESS")
                    total_records_all += total_scraped
                    successful_items += 1
                    continue
                else:
                    log(f"✅ Transactions complete ({total_scraped:,}), but proceeding for Analysis ({detail_action})...", "INFO")
                    # Do NOT continue, proceed to invoke scraper which will skip tx logic if needed or just finish tx loop fast, then do analysis.
            
            # Create scraper instance for this batch item
            scraper = ScraperProDetail(driver, wait, csv_file=csv_file)
            scraper.current_segment = current_segment
            scraper.current_page = current_page
            scraper.current_stt = current_stt
            scraper.total_scraped = total_scraped
            scraper.segment_end_date = segment_end_date
            scraper.last_scraped_date = last_scraped_date
            scraper.batch_config = batch_item  # Store batch config for reference
            
            # Close Tips modal if it appears
            scraper.close_tips_modal()
            
            # Run scraper with batch_config (with retry logic)
            MAX_BATCH_RETRIES = 3
            batch_success = False
            user_interrupted = False
            
            for retry_attempt in range(MAX_BATCH_RETRIES):
                try:
                    if retry_attempt > 0:
                        log(f"🔄 Retry attempt {retry_attempt + 1}/{MAX_BATCH_RETRIES} for '{item_name}'...", "WARNING")
                        
                        # Re-detect resume point (in case partial progress was made)
                        current_segment, current_page, current_stt, total_scraped, segment_end_date, last_scraped_date = ScraperProDetail.detect_resume_point(csv_file)
                        
                        # Re-create scraper with updated state
                        scraper = ScraperProDetail(driver, wait, csv_file=csv_file)
                        scraper.current_segment = current_segment
                        scraper.current_page = current_page
                        scraper.current_stt = current_stt
                        scraper.total_scraped = total_scraped
                        scraper.segment_end_date = segment_end_date
                        scraper.last_scraped_date = last_scraped_date
                        scraper.batch_config = batch_item
                        
                        # Only check if browser is still alive, don't do full recovery
                        # scrape_detail_transactions will handle form filling
                        try:
                            _ = scraper.driver.current_url
                            log("✅ Browser still alive, proceeding with retry...", "INFO")
                            
                            # CRITICAL: Clear form before retry to prevent duplicate values
                            log("🧹 Clearing form before retry...", "INFO")
                            navigator_pro.click_all_clear(driver, wait)
                        except:
                            # Browser dead, need deep recovery
                            log("⚠️ Browser dead, performing deep recovery...", "WARNING")
                            if not scraper.perform_deep_recovery(batch_config=batch_item):
                                log(f"❌ Recovery failed for retry {retry_attempt + 1}", "ERROR")
                                continue
                    
                    success = scraper.scrape_detail_transactions(batch_config=batch_item)
                    
                    if success:
                        successful_items += 1
                        total_records_all += scraper.total_scraped
                        log(f"✅ Batch item '{item_name}' completed: {scraper.total_scraped:,} records", "SUCCESS")
                        batch_success = True
                        break  # Exit retry loop on success
                    else:
                        log(f"⚠️ Batch item '{item_name}' returned False (attempt {retry_attempt + 1}/{MAX_BATCH_RETRIES})", "WARNING")
                
                except KeyboardInterrupt:
                    log("\n🛑 User interrupted - exiting gracefully...", "WARNING")
                    user_interrupted = True
                    break  # Exit retry loop immediately
                        
                except Exception as e:
                    log(f"❌ Batch item '{item_name}' exception (attempt {retry_attempt + 1}/{MAX_BATCH_RETRIES}): {e}", "ERROR")
                    import traceback
                    traceback.print_exc()
            
            # If user interrupted, exit entire batch processing
            if user_interrupted:
                log("🛑 Stopping all batch processing due to user interrupt.", "WARNING")
                break  # Exit the batch items loop
            
            if not batch_success:
                failed_items += 1
                log(f"❌ Batch item '{item_name}' FAILED after {MAX_BATCH_RETRIES} attempts", "ERROR")
        
        # ============================================================
        # BATCH SUMMARY
        # ============================================================
        batch_elapsed = (datetime.now() - batch_start_time).total_seconds()
        
        log(f"\n{'='*60}", "SUCCESS")
        log(f"📊 BATCH COMPLETE - SUMMARY", "SUCCESS")
        log(f"{'='*60}", "SUCCESS")
        log(f"✅ Successful: {successful_items}/{len(batch_items)} items", "SUCCESS" if failed_items == 0 else "WARNING")
        if failed_items > 0:
            log(f"❌ Failed: {failed_items}/{len(batch_items)} items", "WARNING")
        log(f"📊 Total Records: {total_records_all:,}", "INFO")
        log(f"⏱️  Total Time: {int(batch_elapsed//3600)}h {int((batch_elapsed%3600)//60)}m {int(batch_elapsed%60)}s", "INFO")
        log(f"{'='*60}\n", "SUCCESS")
        
        # Keep browser open briefly
        log("🔄 Closing browser in 10 seconds...", "INFO")
        time.sleep(10)
        driver.quit()
        
        return failed_items == 0
        
    except Exception as e:
        log(f"❌ Multi-batch main failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def main():
    """
    Main entry point - routes to Single, Multi, or Daily mode based on DETAIL_SUBMODE.
    """
    submode = getattr(config, 'DETAIL_SUBMODE', 'single')
    
    log(f"🔀 Strategy: {submode.upper()} - TRANSACTIONS", "INFO")

    if submode == "daily":
        log("📅 Running in Daily Mode (day-by-day iteration)", "INFO")
        try:
            from .core_pro_daily import main_pro_detail_daily
        except ImportError:
            from src.scraper.core_pro_daily import main_pro_detail_daily
        return main_pro_detail_daily()

    elif submode == "multi":
        log("📂 Running in Batch Mode", "INFO")
        return main_pro_detail_multi()
    else:
        log("👤 Running in Single Mode (using config vars)", "INFO")
        # Ensure main_pro_detail uses the new login flow too?
        # main_pro_detail likely uses ScraperProDetail directly.
        return main_pro_detail()


if __name__ == "__main__":
    main()

