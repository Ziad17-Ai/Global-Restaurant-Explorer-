"""
DAG Syntax, AST, Zero-Side-Effect Parse, and Airflow DagBag Import Tests.

Runs cleanly both in a full Apache Airflow environment (exercising DagBag)
and in a lightweight Python 3.11 environment without Airflow installed
(exercising AST compilation and parse-time safety checks).
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import py_compile
import tempfile
import unittest
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
DAG_FILE = BUNDLE_ROOT / "dags" / "global_restaurant_explorer_etl_dag.py"
ADAPTER_FILE = BUNDLE_ROOT / "include" / "airflow_etl_adapter.py"

HAS_AIRFLOW = importlib.util.find_spec("airflow") is not None


class TestDAGSyntaxAndImport(unittest.TestCase):
    def test_python_files_compile_cleanly(self) -> None:
        """Both DAG and adapter files must compile without syntax errors (works on read-only mounts)."""
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(DAG_FILE), cfile=str(Path(tmp) / "dag.pyc"), doraise=True)
            py_compile.compile(str(ADAPTER_FILE), cfile=str(Path(tmp) / "adapter.pyc"), doraise=True)

    def test_dag_has_no_parse_time_heavy_imports_or_dynamic_start_date(self) -> None:
        """
        Verify at AST level that top-level DAG parsing does not import pandas,
        sqlalchemy, pymysql, or pipeline.etl, and does not call datetime.now().
        """
        source = DAG_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(DAG_FILE))

        forbidden_top_level_imports = {
            "pandas",
            "sqlalchemy",
            "pymysql",
            "sqlite3",
            "pipeline",
            "airflow_etl_adapter",
        }
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertNotIn(
                        top,
                        forbidden_top_level_imports,
                        f"Heavy/runtime import '{alias.name}' found at DAG top level.",
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                self.assertNotIn(
                    top,
                    forbidden_top_level_imports,
                    f"Heavy/runtime import 'from {node.module}' found at DAG top level.",
                )

        # Ensure datetime.now() / pendulum.now() is never used in DAG file
        self.assertNotIn("datetime.now(", source)
        self.assertNotIn("pendulum.now(", source)

    def test_no_hardcoded_secrets_in_dag_or_adapter(self) -> None:
        """Ensure neither DAG nor adapter embeds hardcoded credentials or connection strings."""
        for file_path in (DAG_FILE, ADAPTER_FILE):
            text = file_path.read_text(encoding="utf-8")
            self.assertNotIn("AccountKey=", text)
            self.assertNotIn("mysql+pymysql://", text)

    @unittest.skipUnless(HAS_AIRFLOW, "apache-airflow not installed in this environment")
    def test_airflow_dagbag_imports_without_errors(self) -> None:
        """Load the DAG via Airflow's real DagBag and verify zero import errors."""
        try:
            from airflow.dag_processing.dagbag import DagBag  # type: ignore
        except ImportError:
            from airflow.models import DagBag  # type: ignore

        kwargs = {"dag_folder": str(DAG_FILE.parent)}
        if "include_examples" in inspect.signature(DagBag.__init__).parameters:
            kwargs["include_examples"] = False
        dag_bag = DagBag(**kwargs)
        self.assertEqual(
            dag_bag.import_errors,
            {},
            f"Airflow DagBag reported import errors: {dag_bag.import_errors}",
        )
        self.assertIn("global_restaurant_explorer_etl", dag_bag.dags)


if __name__ == "__main__":
    unittest.main()
