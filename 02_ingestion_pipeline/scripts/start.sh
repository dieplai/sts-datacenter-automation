#!/usr/bin/env bash
# Start the local Docker stack after the first-time initialization has run.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE="${COMPOSE:-docker compose}"
POSTGRES_USER="${POSTGRES_USER:-stsbeyond}"
POSTGRES_DB="${POSTGRES_DB:-data_ingestion}"

echo "======================================================"
echo " STSDataIngestion - Docker Start"
echo "======================================================"

echo ""
echo "--> Start PostgreSQL and MongoDB"
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
echo "--> Start Airflow runtime services"
${COMPOSE} up -d airflow-webserver airflow-scheduler airflow-dag-processor

echo ""
echo "--> Wait for Airflow API healthcheck"
for _ in {1..60}; do
  if ${COMPOSE} exec -T airflow-webserver curl --fail http://localhost:8080/api/v2/monitor/health >/dev/null 2>&1; then
    echo "    Airflow API is ready."
    break
  fi
  sleep 2
done

if ! ${COMPOSE} exec -T airflow-webserver curl --fail http://localhost:8080/api/v2/monitor/health >/dev/null 2>&1; then
  echo "Airflow API did not become ready in time." >&2
  exit 1
fi

echo ""
echo "--> Current containers"
${COMPOSE} ps

echo ""
echo "======================================================"
echo " Start DONE"
echo " Airflow UI: http://localhost:8080"
echo " Login: admin / admin"
echo " App PostgreSQL: localhost:5434"
echo "======================================================"
