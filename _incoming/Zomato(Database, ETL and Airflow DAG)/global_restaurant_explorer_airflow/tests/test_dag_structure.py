"""
DAG Structure, Configuration, Task IDs, and Dependency Graph Verification Tests.

When `apache-airflow` is installed, inspects the real DagBag DAG object.
When `apache-airflow` is not installed (offline CI/sandbox), executes the DAG
module against a minimal TaskFlow recording stub to verify exact DAG metadata,
task IDs, and dependency edges without skipping structural checks.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import types
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
DAG_FILE = BUNDLE_ROOT / "dags" / "global_restaurant_explorer_etl_dag.py"

EXPECTED_DAG_ID = "global_restaurant_explorer_etl"
EXPECTED_TASK_IDS = [
    "validate_runtime_config",
    "validate_source_and_schema",
    "bronze_ingestion",
    "validate_and_quarantine",
    "load_silver_layer",
    "refresh_gold_views",
    "run_data_quality_checks",
    "generate_pipeline_summary",
]
EXPECTED_EDGES: Set[Tuple[str, str]] = {
    ("validate_runtime_config", "validate_source_and_schema"),
    ("validate_runtime_config", "bronze_ingestion"),
    ("validate_source_and_schema", "bronze_ingestion"),
    ("validate_runtime_config", "validate_and_quarantine"),
    ("bronze_ingestion", "validate_and_quarantine"),
    ("validate_runtime_config", "load_silver_layer"),
    ("validate_and_quarantine", "load_silver_layer"),
    ("validate_runtime_config", "refresh_gold_views"),
    ("load_silver_layer", "refresh_gold_views"),
    ("validate_runtime_config", "run_data_quality_checks"),
    ("validate_and_quarantine", "run_data_quality_checks"),
    ("load_silver_layer", "run_data_quality_checks"),
    ("refresh_gold_views", "run_data_quality_checks"),
    ("validate_runtime_config", "generate_pipeline_summary"),
    ("validate_source_and_schema", "generate_pipeline_summary"),
    ("bronze_ingestion", "generate_pipeline_summary"),
    ("validate_and_quarantine", "generate_pipeline_summary"),
    ("load_silver_layer", "generate_pipeline_summary"),
    ("refresh_gold_views", "generate_pipeline_summary"),
    ("run_data_quality_checks", "generate_pipeline_summary"),
}


def _load_dag_with_stub() -> Dict[str, Any]:
    """Load the DAG module with a minimal Airflow SDK recorder when Airflow is absent."""
    recorded: Dict[str, Any] = {"dags": {}, "tasks": {}, "edges": set()}

    class _XComRef:
        def __init__(self, task_id: str) -> None:
            self.task_id = task_id

    def fake_dag(**kwargs: Any):
        def decorator(fn):
            def wrapper():
                recorded["dags"][kwargs["dag_id"]] = kwargs
                return fn()
            return wrapper
        return decorator

    def fake_task(**kwargs: Any):
        def decorator(fn):
            task_id = kwargs.get("task_id", fn.__name__)
            recorded["tasks"][task_id] = kwargs

            def task_call(*args: Any, **call_kwargs: Any) -> _XComRef:
                for val in list(args) + list(call_kwargs.values()):
                    if isinstance(val, _XComRef):
                        recorded["edges"].add((val.task_id, task_id))
                return _XComRef(task_id)

            return task_call
        return decorator

    fake_airflow = types.ModuleType("airflow")
    fake_sdk = types.ModuleType("airflow.sdk")
    fake_sdk.dag = fake_dag  # type: ignore[attr-defined]
    fake_sdk.task = fake_task  # type: ignore[attr-defined]
    fake_sdk.get_current_context = lambda: {}  # type: ignore[attr-defined]

    saved = {k: sys.modules.get(k) for k in ("airflow", "airflow.sdk", "_dag_under_test")}
    sys.modules["airflow"] = fake_airflow
    sys.modules["airflow.sdk"] = fake_sdk
    try:
        spec = importlib.util.spec_from_file_location("_dag_under_test", DAG_FILE)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, prev in saved.items():
            if prev is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = prev

    return recorded


class TestDAGStructure(unittest.TestCase):
    def test_dag_metadata_tasks_and_dependencies(self) -> None:
        if importlib.util.find_spec("airflow") is not None:
            try:
                from airflow.dag_processing.dagbag import DagBag  # type: ignore
            except ImportError:
                from airflow.models import DagBag  # type: ignore

            kwargs = {"dag_folder": str(DAG_FILE.parent)}
            if "include_examples" in inspect.signature(DagBag.__init__).parameters:
                kwargs["include_examples"] = False
            dag_bag = DagBag(**kwargs)
            self.assertEqual(dag_bag.import_errors, {})
            dag_obj = dag_bag.get_dag(EXPECTED_DAG_ID)
            self.assertIsNotNone(dag_obj)
            self.assertFalse(dag_obj.catchup)
            self.assertEqual(dag_obj.max_active_runs, 1)
            self.assertIsNone(dag_obj.schedule)
            self.assertEqual(dag_obj.start_date.utcoffset(), timedelta(0))
            self.assertEqual(sorted(dag_obj.task_ids), sorted(EXPECTED_TASK_IDS))

            actual_edges: Set[Tuple[str, str]] = set()
            for task_id in dag_obj.task_ids:
                t = dag_obj.get_task(task_id)
                for downstream in t.downstream_task_ids:
                    actual_edges.add((task_id, downstream))
            self.assertEqual(actual_edges, EXPECTED_EDGES)
        else:
            recorded = _load_dag_with_stub()
            self.assertIn(EXPECTED_DAG_ID, recorded["dags"])
            dag_meta = recorded["dags"][EXPECTED_DAG_ID]
            self.assertFalse(dag_meta["catchup"])
            self.assertEqual(dag_meta["max_active_runs"], 1)
            self.assertIsNone(dag_meta["schedule"])
            self.assertEqual(dag_meta["start_date"].tzinfo, timezone.utc)
            self.assertEqual(dag_meta["default_args"]["retries"], 2)
            self.assertEqual(dag_meta["default_args"]["retry_delay"], timedelta(minutes=2))
            self.assertEqual(list(recorded["tasks"].keys()), EXPECTED_TASK_IDS)
            self.assertEqual(recorded["edges"], EXPECTED_EDGES)


if __name__ == "__main__":
    unittest.main()