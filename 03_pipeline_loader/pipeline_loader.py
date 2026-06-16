"""
STS W52 CSV → PostgreSQL loader
Bước 1 trong pipeline: raw CSV → hs_raw_data (staging table) → Fact tables

Usage:
    python pipeline_loader.py --file detail_Vietnam_import_hs52_JAN_2026.csv
    python pipeline_loader.py --dir /data/raw --dry-run
    python pipeline_loader.py --dir /data/raw/acc1 /data/raw/acc2

DB config (env vars):
    PG_HOST    default: localhost
    PG_PORT    default: 5432
    PG_DB      default: sts-dev
    PG_USER    default: postgres
    PG_PASS    (required)
"""

import os
import re
import argparse
import logging
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── DB config ─────────────────────────────────────────────────────────────────
DB = dict(
    host=os.getenv("PG_HOST", "localhost"),
    port=int(os.getenv("PG_PORT", 5432)),
    dbname=os.getenv("PG_DB", "sts-dev"),
    user=os.getenv("PG_USER", "postgres"),
    password=os.getenv("PG_PASS", ""),
)

# ── Column mapping: CSV header → DB column (hs_raw_data staging table) ────────
# Source of truth: STSDataIngestion/src/data_processing/.../validation_handler.py
# DB table: hs_raw_data (crawling_data.temp equivalent)
IMPORT_MAP = {
    "Declaration No":          "declaration_number",
    "Transaction Date":        "transaction_date",
    "HS Code":                 "hs_code",
    "Product Description":     "product_description",
    "Product Desc(EN)":        "product_description_en",
    "Supplier":                "supplier_name",
    "Buyer":                   "buyer_name",
    "quantity":                "quantity",
    "Quantity unit":           "quantity_unit",
    "Unit Price(USD)":         "unit_price_usd",
    "Unit Price(Currency)":    "unit_price_foreign_currency",
    "Total Price(Currency)":   "total_price_foreign_currency",
    "Amount":                  "total_amount_usd",
    "Exchange Rate":           "exchange_rate",
    "Incoterms":               "incoterms",
    "Payment Method":          "payment_method",
    "Import Country":          "import_country",
    "Mode of Transport":       "transport_mode",
    "Country of Origin":       "country_of_origin",
    "Customs Br Code":         "customs_branch_code",
    "Customs Br Name":         "customs_branch_name",
    "bill_id":                 "bill_id",
    "buyer_country":           "buyer_country",
    "customs_branch_code_2":   "customs_branch_code_secondary",
    "date":                    "date",
    "exporter_country":        "exporter_country",
    "foreign_currency":        "foreign_currency",
    "importer_address_vn":     "importer_address_vn",
    "importer_name_en":        "importer_name_en",
    "importer_tel":            "importer_tel",
    "type_of_import":          "import_type",
}

# Export adds the same 31 cols; server Claude should verify export-specific cols
# (e.g. "Export serial number" → "export_declaration_number") and extend this map.
EXPORT_MAP = IMPORT_MAP.copy()


# ── Filename parser ────────────────────────────────────────────────────────────
def parse_filename(filepath: str) -> dict:
    """detail_Vietnam_import_hs52_JAN_2026 → {trade_type, hs, month, year}"""
    name = Path(filepath).stem
    m = re.match(r"detail_Vietnam_(import|export)_hs(\d+)_(\w+)_(\d{4})", name, re.I)
    if not m:
        raise ValueError(f"Cannot parse filename: {name!r}")
    return {
        "trade_type": m.group(1).lower(),
        "hs":         m.group(2),
        "month":      m.group(3).upper(),
        "year":       int(m.group(4)),
    }


# ── CSV reader ─────────────────────────────────────────────────────────────────
def load_csv(filepath: str, col_map: dict) -> pd.DataFrame:
    df = pd.read_csv(filepath, encoding="utf-8-sig", dtype=str, low_memory=False)
    keep = {csv_col: db_col for csv_col, db_col in col_map.items()
            if csv_col in df.columns and db_col is not None}

    if not keep:
        log.warning(f"  No mapped columns found. CSV has: {list(df.columns[:8])}")
    df = df[list(keep.keys())].rename(columns=keep)

    # Type coercion
    if "transaction_date" in df.columns:
        df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    for num_col in ("quantity", "unit_price_usd", "total_amount_usd",
                    "exchange_rate", "unit_price_foreign_currency",
                    "total_price_foreign_currency"):
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
    return df


# ── Bulk insert ────────────────────────────────────────────────────────────────
def insert_batch(conn, df: pd.DataFrame, meta: dict, batch_size: int = 5000,
                 table: str = "hs_raw_data"):
    df = df.copy()
    df["data_source"]  = meta.get("source_file", "")
    df["import_type"]  = df.get("import_type", meta.get("trade_type", ""))

    cols = list(df.columns)
    rows = [tuple(r) for r in df.itertuples(index=False, name=None)]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
           f"ON CONFLICT DO NOTHING")

    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            execute_values(cur, sql, rows[i : i + batch_size])
            log.info(f"    rows {i}–{min(i + batch_size, len(rows))}")
    conn.commit()
    log.info(f"  Committed {len(rows):,} rows → {table}")


# ── Per-file entry point ───────────────────────────────────────────────────────
def process_file(filepath: str, dry_run: bool = False,
                 table: str = "hs_raw_data") -> int:
    meta = parse_filename(filepath)
    col_map = IMPORT_MAP if meta["trade_type"] == "import" else EXPORT_MAP
    log.info(f"Processing {Path(filepath).name}  {meta}")

    df = load_csv(filepath, col_map)
    log.info(f"  Read {len(df):,} rows, {len(df.columns)} cols")

    if dry_run:
        log.info("  [DRY RUN] skipping DB insert")
        return len(df)

    meta["source_file"] = Path(filepath).name
    conn = psycopg2.connect(**DB)
    try:
        insert_batch(conn, df, meta, table=table)
    finally:
        conn.close()
    return len(df)


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Load W52 CSVs into PostgreSQL hs_raw_data")
    ap.add_argument("--file",     help="Single CSV file")
    ap.add_argument("--dir",      nargs="+", help="One or more directories of CSVs")
    ap.add_argument("--pattern",  default="detail_Vietnam_*.csv")
    ap.add_argument("--table",    default="hs_raw_data",
                    help="Target DB table (default: hs_raw_data)")
    ap.add_argument("--dry-run",  action="store_true",
                    help="Parse files but skip DB insert")
    args = ap.parse_args()

    files: list[Path] = []
    if args.file:
        files = [Path(args.file)]
    elif args.dir:
        for d in args.dir:
            files.extend(sorted(Path(d).rglob(args.pattern)))

    if not files:
        ap.print_help()
        return

    total_rows = 0
    failed = []
    for f in files:
        try:
            n = process_file(str(f), dry_run=args.dry_run, table=args.table)
            total_rows += n
        except Exception as e:
            log.error(f"FAILED {f}: {e}")
            failed.append(str(f))

    log.info(f"=== Done: {len(files) - len(failed)}/{len(files)} files, "
             f"{total_rows:,} rows inserted ===")
    if failed:
        log.warning(f"Failed: {failed}")


if __name__ == "__main__":
    main()
