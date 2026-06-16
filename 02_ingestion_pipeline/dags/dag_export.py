from __future__ import annotations
from datetime import datetime, timezone, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.sensors.external_task import ExternalTaskSensor

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from wrapper.export_wrapper import wrap_export_to_ggdrive

with DAG(
    dag_id = "dag_export",
    schedule = "@daily",
    start_date = datetime(2026, 4, 1, tzinfo = timezone.utc),
    catchup = False,
    tags = ["sts", "pipeline"],
) as dag:
    wait_for_pipeline = ExternalTaskSensor(
        task_id = "wait_for_pipeline",
        external_dag_id = "dag_ingest",
        execution_delta = timedelta(hours = 4),
        external_task_id = "run_ingest_pipeline",
        allowed_states = ["success"],
        mode = "reschedule",
        timeout = 3600,
    )

    export_to_ggdrive = PythonOperator(
        task_id = "export_to_ggdrive",
        python_callable = wrap_export_to_ggdrive
    )
    
    wait_for_pipeline >> export_to_ggdrive