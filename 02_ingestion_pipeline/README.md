# STSDataIngestion

STSDataIngestion is a Python data ingestion pipeline built around DDD and Clean
Architecture. The project downloads files from supported sources, processes HS
code data, stores metadata/results in MongoDB and PostgreSQL, and can be
orchestrated by Airflow.

## What this project does

- Polls Google Drive from Airflow and waits for files for the execution date.
- Downloads files from `google_drive`, `s3`, or `api` through a common loader
  interface.
- Runs a processing pipeline for HS code data.
- Persists ingestion state, processing summaries, raw rows, and per-file status.
- Sends Airflow success/failure summaries through the configured email backend.

## Project layout

```text
.
|-- dags/                  # Airflow DAGs, sensors, wrappers, notifications
|-- markdown/              # Detailed setup and architecture documents
|-- scripts/               # Local Docker scripts, DB init scripts, and Google Drive OAuth
|-- src/
|   |-- data_ingest/       # Pipeline orchestration
|   |-- data_loader/       # Source dispatching and downloaders
|   |-- data_processing/   # Processing handlers and pipeline factory
|   `-- shared/            # Shared domain models, settings, repositories, services
|-- test-airflow/          # Airflow DAG/wrapper tests
|-- tests/                 # Unit tests for domain/application/infrastructure code
|-- pyproject.toml
`-- README.md
```

## Requirements

- Python 3.11+
- `uv`
- Docker with `docker compose` for the local Airflow/Postgres/MongoDB stack
- Google OAuth client secret if using Google Drive ingestion

Quick check:

```bash
python --version
uv --version
docker --version
docker compose version
```

## Environment setup

Create a local `.env` from the sample file:

```bash
cp .env.example .env
```

Update values for your runtime. For Docker, database hosts should point to the
compose service names rather than `localhost`, for example:

```env
POSTGRES_HOST=postgres
MONGO_HOST=mongo
GOOGLE_CREDENTIALS_PATH=/opt/airflow/client_secret.json
```

Local-only secrets and generated files should not be committed:

```text
.env
client_secret.json
client_secret.token.json
google_tokens/
service_settings.json
```

## Google Drive OAuth

Place your Google OAuth client secret at one of these paths:

```text
client_secret.json
google_tokens/client_secret.json
```

Then run the first-run script. It will create `google_tokens/`, run the OAuth
flow, and save the token at `google_tokens/client_secret.token.json`.

## Run locally with Docker

First run on a new machine:

```bash
./scripts/first-run.sh
```

After the first initialization:

```bash
./scripts/start.sh
```

Airflow will be available at:

```text
http://localhost:8080
```

Default local login:

```text
admin / admin
```

To reset local containers and volumes:

```bash
docker compose down --volumes --remove-orphans
RESET_LOCAL_DATA=1 ./scripts/first-run.sh
```

## Run the pipeline from Python

Use the application entry point directly when you do not need the Airflow
scheduler:

```python
from data_ingest.application.pipeline import run_ingest_pipeline

record = run_ingest_pipeline(
    run_id="2026-05-27",
    execution_date="2026-05-27",
    source="google_drive",
    dest_path="/tmp/sts_data_ingestion/",
    file_id="<google_drive_file_id>",
)

print(record.status)
```

Smoke test helper:

```bash
PYTHONPATH=src uv run python run_pipeline_test.py --file-id <google_drive_file_id>
```

## Airflow DAGs

Main DAG:

```text
dags/dag_ingest.py
```

Default DAG flow:

```text
wait_for_google_drive_files -> run_ingest_pipeline -> send_summary_email
```

Important default params:

- `source`: `google_drive`
- `dest_path`: `/tmp/sts_data_ingestion/`
- `folder_id`: Google Drive folder id used by the sensor
- `file_id`: optional direct file id

## Tests

Run the unit tests:

```bash
PYTHONPATH=src uv run pytest -q tests
```

Run Airflow-focused tests:

```bash
PYTHONPATH=src:dags uv run pytest -q test-airflow
```

Validate imports and project structure:

```bash
PYTHONPATH=src uv run python validate.py
```

## Useful docs

- `markdown/first_run_setup.md`: detailed first-run Docker and OAuth guide
- `markdown/module_architecture.md`: module, component, and class diagrams
- `DEPENDENCIES.md`: dependency architecture notes

## Troubleshooting

If Google OAuth fails, remove the old token and rerun first-run:

```bash
rm -f google_tokens/client_secret.token.json client_secret.token.json
./scripts/first-run.sh
```

If Airflow cannot connect to databases, check that Docker `.env` values use
service hostnames such as `postgres` and `mongo`.

If a port is already in use, check the default local ports:

- Airflow UI: `8080`
- PostgreSQL host port: `5434`
- MongoDB host port: `27017`

```bash
lsof -i :8080
lsof -i :5434
lsof -i :27017
```
