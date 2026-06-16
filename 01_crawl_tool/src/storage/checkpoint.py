"""Resume-point detection from previously-written CSV (or Excel fallback).

The scraper writes a `(segment, page, stt)` triple on every row. When
restarting, we read the last row of the file and compute where to pick up.

Segment/page accounting:
  - 10 000 records per search ⇒ 30 rows × 333 pages ceiling
  - When the current page hits that ceiling, the scraper shifts to a new
    segment and uses the oldest trade_date of the finished segment as the
    new end_date filter.
"""
import os

import pandas as pd

try:
    from ..observability import log
except ImportError:  # pragma: no cover
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import log  # type: ignore


MAX_PAGES_PER_SEGMENT = 333
ROWS_PER_PAGE = 30

_DATE_COLS = ("Transaction Date", "date", "transaction_date")


def _safe_read_csv(path):
    if not os.path.exists(path) or os.path.getsize(path) < 10:
        return None
    try:
        return pd.read_csv(
            path, encoding="utf-8-sig", on_bad_lines="skip", low_memory=False,
        )
    except Exception:
        return None


def _date_of(row):
    for col in _DATE_COLS:
        if col in row.index and pd.notna(row[col]):
            return str(row[col])
    return None


def detect_resume_point(csv_file):
    """Return `(next_segment, next_page, next_stt, total_rows,
    segment_end_date, last_scraped_date)`.

    Falls back to Excel sibling if CSV is missing/broken. Returns
    `(1, 1, 1, 0, None, None)` for a fresh run.
    """
    excel_file = csv_file.replace(".csv", ".xlsx")

    df = _safe_read_csv(csv_file)
    if df is None or "segment" not in df.columns or "page" not in df.columns:
        if os.path.exists(excel_file):
            log(f"🔍 Attempting to restore resume point from Excel: "
                f"{os.path.basename(excel_file)}", "INFO")
            try:
                df_excel = pd.read_excel(excel_file, engine="openpyxl")
                if not df_excel.empty and "segment" in df_excel.columns and "page" in df_excel.columns:
                    log("✅ Valid data found in Excel. Restoring CSV...", "SUCCESS")
                    df_excel.to_csv(csv_file, index=False, encoding="utf-8-sig")
                    df = df_excel
            except Exception:
                pass

    try:
        if df is None or df.empty:
            return 1, 1, 1, 0, None, None
        if "segment" not in df.columns or "page" not in df.columns:
            return 1, 1, 1, 0, None, None

        last_row = df.iloc[-1]
        try:
            last_segment = int(last_row.get("segment", 1))
            last_page = int(last_row.get("page", 1))
            last_stt = int(last_row.get("stt", 0))
        except Exception:
            return 1, 1, 1, 0, None, None

        total_rows = len(df)
        last_scraped_date_val = _date_of(last_row)

        # --- segment_end_date detection -----------------------------------
        # Priority 1: last page of segment → use its oldest-date row
        # Priority 2: currently inside segment N>1 → take from segment N-1's last
        segment_end_date = None
        will_shift = last_stt >= ROWS_PER_PAGE and last_page >= MAX_PAGES_PER_SEGMENT

        if will_shift:
            try:
                segment_end_date = _date_of(df.iloc[-1])
                if segment_end_date:
                    log(f"📍 Detected boundary date from last row of Seg "
                        f"{last_segment}: {segment_end_date}", "INFO")
            except Exception as e:
                log(f"⚠️ Could not detect boundary date from last row: {e}", "WARNING")

        elif last_segment > 1:
            try:
                prev_n = last_segment - 1
                prev_mask = df["segment"] == prev_n
                if prev_mask.any():
                    segment_end_date = _date_of(df[prev_mask].iloc[-1])
                    if segment_end_date:
                        log(f"📍 Detected segment boundary date from last row "
                            f"of Seg {prev_n}: {segment_end_date}", "INFO")

                if not segment_end_date:
                    curr_mask = df["segment"] == last_segment
                    if curr_mask.any():
                        segment_end_date = _date_of(df[curr_mask].iloc[0])
                        if segment_end_date:
                            log(f"📍 Fallback: first row date of Seg "
                                f"{last_segment}: {segment_end_date}", "INFO")
            except Exception as e:
                log(f"⚠️ Could not detect segment boundary date: {e}", "WARNING")

        # --- where to resume ----------------------------------------------
        next_segment = last_segment
        next_page = last_page
        next_stt = last_stt + 1

        if last_stt >= ROWS_PER_PAGE:
            next_page = last_page + 1
            next_stt = 1
            if next_page > MAX_PAGES_PER_SEGMENT:
                next_page = 1
                next_segment += 1
                log(f"📍 Resume will start new segment {next_segment}", "INFO")

        log("📍 Detected resume point:", "INFO")
        log(f"   Last scraped: Seg {last_segment}, Page {last_page}, STT {last_stt}", "INFO")
        log(f"   Total rows in history: {total_rows:,}", "INFO")
        log(f"   Segment end date: {segment_end_date or 'None (Fresh start)'}", "INFO")
        log(f"   Will resume from: Seg {next_segment}, Page {next_page}, STT {next_stt}", "INFO")

        return next_segment, next_page, next_stt, total_rows, segment_end_date, last_scraped_date_val

    except Exception as e:
        log(f"⚠️ Error resume point: {e}", "WARNING")
        return 1, 1, 1, 0, None, None
