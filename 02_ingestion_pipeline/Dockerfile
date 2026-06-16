FROM apache/airflow:3.2.1

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

WORKDIR /opt/airflow

RUN pip install --no-cache-dir \
    "pydantic>=2.0.0" \
    "pydantic-settings>=2.0.0" \
    "pymongo>=4.6.0" \
    "psycopg2-binary>=2.9.0" \
    "google-auth>=2.25.0" \
    "google-auth-oauthlib>=1.1.0" \
    "google-auth-httplib2>=0.2.0" \
    "google-api-python-client>=2.100.0" \
    "boto3>=1.28.0" \
    "requests>=2.31.0" \
    "python-dotenv>=1.0.0" \
    "tqdm>=4.67.3" \
    "pandas>=2.0.0" \
    "openpyxl>=3.1.0" \
    "openai>=1.0.0" \
    "asyncpg>=0.31.0"

ENV PYTHONPATH=/opt/airflow/src:/opt/airflow
