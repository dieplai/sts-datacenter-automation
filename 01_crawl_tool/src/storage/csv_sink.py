"""CSV writer with dynamic header expansion.

`CsvSink` owns a single CSV path. It writes EVERY row the scraper
produces — no dedupe — because the dedupe-by-bill_id mechanism was
silently dropping legitimate rows when the in-memory `seen_bill_ids`
set drifted from the on-disk CSV state (write-after-add ordering bug;
2026-05-05 acc5 austgrow incident lost ~17 line items across pages
5/8/10). Downstream DA pipeline (Spark / dbt / SQL `SELECT DISTINCT`)
is the right place to handle uniqueness.

`seen_bill_ids` is still loaded from existing CSV for visibility
("Resumed from CSV with N rows") but no longer used to filter writes.

Usage::

    sink = CsvSink(csv_file, FIELD_MAPPING, ALIASES)
    sink.initialize()        # create dir + load resume info
    sink.append(transactions) # call once per page
"""
import csv
import os

import pandas as pd

try:
    from ..observability import log
except ImportError:  # pragma: no cover
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import log  # type: ignore


_STATIC_ORDER = [
    "segment", "page", "stt",
    "bill_no", "date", "hs", "descript", "product_desc_en",
    "type_of_export_code", "type_of_export_name",
    "seller", "buyer",
    "qty", "qty_unit", "unit_name", "uusd", "unit_value_in_fc",
    "total_value_in_fc", "amount",
    "foreign_currency", "exchange_rate", "incoterms", "payment_method",
    "buyer_country", "seller_country", "trans", "origin_country",
    "customs_br_code_1", "customs_br_code_2", "customs_branch_name",
    "buyer_port", "seller_port", "flight_voyage_number", "carrier",
    "bill_id", "export_declaration_number", "id",
]

_BILL_ID_COLUMN_CANDIDATES = (
    "bill_id", "Bill of Lading ID", "billid", "BillId", "Bill ID",
)


def _normalize(s):
    """Lowercase + keep-alnum only — safe header comparison key."""
    if not s:
        return ""
    return "".join(c.lower() for c in str(s) if c.isalnum())


class CsvSink:
    """Single-file CSV writer with dynamic header expansion. No dedupe —
    downstream DA pipeline handles uniqueness."""

    def __init__(self, csv_file, field_mapping, aliases):
        self.csv_file = csv_file
        self.field_mapping = field_mapping
        self.aliases = aliases
        # Kept for backward-compat: a few callers in core_pro_detail.py
        # reference _seen_bill_ids. We populate it from the existing CSV
        # at startup (resume-info logging) but never use it to filter
        # writes.
        self.seen_bill_ids = set()

    # ---- lifecycle ------------------------------------------------------

    def initialize(self):
        """Ensure the output dir exists and warm the dedupe set from any
        existing CSV (resume path)."""
        try:
            d = os.path.dirname(self.csv_file)
            if d:
                os.makedirs(d, exist_ok=True)
        except Exception as e:
            log(f"❌ Error initializing CSV: {e}", "ERROR")
        self._load_seen_bill_ids()

    def _load_seen_bill_ids(self):
        try:
            if not os.path.exists(self.csv_file) or os.path.getsize(self.csv_file) < 20:
                return
            with open(self.csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                try:
                    header = next(reader)
                except StopIteration:
                    return
            col = next(
                (c for c in _BILL_ID_COLUMN_CANDIDATES if c in header), None,
            )
            if not col:
                return
            df = pd.read_csv(
                self.csv_file, usecols=[col], dtype=str,
                encoding="utf-8-sig", on_bad_lines="skip",
            )
            self.seen_bill_ids.update(
                v for v in df[col].dropna().astype(str)
                if v and v.lower() != "nan"
            )
            if self.seen_bill_ids:
                log(f"🧠 Resume load: {len(self.seen_bill_ids)} bill_ids "
                    f"already in CSV (informational — no dedupe applied)",
                    "INFO")
        except Exception as e:
            log(f"⚠️ _load_seen_bill_ids failed: {e}", "WARNING")

    # ---- write ----------------------------------------------------------

    def append(self, transactions):
        """Append a batch of transaction dicts. Writes ALL rows the scraper
        produces — no dedupe. Downstream DA pipeline is responsible for
        SELECT DISTINCT / drop_duplicates by bill_id (or composite key).
        """
        try:
            if not transactions:
                return

            # Track new bill_ids for visibility/logging only — no filtering.
            # Old behavior dropped rows whose bill_id was already in
            # seen_bill_ids, but the set drifted from the CSV when writes
            # failed mid-flight or recovery cycles re-fetched specs that
            # were "added" but never committed. Net effect: real rows lost
            # silently. Now we just log how many rows in this batch share
            # a bill_id we've previously written, for monitoring.
            potential_dups = sum(
                1 for t in transactions
                if str(t.get("bill_id") or "").strip() in self.seen_bill_ids
                and str(t.get("bill_id") or "").strip()
            )
            if potential_dups:
                log(f"ℹ️ {potential_dups} rows in this batch have bill_id "
                    f"already in CSV (writing anyway — DA pipeline dedups)",
                    "INFO")
            for t in transactions:
                bid = str(t.get("bill_id") or "").strip()
                if bid:
                    self.seen_bill_ids.add(bid)

            file_exists = (
                os.path.exists(self.csv_file)
                and os.path.getsize(self.csv_file) > 10
            )

            # --- resolve header ---
            if not file_exists:
                fieldnames = []
                for k in _STATIC_ORDER:
                    disp = self.field_mapping.get(k, k)
                    if disp not in fieldnames:
                        fieldnames.append(disp)
            else:
                with open(self.csv_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    try:
                        fieldnames = next(reader)
                    except StopIteration:
                        file_exists = False
                        return self.append(transactions)

            # --- dynamic expansion for previously-unknown fields ---
            known_norms = {_normalize(c) for c in fieldnames}
            for v in self.field_mapping.values():
                known_norms.add(_normalize(v))

            new_fields = []
            for t in transactions:
                for raw_key in t.keys():
                    norm_key = _normalize(raw_key)
                    if norm_key in known_norms:
                        continue
                    covered = any(
                        _normalize(disp) == norm_key for disp in fieldnames
                    )
                    if not covered and raw_key not in new_fields:
                        new_fields.append(raw_key)

            if new_fields:
                log(f"⚡ Found {len(new_fields)} new dynamic fields: {new_fields}",
                    "PROCESS")
                log("⚡ Expanding CSV structure...", "PROCESS")
                fieldnames.extend(new_fields)
                if file_exists:
                    # Rewrite the file with the expanded header
                    with open(self.csv_file, "r", encoding="utf-8-sig") as f:
                        existing = list(csv.DictReader(f))
                    with open(self.csv_file, "w", newline="", encoding="utf-8-sig") as f:
                        writer = csv.DictWriter(
                            f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL,
                        )
                        writer.writeheader()
                        writer.writerows(existing)

            # --- map each transaction to the header via soft matching ---
            normalized_aliases = {_normalize(k): v for k, v in self.aliases.items()}
            normalized_mapping = {
                _normalize(v): k for k, v in self.field_mapping.items()
            }

            mapped_rows = []
            debug_logged = False
            for t in transactions:
                row = {}
                for disp in fieldnames:
                    val = ""
                    norm_col = _normalize(disp)

                    found_key = None
                    if norm_col in normalized_mapping:
                        found_key = normalized_mapping[norm_col]
                    elif norm_col in normalized_aliases:
                        found_key = normalized_aliases[norm_col]

                    if found_key:
                        val = t.get(found_key, "")

                    if val in ("", None):
                        # Last resort: linear scan
                        for raw_k, raw_v in t.items():
                            if _normalize(raw_k) == norm_col:
                                val = raw_v
                                break

                    if val is None:
                        val = ""
                    if isinstance(val, str):
                        val = val.replace("\r", "").replace("\n", " ").strip()
                        val = val.replace("&amp;", "&").replace("&quot;", '"')

                    row[disp] = val

                if not row.get("Transaction Date") and not row.get("Declaration No"):
                    if not debug_logged:
                        log(f"⚠️ Row missing critical data. Available keys: "
                            f"{list(t.keys())}", "DEBUG")
                        debug_logged = True

                mapped_rows.append(row)

            # --- write ---
            with open(self.csv_file, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(
                    f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL,
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerows(mapped_rows)

            log(f"💾 Saved {len(transactions)} rows to CSV: "
                f"{os.path.basename(self.csv_file)}", "SUCCESS")

        except Exception as e:
            log(f"❌ Error saving CSV: {e}", "ERROR")
            import traceback
            traceback.print_exc()
