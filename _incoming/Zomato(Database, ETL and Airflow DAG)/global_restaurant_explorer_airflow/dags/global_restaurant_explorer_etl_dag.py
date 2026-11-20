"""
Apache Airflow DAG: Global Restaurant Explorer Platform ETL Pipeline

Orchestrates the existing Bronze -> Silver -> Gold ETL implementation in
`global_restaurant_explorer_etl/pipeline/etl/` without duplicating business logic,
hardcoding secrets, or passing large datasets through XCom.

Target Runtime: Apache Airflow 3.4.0+ (Python 3.11+) using the TaskFlow SDK,
with automatic import fallback for Apache Airflow 2.10–2.11.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

# Ensure sibling `include/` directory is importable regardless of working directory
_DAG_DIR = Path(__file__).resolve().parent
_INCLUDE_DIR = _DAG_DIR.parent / "include"
if _INCLUDE_DIR.is_dir() and str(_INCLUDE_DIR) not in sys.path:
    sys.path.insert(0, str(_INCLUDE_DIR))

# Airflow 3.x Task SDK (primary) with Airflow 2.10+ fallback
try:
    from airflow.sdk import dag, get_current_context, task  # type: ignore
except ImportError:  # pragma: no cover - Airflow 2.x compatibility fallback
    from airflow.decorators import dag, task  # type: ignore
    from airflow.operators.python import get_current_context  # type: ignore


DEFAULT_ARGS: Dict[str, Any] = {
    "owner": "global_restaurant_explorer_data_eng",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(minutes=30),
}

# Static UTC start_date prevents Airflow 3.x DAG version inflation on every parse
START_DATE_UTC = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)

# Safe default: manual-only until explicitly enabled via AIRFLOW_ETL_SCHEDULE (e.g. "@daily")
SCHEDULE = os.getenv("AIRFLOW_ETL_SCHEDULE") or None


@dag(
    dag_id="global_restaurant_explorer_etl",
    description=(
        "Production Medallion (Bronze -> Silver -> Gold) ETL workflow for the "
        "Global Restaurant Explorer Platform orchestrating pipeline.etl modules."
    ),
    schedule=SCHEDULE,
    start_date=START_DATE_UTC,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["global-restaurant-explorer", "zomato", "etl", "medallion", "mysql"],
    params={
        "source_csv": "data/zomato_cleaned.csv",
        "mysql_conn_id": "mysql_zomato_explorer",
        "dry_run": False,
        "force": False,
        "batch_id": "",
        "max_quarantine_ratio": 1.0,
    },
)
def global_restaurant_explorer_etl() -> None:
    """TaskFlow DAG definition mapping each stage to real pipeline.etl functions."""

    @task(task_id="validate_runtime_config", retries=1, execution_timeout=timedelta(minutes=5))
    def validate_runtime_config() -> Dict[str, Any]:
        from airflow_etl_adapter import task_validate_runtime_config

        ctx = get_current_context()
        params = ctx.get("params") or {}
        dag_run = ctx.get("dag_run")
        dag_run_id = getattr(dag_run, "run_id", None) or ctx.get("run_id")

        return task_validate_runtime_config(
            dag_run_id=dag_run_id,
            mysql_conn_id=str(params.get("mysql_conn_id", "mysql_zomato_explorer")),
            source_csv=params.get("source_csv") or None,
            explicit_batch_id=params.get("batch_id") or None,
            dry_run=bool(params.get("dry_run", False)),
            force=bool(params.get("force", False)),
            max_quarantine_ratio=float(params.get("max_quarantine_ratio", 1.0)),
        )

    @task(task_id="validate_source_and_schema", retries=1, execution_timeout=timedelta(minutes=5))
    def validate_source_and_schema(runtime_ctx: Dict[str, Any]) -> Dict[str, Any]:
        from airflow_etl_adapter import task_validate_source_and_schema

        return task_validate_source_and_schema(runtime_ctx)

    @task(task_id="bronze_ingestion", retries=2, execution_timeout=timedelta(minutes=10))
    def bronze_ingestion(
        runtime_ctx: Dict[str, Any],
        source_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        from airflow_etl_adapter import task_bronze_ingestion

        return task_bronze_ingestion(runtime_ctx, source_ctx)

    @task(task_id="validate_and_quarantine", retries=1, execution_timeout=timedelta(minutes=15))
    def validate_and_quarantine(
        runtime_ctx: Dict[str, Any],
        bronze_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        from airflow_etl_adapter import task_validate_and_quarantine

        return task_validate_and_quarantine(runtime_ctx, bronze_ctx)

    @task(task_id="load_silver_layer", retries=2, execution_timeout=timedelta(minutes=20))
    def load_silver_layer(
        runtime_ctx: Dict[str, Any],
        validation_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        from airflow_etl_adapter import task_load_silver_layer

        return task_load_silver_layer(runtime_ctx, validation_ctx)

    @task(task_id="refresh_gold_views", retries=2, execution_timeout=timedelta(minutes=10))
    def refresh_gold_views(
        runtime_ctx: Dict[str, Any],
        silver_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        from airflow_etl_adapter import task_refresh_gold_views

        return task_refresh_gold_views(runtime_ctx, silver_ctx)

    @task(task_id="run_data_quality_checks", retries=1, execution_timeout=timedelta(minutes=10))
    def run_data_quality_checks(
        runtime_ctx: Dict[str, Any],
        validation_ctx: Dict[str, Any],
        silver_ctx: Dict[str, Any],
        gold_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        from airflow_etl_adapter import task_run_data_quality_checks

        return task_run_data_quality_checks(runtime_ctx, validation_ctx, silver_ctx, gold_ctx)

    @task(task_id="generate_pipeline_summary", retries=1, execution_timeout=timedelta(minutes=5))
    def generate_pipeline_summary(
        runtime_ctx: Dict[str, Any],
        source_ctx: Dict[str, Any],
        bronze_ctx: Dict[str, Any],
        validation_ctx: Dict[str, Any],
        silver_ctx: Dict[str, Any],
        gold_ctx: Dict[str, Any],
        dq_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        from airflow_etl_adapter import task_generate_pipeline_summary

        return task_generate_pipeline_summary(
            runtime_ctx,
            source_ctx,
            bronze_ctx,
            validation_ctx,
            silver_ctx,
            gold_ctx,
            dq_ctx,
        )

    # Explicit TaskFlow dependency graph
    runtime_ctx = validate_runtime_config()
    source_ctx = validate_source_and_schema(runtime_ctx)
    bronze_ctx = bronze_ingestion(runtime_ctx, source_ctx)
    validation_ctx = validate_and_quarantine(runtime_ctx, bronze_ctx)
    silver_ctx = load_silver_layer(runtime_ctx, validation_ctx)
    gold_ctx = refresh_gold_views(runtime_ctx, silver_ctx)
    dq_ctx = run_data_quality_checks(runtime_ctx, validation_ctx, silver_ctx, gold_ctx)
    generate_pipeline_summary(
        runtime_ctx,
        source_ctx,
        bronze_ctx,
        validation_ctx,
        silver_ctx,
        gold_ctx,
        dq_ctx,
    )


global_restaurant_explorer_etl()
