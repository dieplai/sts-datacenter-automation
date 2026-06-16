#!/usr/bin/env bash
# STS W52 — Pull CSVs from crawl machines → load into PostgreSQL
# Schedule: cron every 2 hours, or run manually
#
# Requires:
#   - SSH key auth to Máy 1 (100.76.219.16) and Máy 3 (100.76.65.2) as user pc
#   - Python + psycopg2 installed: pip install pandas psycopg2-binary
#   - PG_HOST/PG_PASS env vars set (or edit DB section below)
#
# Usage:
#   chmod +x watch_and_ingest.sh
#   ./watch_and_ingest.sh
#
#   # Add to crontab (every 2 hours):
#   0 */2 * * * /opt/sts/03_pipeline_loader/watch_and_ingest.sh >> /data/logs/ingest.log 2>&1

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
RAW_DIR="/data/raw"
LOG_DIR="/data/logs"
LOADER_DIR="$(dirname "$0")"

MAY1="100.76.219.16"
MAY3="100.76.65.2"
SSH_USER="pc"

export PG_HOST="${PG_HOST:-localhost}"
export PG_PORT="${PG_PORT:-5432}"
export PG_DB="${PG_DB:-sts-dev}"
export PG_USER="${PG_USER:-postgres}"
# PG_PASS must be set in environment or .env file

mkdir -p "$RAW_DIR"/{acc1,acc2,acc3,acc4} "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG="$LOG_DIR/ingest_$TIMESTAMP.log"

echo "[$TIMESTAMP] === STS INGEST START ===" | tee -a "$LOG"

# ── Pull from Máy 1 (ACC1 + ACC2) ─────────────────────────────────────────────
for ACC in 1 2; do
    echo "[$(date +%H:%M:%S)] Pulling ACC$ACC from Máy 1 ($MAY1)..." | tee -a "$LOG"
    rsync -av --checksum \
        --include="detail_Vietnam_*.csv" \
        --exclude="*" \
        "${SSH_USER}@${MAY1}:C:/Crawl/acc${ACC}/crawl_w52_sts/output/" \
        "$RAW_DIR/acc${ACC}/" 2>&1 | tee -a "$LOG" || \
        echo "[WARN] ACC$ACC rsync failed, continuing..." | tee -a "$LOG"
done

# ── Pull from Máy 3 (ACC3 + ACC4) ─────────────────────────────────────────────
for ACC in 3 4; do
    echo "[$(date +%H:%M:%S)] Pulling ACC$ACC from Máy 3 ($MAY3)..." | tee -a "$LOG"
    rsync -av --checksum \
        --include="detail_Vietnam_*.csv" \
        --exclude="*" \
        "${SSH_USER}@${MAY3}:C:/Crawl/acc${ACC}/crawl_w52_sts/output/" \
        "$RAW_DIR/acc${ACC}/" 2>&1 | tee -a "$LOG" || \
        echo "[WARN] ACC$ACC rsync failed, continuing..." | tee -a "$LOG"
done

# ── Load all new CSVs into PostgreSQL ─────────────────────────────────────────
echo "[$(date +%H:%M:%S)] Loading CSVs into PostgreSQL..." | tee -a "$LOG"
python3 "$LOADER_DIR/pipeline_loader.py" \
    --dir "$RAW_DIR/acc1" "$RAW_DIR/acc2" "$RAW_DIR/acc3" "$RAW_DIR/acc4" \
    2>&1 | tee -a "$LOG"

echo "[$(date +%H:%M:%S)] === STS INGEST DONE ===" | tee -a "$LOG"

# ── Optional: NER enrichment (Phase 2 - uncomment when ready) ─────────────────
# python3 /opt/sts/04_ner_enrichment/ner_enricher.py \
#     --table hs_raw_data --batch-size 500 2>&1 | tee -a "$LOG"
