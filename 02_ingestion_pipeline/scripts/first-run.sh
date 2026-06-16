#!/usr/bin/env bash
# First-time local initialization for STSDataIngestion.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE="${COMPOSE:-docker compose}"
AIRFLOW_IMAGE="${AIRFLOW_IMAGE:-sts-data-ingestion-airflow:local}"
POSTGRES_USER="${POSTGRES_USER:-stsbeyond}"
POSTGRES_DB="${POSTGRES_DB:-data_ingestion}"
POSTGRES_MAINTENANCE_DB="${POSTGRES_MAINTENANCE_DB:-postgres}"
RESET_LOCAL_DATA="${RESET_LOCAL_DATA:-0}"

echo "======================================================"
echo " STSDataIngestion - Docker First Run"
echo "======================================================"

echo ""
echo "--> Prepare Google Drive OAuth token mount"
mkdir -p google_tokens

if [[ ! -f client_secret.json && -f google_tokens/client_secret.json ]]; then
  cp google_tokens/client_secret.json client_secret.json
  echo "    Copied google_tokens/client_secret.json -> client_secret.json"
fi

if [[ -f client_secret.json && ! -f google_tokens/client_secret.json ]]; then
  cp client_secret.json google_tokens/client_secret.json
  echo "    Copied client_secret.json -> google_tokens/client_secret.json"
elif [[ -f google_tokens/client_secret.json ]]; then
  echo "    Found google_tokens/client_secret.json"
else
  echo "    Missing client_secret.json. Put it at ./client_secret.json or ./google_tokens/client_secret.json." >&2
  exit 1
fi

if [[ -f client_secret.token.json && ! -f google_tokens/client_secret.token.json ]]; then
  cp client_secret.token.json google_tokens/client_secret.token.json
  echo "    Copied client_secret.token.json -> google_tokens/client_secret.token.json"
elif [[ -f google_tokens/client_secret.token.json ]]; then
  echo "    Found google_tokens/client_secret.token.json"
else
  echo "    No OAuth token found yet."
fi

echo "    Running Google Drive auth first-run check..."
PYTHONPATH=src uv run python scripts/google_drive_auth.py

if [[ ! -f google_tokens/client_secret.token.json ]]; then
  echo "    Google OAuth token was not created: google_tokens/client_secret.token.json" >&2
  exit 1
fi

echo "    Google OAuth token is ready: google_tokens/client_secret.token.json"

echo ""
echo "--> Build local Airflow image: ${AIRFLOW_IMAGE}"
docker build -f Dockerfile -t "${AIRFLOW_IMAGE}" .

if [[ "${RESET_LOCAL_DATA}" == "1" ]]; then
  echo ""
  echo "--> Reset local Docker data for this compose project"
  ${COMPOSE} down --volumes --remove-orphans
fi

echo ""
echo "--> Start PostgreSQL and MongoDB for initialization"
${COMPOSE} up -d postgres mongo

echo ""
echo "--> Wait for PostgreSQL healthcheck"
for _ in {1..60}; do
  if ${COMPOSE} exec -T postgres pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    echo "    PostgreSQL is ready."
    break
  fi
  sleep 2
done

if ! ${COMPOSE} exec -T postgres pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
fi

echo ""
echo "--> Wait for MongoDB healthcheck"
for _ in {1..60}; do
  if ${COMPOSE} exec -T mongo mongosh --quiet --eval "db.adminCommand('ping').ok" >/dev/null 2>&1; then
    echo "    MongoDB is ready."
    break
  fi
  sleep 2
done

if ! ${COMPOSE} exec -T mongo mongosh --quiet --eval "db.adminCommand('ping').ok" >/dev/null 2>&1; then
  echo "MongoDB did not become ready in time." >&2
  exit 1
fi

echo ""
echo "--> Copy and run DB init script"
${COMPOSE} cp scripts/init-dbs.sql postgres:/tmp/init-dbs.sql
${COMPOSE} exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_MAINTENANCE_DB}" -f /tmp/init-dbs.sql

echo ""
echo "--> Copy and run MongoDB init script"
${COMPOSE} cp scripts/init-mongo.js mongo:/tmp/init-mongo.js
${COMPOSE} exec -T mongo mongosh --quiet etl_pipeline_db /tmp/init-mongo.js

echo ""
echo "--> Create airflow-init container and copy init entrypoint"
${COMPOSE} create --no-recreate airflow-init >/dev/null
${COMPOSE} cp scripts/entrypoint-init.sh airflow-init:/opt/airflow/scripts/entrypoint-init.sh

echo ""
echo "--> Run Airflow init"
${COMPOSE} run --rm airflow-init

echo ""
echo "--> Start runtime stack"
bash scripts/start.sh
