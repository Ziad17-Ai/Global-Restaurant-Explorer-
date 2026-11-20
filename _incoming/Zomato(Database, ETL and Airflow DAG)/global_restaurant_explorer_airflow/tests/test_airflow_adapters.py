"""
Unit Tests for `include/airflow_etl_adapter.py`.

Covers:
- Configuration validation & Airflow Connection overlay
- Secret redaction in logs
- Deterministic 36-char retry-safe batch_id derivation
- Missing CSV dataset & missing SQL file handling
- Database connection failure handling
- Real ETL task invocation (mocked pipeline.etl modules)
- Exception propagation (so Airflow marks tasks FAILED)
- Retry-safe Bronze ingestion (FileExistsError) and DQ/quarantine cleanup
- Quality gate enforcement & post-load reconciliation
- Small JSON-serializable XCom payloads (no DataFrames or secrets)
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIR = BUNDLE_ROOT / "include"
if str(INCLUDE_DIR) not in sys.path:
    sys.path.insert(0, str(INCLUDE_DIR))

import airflow_etl_adapter as adapter  # noqa: E402


def _create_fake_project_tree(base: Path, with_sql: bool = True, with_csv: bool = True) -> Path:
    """Create a minimal temporary directory mimicking global_restaurant_explorer_etl."""
    (base / "pipeline" / "etl").mkdir(parents=True, exist_ok=True)
    if with_sql:
        (base / "sql" / "migrations").mkdir(parents=True, exist_ok=True)
        (base / "sql" / "validation").mkdir(parents=True, exist_ok=True)
        (base / "sql" / "migrations" / "001_create_etl_metadata.sql").write_text("-- 001\n", encoding="utf-8")
        (base / "sql" / "migrations" / "002_create_gold_views.sql").write_text("-- 002\n", encoding="utf-8")
        (base / "sql" / "validation" / "etl_validation_queries.sql").write_text("-- val\n", encoding="utf-8")
    if with_csv:
        (base / "data").mkdir(parents=True, exist_ok=True)
        header = (
            "Restaurant ID,Restaurant Name,Country Code,City,Address,Locality,"
            "Locality Verbose,Longitude,Latitude,Cuisines,Average Cost for two,"
            "Currency,Has Table booking,Has Online delivery,Is delivering now,"
            "Switch to order menu,Price range,Aggregate rating,Rating color,Rating text,Votes\n"
        )
        row = (
            '6317637,Le Petit Souffle,162,Makati City,"Addr","Loc","Loc V",'
            '121.027535,14.565443,"French, Japanese",80.04,Dollar($),Yes,No,No,No,3,4.8,Dark Green,Excellent,314\n'
        )
        (base / "data" / "zomato_cleaned.csv").write_text(header + row, encoding="utf-8")
    return base


@dataclass(frozen=True)
class _FakeETLConfig:
    db_dialect: str = "mysql"
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "zomato_restaurant_explorer"
    db_user: str = "etl_user"
    db_password: str = "super_secret_pw"
    db_pool_size: int = 5
    db_connect_timeout: int = 15
    sqlite_db_path: Path = Path("data/zomato_test.sqlite")
    storage_backend: str = "local"
    bronze_local_path: Path = Path("data/bronze")
    quarantine_path: Path = Path("data/quarantine")
    reports_path: Path = Path("data/reports")
    logs_path: Path = Path("logs")
    azure_connection_string: Optional[str] = None
    azure_account_url: Optional[str] = None
    azure_container: str = "bronze-zomato"
    project_root: Path = Path(".")

    @classmethod
    def from_env(cls, env_file=None, project_root=None):
        root = Path(project_root) if project_root else Path(".")
        return cls(
            project_root=root,
            bronze_local_path=root / "data" / "bronze",
            quarantine_path=root / "data" / "quarantine",
            reports_path=root / "data" / "reports",
            logs_path=root / "logs",
        )

    def safe_summary(self) -> Dict[str, Any]:
        return {
            "db_dialect": self.db_dialect,
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "db_user": self.db_user,
            "storage_backend": self.storage_backend,
            "azure_configured": bool(self.azure_connection_string or self.azure_account_url),
        }


def _install_mock_pipeline_modules(
    db_manager_cls: Any,
    meta_repo_cls: Any,
    extract_fn: Any = None,
    bronze_fn: Any = None,
    validate_fn: Any = None,
    quarantine_fn: Any = None,
    transform_fn: Any = None,
    load_silver_fn: Any = None,
    build_gold_fn: Any = None,
    report_fn: Any = None,
    config_cls: Any = _FakeETLConfig,
) -> Dict[str, Any]:
    """Inject mock `pipeline.etl.*` modules into sys.modules for isolated unit testing."""
    mods: Dict[str, Any] = {}
    for name in (
        "pipeline",
        "pipeline.etl",
        "pipeline.etl.config",
        "pipeline.etl.database",
        "pipeline.etl.extract",
        "pipeline.etl.bronze",
        "pipeline.etl.validation",
        "pipeline.etl.quarantine",
        "pipeline.etl.transform",
        "pipeline.etl.load_silver",
        "pipeline.etl.build_gold",
        "pipeline.etl.metadata",
        "pipeline.etl.reporting",
    ):
        mods[name] = types.ModuleType(name)

    mods["pipeline.etl.config"].ETLConfig = config_cls
    mods["pipeline.etl.database"].DatabaseManager = db_manager_cls
    mods["pipeline.etl.metadata"].MetadataRepository = meta_repo_cls
    mods["pipeline.etl.extract"].compute_sha256 = lambda p: "a" * 64
    mods["pipeline.etl.extract"].validate_csv_schema = lambda cols: ([], [])
    mods["pipeline.etl.extract"].extract_csv = extract_fn or MagicMock()
    mods["pipeline.etl.bronze"].ingest_to_bronze = bronze_fn or MagicMock()
    mods["pipeline.etl.validation"].validate_dataframe = validate_fn or MagicMock()
    mods["pipeline.etl.quarantine"].write_local_quarantine = quarantine_fn or MagicMock()
    mods["pipeline.etl.transform"].transform_to_silver = transform_fn or MagicMock()
    mods["pipeline.etl.load_silver"].load_silver_layer = load_silver_fn or MagicMock()
    mods["pipeline.etl.build_gold"].build_gold_views = build_gold_fn or MagicMock()
    mods["pipeline.etl.reporting"].write_execution_reports = report_fn or MagicMock()
    return mods


class TestAirflowAdapters(unittest.TestCase):
    def test_redact_secrets(self) -> None:
        raw = "Failed connecting to mysql+pymysql://root:MyS3cr3t!@localhost:3306/db password=TopSecret token:abc123"
        redacted = adapter.redact_secrets(raw)
        self.assertNotIn("MyS3cr3t!", redacted)
        self.assertNotIn("TopSecret", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertIn("***REDACTED***", redacted)

    def test_derive_batch_id_deterministic_and_length_checked(self) -> None:
        b1 = adapter.derive_batch_id(dag_run_id="manual__2026-11-19T22:00:00+00:00")
        b2 = adapter.derive_batch_id(dag_run_id="manual__2026-11-19T22:00:00+00:00")
        self.assertEqual(b1, b2)
        self.assertEqual(len(b1), 36)

        with self.assertRaises(ValueError):
            adapter.derive_batch_id(explicit_batch_id="x" * 37)

    def test_build_etl_config_overlays_airflow_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_conn = types.SimpleNamespace(
                host="mysql-prod.internal",
                port=3307,
                schema="zomato_prod",
                login="airflow_etl",
                password="conn_secret_password",
            )
            mods = _install_mock_pipeline_modules(MagicMock(), MagicMock())
            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=fake_conn):
                    cfg = adapter.build_etl_config(project_root=str(root), mysql_conn_id="mysql_zomato_explorer")
                    self.assertEqual(cfg.db_host, "mysql-prod.internal")
                    self.assertEqual(cfg.db_port, 3307)
                    self.assertEqual(cfg.db_name, "zomato_prod")
                    self.assertEqual(cfg.db_user, "airflow_etl")
                    self.assertEqual(cfg.db_password, "conn_secret_password")

    def test_validate_runtime_config_db_failure_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_db = MagicMock()
            fake_db.test_connection.return_value = False
            mods = _install_mock_pipeline_modules(MagicMock(return_value=fake_db), MagicMock())
            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=None):
                    with self.assertRaises(ConnectionError):
                        adapter.task_validate_runtime_config(
                            dag_run_id="run-1",
                            project_root=str(root),
                            dry_run=False,
                        )
            fake_db.close.assert_called_once()

    def test_validate_runtime_config_returns_small_secret_free_xcom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_db = MagicMock()
            fake_db.test_connection.return_value = True
            mods = _install_mock_pipeline_modules(MagicMock(return_value=fake_db), MagicMock())
            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=None):
                    res = adapter.task_validate_runtime_config(
                        dag_run_id="run-safe",
                        project_root=str(root),
                        dry_run=False,
                    )
            serialized = json.dumps(res)
            self.assertLess(len(serialized), 2048)
            self.assertNotIn("super_secret_pw", serialized)
            self.assertTrue(res["db_connected"])

    def test_missing_dataset_and_missing_sql_raise_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_no_csv = _create_fake_project_tree(Path(tmp) / "no_csv", with_sql=True, with_csv=False)
            ctx_no_csv = {
                "batch_id": "b1",
                "project_root": str(root_no_csv),
                "source_csv_path": str(root_no_csv / "data" / "zomato_cleaned.csv"),
                "mysql_conn_id": "mysql_zomato_explorer",
                "dry_run": True,
                "force": False,
            }
            with self.assertRaises(FileNotFoundError):
                adapter.task_validate_source_and_schema(ctx_no_csv)

            root_no_sql = _create_fake_project_tree(Path(tmp) / "no_sql", with_sql=False, with_csv=True)
            ctx_no_sql = {
                "batch_id": "b2",
                "project_root": str(root_no_sql),
                "source_csv_path": str(root_no_sql / "data" / "zomato_cleaned.csv"),
                "mysql_conn_id": "mysql_zomato_explorer",
                "dry_run": True,
                "force": False,
            }
            with self.assertRaises(FileNotFoundError):
                adapter.task_validate_source_and_schema(ctx_no_sql)

    def test_bronze_ingestion_retry_safe_on_file_exists_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_extract = types.SimpleNamespace(
                file_name="zomato_cleaned.csv",
                source_path=root / "data" / "zomato_cleaned.csv",
                file_hash_sha256="a" * 64,
                file_size_bytes=1234,
                row_count=1,
            )
            fake_conn = MagicMock()
            fake_conn.fetchone.return_value = ("existing-batch",)
            fake_db = MagicMock()
            fake_db.transaction.return_value.__enter__.return_value = fake_conn
            fake_meta = MagicMock()

            mods = _install_mock_pipeline_modules(
                db_manager_cls=MagicMock(return_value=fake_db),
                meta_repo_cls=MagicMock(return_value=fake_meta),
                extract_fn=MagicMock(return_value=fake_extract),
                bronze_fn=MagicMock(side_effect=FileExistsError("batch exists")),
            )
            runtime_ctx = {
                "batch_id": "existing-batch",
                "project_root": str(root),
                "source_csv_path": str(root / "data" / "zomato_cleaned.csv"),
                "mysql_conn_id": "mysql_zomato_explorer",
                "dry_run": False,
                "force": False,
            }
            source_ctx = {"duplicate_source_detected": False}
            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=None):
                    res = adapter.task_bronze_ingestion(runtime_ctx, source_ctx)

            self.assertEqual(res["bronze_status"], "ALREADY_STORED_ON_RETRY")
            fake_meta.register_batch_start.assert_not_called()
            fake_meta.record_stage_run.assert_called_once()

    def test_validation_quality_gate_fails_when_threshold_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_extract = types.SimpleNamespace(dataframe=MagicMock(), row_count=10)
            fake_validation = types.SimpleNamespace(
                valid_df=[1, 2, 3, 4, 5],  # 5 accepted
                quarantine_records=[object()] * 5,  # 5 rejected (50%)
                issues=[],
                summary_by_severity={"ERROR": 5},
                summary_by_type={"INVALID_RATING": 5},
                exact_duplicate_count=0,
                duplicate_restaurant_id_count=0,
            )
            mods = _install_mock_pipeline_modules(
                db_manager_cls=MagicMock(),
                meta_repo_cls=MagicMock(),
                extract_fn=MagicMock(return_value=fake_extract),
                validate_fn=MagicMock(return_value=fake_validation),
            )
            runtime_ctx = {
                "batch_id": "dq-fail-batch",
                "project_root": str(root),
                "source_csv_path": str(root / "data" / "zomato_cleaned.csv"),
                "mysql_conn_id": "mysql_zomato_explorer",
                "dry_run": True,
                "max_quarantine_ratio": 0.10,
            }
            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=None):
                    with self.assertRaises(ValueError):
                        adapter.task_validate_and_quarantine(runtime_ctx, {})

    def test_post_load_reconciliation_catches_row_count_mismatch(self) -> None:
        runtime_ctx = {"batch_id": "rec-1", "dry_run": False}
        validation_ctx = {"accepted_rows": 100}
        silver_ctx = {
            "silver_load": {
                "table_counts": {"stg_zomato_cleaned": 100, "restaurants": 99},
            }
        }
        gold_ctx = {
            "views_verified": {"v_restaurant_explorer": 99, "gold_restaurant_search": 99},
        }
        with self.assertRaises(ValueError):
            adapter.task_run_data_quality_checks(runtime_ctx, validation_ctx, silver_ctx, gold_ctx)

    def test_generate_pipeline_summary_calls_reporting_and_completes_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_db = MagicMock()
            fake_meta = MagicMock()
            json_out = root / "data" / "reports" / "etl_report_b1.json"
            md_out = root / "data" / "reports" / "dq_report_b1.md"
            report_mock = MagicMock(return_value=(json_out, md_out))

            mods = _install_mock_pipeline_modules(
                db_manager_cls=MagicMock(return_value=fake_db),
                meta_repo_cls=MagicMock(return_value=fake_meta),
                report_fn=report_mock,
            )
            runtime_ctx = {
                "batch_id": "b1",
                "dag_run_id": "manual__1",
                "project_root": str(root),
                "mysql_conn_id": "mysql_zomato_explorer",
                "dry_run": False,
                "force": False,
                "duration_ms": 10.0,
            }
            source_ctx = {"source_file_name": "zomato_cleaned.csv", "source_file_hash": "a" * 64, "source_file_size": 100, "duration_ms": 5.0}
            bronze_ctx = {"bronze_status": "STORED", "bronze_uri": "/bronze/x", "bronze_metadata_uri": "/bronze/m", "duration_ms": 2.0}
            validation_ctx = {"extracted_rows": 10, "accepted_rows": 9, "rejected_rows": 1, "total_issues": 1, "duration_ms": 3.0}
            silver_ctx = {"silver_transform": {"restaurants": 9}, "silver_load": {"restaurants_inserted": 9}, "duration_ms": 4.0}
            gold_ctx = {"views_verified": {"gold_restaurant_search": 9}, "query_timings_ms": {"gold_restaurant_search": 1.2}, "duration_ms": 2.0}
            dq_ctx = {"checks_passed": True, "duration_ms": 1.0}

            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=None):
                    res = adapter.task_generate_pipeline_summary(
                        runtime_ctx, source_ctx, bronze_ctx, validation_ctx, silver_ctx, gold_ctx, dq_ctx
                    )

            self.assertEqual(res["status"], "PARTIAL_SUCCESS")
            fake_meta.complete_batch.assert_called_once_with(
                batch_id="b1",
                status="PARTIAL_SUCCESS",
                accepted_row_count=9,
                rejected_row_count=1,
            )
            report_mock.assert_called_once()
            # Confirm XCom output is small and JSON-serializable
            self.assertLess(len(json.dumps(res)), 2048)

    def test_bronze_ingestion_propagates_prior_uri_on_duplicate_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_extract = types.SimpleNamespace(
                file_name="zomato_cleaned.csv",
                source_path=root / "data" / "zomato_cleaned.csv",
                file_hash_sha256="a" * 64,
                file_size_bytes=1234,
                row_count=1,
            )
            fake_conn = MagicMock()
            fake_conn.fetchone.return_value = None
            fake_db = MagicMock()
            fake_db.transaction.return_value.__enter__.return_value = fake_conn
            fake_meta = MagicMock()
            fake_meta.find_successful_batch_by_hash.return_value = {
                "batch_id": "prior-batch",
                "bronze_uri": "/bronze/prior/zomato_cleaned.csv",
            }
            mods = _install_mock_pipeline_modules(
                db_manager_cls=MagicMock(return_value=fake_db),
                meta_repo_cls=MagicMock(return_value=fake_meta),
                extract_fn=MagicMock(return_value=fake_extract),
            )
            runtime_ctx = {
                "batch_id": "dup-batch",
                "project_root": str(root),
                "source_csv_path": str(root / "data" / "zomato_cleaned.csv"),
                "mysql_conn_id": "mysql_zomato_explorer",
                "dry_run": False,
                "force": False,
            }
            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=None):
                    res = adapter.task_bronze_ingestion(runtime_ctx, {"duplicate_source_detected": True})
            self.assertEqual(res["bronze_status"], "SKIPPED_EXISTING_HASH")
            self.assertEqual(res["bronze_uri"], "/bronze/prior/zomato_cleaned.csv")

    def test_validation_quality_gate_marks_batch_failed_when_not_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _create_fake_project_tree(Path(tmp))
            fake_extract = types.SimpleNamespace(dataframe=MagicMock(), row_count=2)
            fake_validation = types.SimpleNamespace(
                valid_df=[],
                quarantine_records=[object(), object()],
                issues=[],
                summary_by_severity={"ERROR": 2},
                summary_by_type={"INVALID_AVERAGE_COST": 2},
                exact_duplicate_count=0,
                duplicate_restaurant_id_count=0,
            )
            fake_db = MagicMock()
            fake_meta = MagicMock()
            mods = _install_mock_pipeline_modules(
                db_manager_cls=MagicMock(return_value=fake_db),
                meta_repo_cls=MagicMock(return_value=fake_meta),
                extract_fn=MagicMock(return_value=fake_extract),
                validate_fn=MagicMock(return_value=fake_validation),
            )
            runtime_ctx = {
                "batch_id": "fail-batch-1",
                "project_root": str(root),
                "source_csv_path": str(root / "data" / "zomato_cleaned.csv"),
                "mysql_conn_id": "mysql_zomato_explorer",
                "dry_run": False,
                "max_quarantine_ratio": 1.0,
            }
            with patch.dict(sys.modules, mods):
                with patch.object(adapter, "_get_airflow_connection", return_value=None):
                    with self.assertRaises(ValueError):
                        adapter.task_validate_and_quarantine(runtime_ctx, {})
            fake_meta.complete_batch.assert_called_once()
            self.assertEqual(fake_meta.complete_batch.call_args.kwargs["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
