#!/bin/bash
# Chạy 1 lần khi airflow-init container start.
# Migrate DB → tạo admin user → tạo connections → tạo variables.
set -e

echo "======================================================"
echo " Airflow Init — STSDataIngestion (local test)"
echo "======================================================"

echo ""
echo "--> Configure SimpleAuthManager password file..."
python - <<'PY'
import json
import os
from pathlib import Path

passwords_file = Path(
    os.getenv(
        "AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE",
        "/opt/airflow/config/simple_auth_manager_passwords.json",
    )
)
username = os.getenv("AIRFLOW_ADMIN_USERNAME", "admin")
password = os.getenv("AIRFLOW_ADMIN_PASSWORD", "admin")

passwords_file.parent.mkdir(parents=True, exist_ok=True)
passwords_file.write_text(json.dumps({username: password}), encoding="utf-8")
PY

echo ""
echo "--> Migrate Airflow metadata DB..."
airflow db migrate

echo ""
echo "--> Create admin user (${AIRFLOW_ADMIN_USERNAME:-admin}/${AIRFLOW_ADMIN_PASSWORD:-admin})..."
airflow users create \
  --username "${AIRFLOW_ADMIN_USERNAME:-admin}" \
  --password "${AIRFLOW_ADMIN_PASSWORD:-admin}" \
  --firstname "${AIRFLOW_ADMIN_FIRSTNAME:-STS}" \
  --lastname "${AIRFLOW_ADMIN_LASTNAME:-Admin}" \
  --role Admin \
  --email "${AIRFLOW_ADMIN_EMAIL:-admin@stscorp.local}" 2>/dev/null \
  || echo "    (user '${AIRFLOW_ADMIN_USERNAME:-admin}' already exists, skipping)"

echo ""
echo "--> Create smtp_default connection..."
airflow connections delete smtp_default 2>/dev/null || true
airflow connections add smtp_default \
  --conn-type smtp \
  --conn-host "${AIRFLOW__SMTP__SMTP_HOST:-smtp.gmail.com}" \
  --conn-login "${AIRFLOW__SMTP__SMTP_USER}" \
  --conn-password "$(echo "${AIRFLOW__SMTP__SMTP_PASSWORD}" | tr -d ' ')" \
  --conn-port "${AIRFLOW__SMTP__SMTP_PORT:-587}" \
  --conn-extra '{"smtp_starttls": true, "smtp_ssl": false}'

echo ""
echo "--> Set Airflow Variables..."
airflow variables set pipeline_summary_email \
  "${AIRFLOW__SMTP__SMTP_USER:-khoinm0603@gmail.com}" 2>/dev/null || true

echo ""
echo "======================================================"
echo " Init DONE. Airflow is ready."
echo " UI: http://localhost:8080  (${AIRFLOW_ADMIN_USERNAME:-admin} / ${AIRFLOW_ADMIN_PASSWORD:-admin})"
echo "======================================================"
