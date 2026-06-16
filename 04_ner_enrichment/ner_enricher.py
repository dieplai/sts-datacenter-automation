"""
STS NER Enricher — Phase 2 enrichment pipeline
Runs xlm-roberta-product-ner_enhanced_2 on product_description to extract:
  - product_name_clean : PROD entity (tên sản phẩm sạch)
  - fabric_pct         : PCT entity (% thành phần vải, e.g. "cotton 65%")
  - item_condition     : COND entity (tình trạng, e.g. "mới 100%")

Model: fine-tuned XLM-RoBERTa (F1=0.9923) trained on Vietnam customs textile data
Repo:  <HF_USERNAME>/xlm-roberta-product-ner_enhanced_2  (HuggingFace Hub)

Usage:
    # Enrich all un-enriched rows in hs_raw_data
    python ner_enricher.py

    # Enrich specific table, custom batch size
    python ner_enricher.py --table hs_raw_data --batch-size 200

    # Dry run — print sample predictions without writing to DB
    python ner_enricher.py --dry-run --limit 10

Requirements:
    pip install transformers torch psycopg2-binary pandas tqdm
    (GPU optional but recommended for large batches; CPU ~100 rows/min)

DB: adds 3 columns to hs_raw_data — run migration.sql first if not exist.
"""

import os
import argparse
import logging
from typing import Optional

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
HF_MODEL_NAME = os.getenv(
    "NER_MODEL",
    # Replace <HF_USERNAME> with actual HuggingFace username before deploying
    "<HF_USERNAME>/xlm-roberta-product-ner_enhanced_2"
)

DB = dict(
    host=os.getenv("PG_HOST", "localhost"),
    port=int(os.getenv("PG_PORT", 5432)),
    dbname=os.getenv("PG_DB", "sts-dev"),
    user=os.getenv("PG_USER", "postgres"),
    password=os.getenv("PG_PASS", ""),
)

# BIO tag labels (must match training label scheme)
LABEL_MAP = {
    "B-PROD": "product", "I-PROD": "product",
    "B-PCT":  "pct",     "I-PCT":  "pct",
    "B-COND": "cond",    "I-COND": "cond",
    "O": None,
}


# ── Model loader ──────────────────────────────────────────────────────────────
_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline as hf_pipeline
        log.info(f"Loading NER model: {HF_MODEL_NAME}")
        _pipeline = hf_pipeline(
            "ner",
            model=HF_MODEL_NAME,
            aggregation_strategy="simple",  # merges B-/I- spans automatically
            device=0 if _has_gpu() else -1,
        )
        log.info("Model loaded")
    return _pipeline


def _has_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ── NER extraction ─────────────────────────────────────────────────────────────
def extract_entities(texts: list[str]) -> list[dict]:
    """Run NER on a list of texts. Returns list of dicts with product/pct/cond."""
    nlp = get_pipeline()
    results = []
    for batch in nlp(texts, batch_size=32):
        if not isinstance(batch, list):
            batch = [batch]
        prod_parts, pct_parts, cond_parts = [], [], []
        for ent in batch:
            label = ent.get("entity_group") or ent.get("entity", "")
            word = ent.get("word", "").strip()
            if not word:
                continue
            if "PROD" in label:
                prod_parts.append(word)
            elif "PCT" in label:
                pct_parts.append(word)
            elif "COND" in label:
                cond_parts.append(word)
        results.append({
            "product_name_clean": " ".join(prod_parts) or None,
            "fabric_pct":         " ".join(pct_parts)  or None,
            "item_condition":     " ".join(cond_parts) or None,
        })
    return results


# ── DB helpers ────────────────────────────────────────────────────────────────
MIGRATION_SQL = """
ALTER TABLE hs_raw_data
    ADD COLUMN IF NOT EXISTS product_name_clean  TEXT,
    ADD COLUMN IF NOT EXISTS fabric_pct          TEXT,
    ADD COLUMN IF NOT EXISTS item_condition      TEXT,
    ADD COLUMN IF NOT EXISTS ner_processed       BOOLEAN DEFAULT FALSE;
"""

def ensure_columns(conn):
    with conn.cursor() as cur:
        cur.execute(MIGRATION_SQL)
    conn.commit()
    log.info("NER columns ensured in hs_raw_data")


def fetch_unprocessed(conn, table: str, limit: Optional[int], batch_size: int):
    """Yield (id, product_description) for rows not yet NER-processed."""
    offset = 0
    total_fetched = 0
    while True:
        if limit and total_fetched >= limit:
            break
        fetch = batch_size if not limit else min(batch_size, limit - total_fetched)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, product_description FROM {table} "
                f"WHERE (ner_processed IS NULL OR ner_processed = FALSE) "
                f"AND product_description IS NOT NULL "
                f"LIMIT %s OFFSET %s",
                (fetch, offset),
            )
            rows = cur.fetchall()
        if not rows:
            break
        total_fetched += len(rows)
        offset += len(rows)
        yield rows


def write_enrichments(conn, table: str, enrichments: list[tuple]):
    """UPDATE hs_raw_data SET product_name_clean=... WHERE id=..."""
    with conn.cursor() as cur:
        for row_id, prod, pct, cond in enrichments:
            cur.execute(
                f"UPDATE {table} SET "
                f"product_name_clean=%s, fabric_pct=%s, item_condition=%s, "
                f"ner_processed=TRUE WHERE id=%s",
                (prod, pct, cond, row_id),
            )
    conn.commit()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="NER enrichment for hs_raw_data")
    ap.add_argument("--table",      default="hs_raw_data")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--limit",      type=int, default=None,
                    help="Max rows to process (for testing)")
    ap.add_argument("--dry-run",    action="store_true",
                    help="Print predictions, skip DB write")
    args = ap.parse_args()

    conn = psycopg2.connect(**DB)
    try:
        if not args.dry_run:
            ensure_columns(conn)

        total_enriched = 0
        for batch_rows in fetch_unprocessed(conn, args.table, args.limit, args.batch_size):
            ids   = [r[0] for r in batch_rows]
            texts = [r[1] or "" for r in batch_rows]

            entities = extract_entities(texts)

            enrichments = [
                (ids[i], e["product_name_clean"], e["fabric_pct"], e["item_condition"])
                for i, e in enumerate(entities)
            ]

            if args.dry_run:
                for row_id, prod, pct, cond in enrichments[:3]:
                    log.info(f"  id={row_id} | prod={prod!r} | pct={pct!r} | cond={cond!r}")
            else:
                write_enrichments(conn, args.table, enrichments)

            total_enriched += len(batch_rows)
            log.info(f"  Enriched {total_enriched:,} rows so far...")

        log.info(f"=== NER enrichment done: {total_enriched:,} rows processed ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
