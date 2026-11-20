"""
Airflow-to-ETL Integration Adapter for Global Restaurant Explorer Platform.

Bridges Apache Airflow tasks to the real, tested ETL modules in
`global_restaurant_explorer_etl/pipeline/etl/` without duplicating business logic,
exposing secrets, or passing large datasets through XCom.

All database connections, Airflow Connection lookups, and `pipeline.etl` imports
happen lazily inside task execution functions — NEVER at module import / DAG
parse time.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("airflow.task.global_restaurant_explorer_etl")

# Fixed namespace UUID for deterministic retry-safe batch_id generation (<= 36 chars for MySQL CHAR(36))
_BATCH_UUID_NAMESPACE = uuid.UUID("7f3b9a60-4d8e-5c12-9b4a-2e6f8c1d3a90")

REQUIRED_SQL_RELATIVE_PATHS: Tuple[str, ...] = (
    "sql/migrations/001_create_etl_metadata.sql",
    "sql/migrations/002_create_gold_views.sql",
    "sql/validation/etl_validation_queries.sql",
)

_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|connection_string|accountkey|sig)\s*([=:]\s*)([^\s;,&\"']+)"
)


def redact_secrets(text: str) -> str:
    """Redact potential credentials, passwords, or connection strings from log messages."""
    if not text:
        return text
    redacted = _SECRET_PATTERN.sub(r"\1\2***REDACTED***", text)
    # Redact user:password@host patterns in URIs
    redacted = re.sub(r"(://[^:/@\s]+:)([^@\s]+)(@)", r"\1***REDACTED***\3", redacted)
    return redacted


def derive_batch_id(dag_run_id: Optional[str] = None, explicit_batch_id: Optional[str] = None) -> str:
    """
    Generate a deterministic, retry-safe batch ID fitting MySQL CHAR(36).

    - If `explicit_batch_id` is provided, validate length <= 36 and return it.
    - If `dag_run_id` is provided, derive a deterministic UUIDv5 (36 chars) so
      Airflow task retries within the same DAG run share the exact same batch_id.
    - Otherwise fall back to a random UUIDv4.
    """
    if explicit_batch_id:
        cleaned = str(explicit_batch_id).strip()
        if not cleaned:
            raise ValueError("batch_id cannot be empty.")
        if len(cleaned) > 36:
            raise ValueError(
                f"batch_id '{cleaned}' is {len(cleaned)} chars; MySQL etl_ingestion_batches.batch_id is CHAR(36)."
            )
        return cleaned
    if dag_run_id:
        return str(uuid.uuid5(_BATCH_UUID_NAMESPACE, str(dag_run_id)))
    return str(uuid.uuid4())


def resolve_project_root(project_root: Optional[str] = None) -> Path:
    """
    Deterministically resolve the `global_restaurant_explorer_etl` project root
    without depending on the process current working directory.
    """
    candidates: List[Path] = []
    if project_root:
        candidates.append(Path(project_root))
    env_root = os.getenv("ETL_PROJECT_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root))
    # Common container mount & sibling layouts
    here = Path(__file__).resolve()
    candidates.extend(
        [
            Path("/opt/airflow/etl_project"),
            here.parents[1],
            here.parents[2],
            here.parents[2] / "global_restaurant_explorer_etl",
        ]
    )

    for candidate in candidates:
        if (candidate / "pipeline" / "etl").is_dir():
            return candidate.resolve()

    searched = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(
        f"Could not locate ETL project root containing 'pipeline/etl/'. "
        f"Set ETL_PROJECT_ROOT to the global_restaurant_explorer_etl directory. Searched: {searched}"
    )


def ensure_project_on_sys_path(project_root: Path) -> None:
    """Ensure the resolved ETL project root is importable on sys.path."""
    root_str = str(project_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _get_airflow_connection(conn_id: str) -> Optional[Any]:
    """
    Retrieve an Airflow Connection at task execution time via BaseHook.
    Returns None if Airflow is unavailable or the connection is not defined
    (allowing clean fallback to environment variables / SQLite test configs).
    """
    try:
        try:
            from airflow.sdk.bases.hook import BaseHook  # type: ignore
        except ImportError:  # pragma: no cover - Airflow 2.x fallback
            from airflow.hooks.base import BaseHook  # type: ignore

        return BaseHook.get_connection(conn_id)
    except Exception as exc:  # pragma: no cover - depends on live Airflow metadata DB
        logger.info(
            "Airflow Connection '%s' not loaded (%s); falling back to ETLConfig environment variables.",
            conn_id,
            redact_secrets(str(exc)),
        )
        return None


def build_etl_config(
    project_root: Optional[str] = None,
    mysql_conn_id: str = "mysql_zomato_explorer",
    env_file: Optional[str] = None,
    use_airflow_connection: bool = True,
) -> Any:
    """
    Build the real `pipeline.etl.config.ETLConfig`, optionally overlaying
    database credentials from an Airflow Connection so secrets never live in
    the DAG or deployment bundle.
    """
    root = resolve_project_root(project_root)
    ensure_project_on_sys_path(root)

    from pipeline.etl.config import ETLConfig  # type: ignore

    env_path = Path(env_file) if env_file else None
    config = ETLConfig.from_env(env_file=env_path, project_root=root)

    if use_airflow_connection and config.db_dialect == "mysql":
        conn = _get_airflow_connection(mysql_conn_id)
        if conn is not None:
            overrides: Dict[str, Any] = {}
            if getattr(conn, "host", None):
                overrides["db_host"] = str(conn.host)
            if getattr(conn, "port", None):
                overrides["db_port"] = int(conn.port)
            if getattr(conn, "schema", None):
                overrides["db_name"] = str(conn.schema)
            if getattr(conn, "login", None):
                overrides["db_user"] = str(conn.login)
            if getattr(conn, "password", None) is not None:
                overrides["db_password"] = str(conn.password)
            if overrides:
                config = replace(config, **overrides)
                logger.info(
                    "Applied MySQL connection settings from Airflow Connection '%s' (host=%s, db=%s).",
                    mysql_conn_id,
                    config.db_host,
                    config.db_name,
                )

    return config


def resolve_source_csv_path(project_root: Path, source_csv: Optional[str] = None) -> Path:
    """Resolve the input CSV path relative to project_root when not absolute."""
    raw = source_csv or os.getenv("ETL_SOURCE_CSV", "data/zomato_cleaned.csv")
    path = Path(raw)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def _resolve_readable_csv(runtime_ctx: Dict[str, Any], bronze_uri: Optional[str] = None) -> Path:
    """Prefer the immutable local Bronze snapshot when present; otherwise use source_csv_path."""
    if bronze_uri and not str(bronze_uri).startswith("az://"):
        bp = Path(str(bronze_uri))
        if bp.is_file():
            return bp
    return Path(runtime_ctx["source_csv_path"])


def _mark_batch_failed(
    config: Any,
    batch_id: str,
    stage: str,
    started_at: str,
    error_message: str,
    accepted_rows: int = 0,
    rejected_rows: int = 0,
) -> None:
    """Record stage failure and transition etl_ingestion_batches out of RUNNING."""
    try:
        from pipeline.etl.database import DatabaseManager  # type: ignore
        from pipeline.etl.metadata import MetadataRepository  # type: ignore

        safe_err = redact_secrets(error_message)
        db = DatabaseManager(config)
        try:
            meta = MetadataRepository(db)
            meta.record_stage_run(
                batch_id=batch_id,
                stage=stage,
                status="FAILED",
                started_at=started_at,
                accepted_count=accepted_rows,
                rejected_count=rejected_rows,
                error_message=safe_err,
            )
            meta.complete_batch(
                batch_id=batch_id,
                status="FAILED",
                accepted_row_count=accepted_rows,
                rejected_row_count=rejected_rows,
                error_message=safe_err,
            )
        finally:
            db.close()
    except Exception as meta_exc:
        logger.warning("Failed to record FAILED batch status for batch_id=%s: %s", batch_id, redact_secrets(str(meta_exc)))


# ---------------------------------------------------------------------------
# Task 1: Validate Runtime Configuration & Database Connectivity
# ---------------------------------------------------------------------------
def task_validate_runtime_config(
    dag_run_id: Optional[str] = None,
    project_root: Optional[str] = None,
    mysql_conn_id: str = "mysql_zomato_explorer",
    source_csv: Optional[str] = None,
    explicit_batch_id: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    max_quarantine_ratio: float = 1.0,
) -> Dict[str, Any]:
    """
    Validate ETL configuration, resolve deterministic batch_id, and test DB connectivity.
    Returns strictly small, credential-free metadata for XCom.
    """
    t0 = time.perf_counter()
    batch_id = derive_batch_id(dag_run_id=dag_run_id, explicit_batch_id=explicit_batch_id)
    root = resolve_project_root(project_root)
    config = build_etl_config(project_root=str(root), mysql_conn_id=mysql_conn_id)
    csv_path = resolve_source_csv_path(root, source_csv)

    if config.storage_backend not in ("local", "azure"):
        raise ValueError(f"Unsupported STORAGE_BACKEND: '{config.storage_backend}'")
    if config.storage_backend == "azure" and not (
        config.azure_connection_string or config.azure_account_url
    ):
        raise ValueError(
            "STORAGE_BACKEND=azure requires AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL."
        )
    if not (0.0 <= max_quarantine_ratio <= 1.0):
        raise ValueError(f"max_quarantine_ratio must be between 0.0 and 1.0, got {max_quarantine_ratio}")

    db_connected = False
    if not dry_run:
        from pipeline.etl.database import DatabaseManager  # type: ignore

        db = DatabaseManager(config)
        try:
            if not db.test_connection():
                raise ConnectionError(
                    f"Database connectivity check failed for dialect={config.db_dialect} "
                    f"(summary={config.safe_summary()})."
                )
            db_connected = True
        except Exception as exc:
            logger.error("Database connectivity check failed: %s", redact_secrets(str(exc)))
            raise
        finally:
            db.close()

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    summary = config.safe_summary()
    logger.info(
        "Validated runtime config | dag_run_id=%s | batch_id=%s | db_dialect=%s | storage=%s | dry_run=%s | ms=%.2f",
        dag_run_id,
        batch_id,
        config.db_dialect,
        config.storage_backend,
        dry_run,
        duration_ms,
    )
    return {
        "batch_id": batch_id,
        "dag_run_id": dag_run_id or "manual",
        "project_root": str(root),
        "source_csv_path": str(csv_path),
        "mysql_conn_id": mysql_conn_id,
        "dry_run": bool(dry_run),
        "force": bool(force),
        "max_quarantine_ratio": float(max_quarantine_ratio),
        "db_connected": db_connected,
        "config_summary": summary,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 2: Validate Source Files, SQL Resources & Core Database Schema
# ---------------------------------------------------------------------------
def task_validate_source_and_schema(runtime_ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify:
      1. Source CSV exists, is readable UTF-8, matches the exact 21-column schema,
         and compute its SHA-256 checksum.
      2. Required SQL migration & validation scripts exist.
      3. All 8 core Silver/staging tables exist (preflight_verify_core_schema),
         then apply additive migration 001 (CREATE TABLE IF NOT EXISTS).
      4. Check SHA-256 idempotency against etl_ingestion_batches.
    """
    t0 = time.perf_counter()
    root = Path(runtime_ctx["project_root"])
    ensure_project_on_sys_path(root)
    csv_path = Path(runtime_ctx["source_csv_path"])
    dry_run = bool(runtime_ctx["dry_run"])
    force = bool(runtime_ctx["force"])

    if not csv_path.exists() or not csv_path.is_file():
        raise FileNotFoundError(f"Source CSV file not found: {csv_path}")
    if csv_path.suffix.lower() != ".csv":
        raise ValueError(f"Source file must have .csv extension: {csv_path}")

    # Validate SQL scripts exist
    missing_sql: List[str] = []
    for rel in REQUIRED_SQL_RELATIVE_PATHS:
        if not (root / rel).is_file():
            missing_sql.append(str(root / rel))
    if missing_sql:
        raise FileNotFoundError(f"Required SQL file(s) missing: {', '.join(missing_sql)}")

    from pipeline.etl.extract import compute_sha256, validate_csv_schema  # type: ignore

    # Validate CSV header without loading full DataFrame into memory
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
    if not header:
        raise ValueError(f"Source CSV file is empty (no header row): {csv_path}")

    missing_cols, unexpected_cols = validate_csv_schema(header)
    if missing_cols or unexpected_cols:
        raise ValueError(
            f"CSV schema mismatch for {csv_path.name}: missing={missing_cols}, unexpected={unexpected_cols}"
        )

    file_hash = compute_sha256(csv_path)
    file_size = csv_path.stat().st_size

    duplicate_source_detected = False
    prior_batch_id: Optional[str] = None
    schema_verified = False

    if not dry_run:
        config = build_etl_config(
            project_root=str(root),
            mysql_conn_id=runtime_ctx["mysql_conn_id"],
        )
        from pipeline.etl.database import DatabaseManager  # type: ignore
        from pipeline.etl.metadata import MetadataRepository  # type: ignore

        db = DatabaseManager(config)
        try:
            missing_tables = db.preflight_verify_core_schema()
            if missing_tables:
                raise RuntimeError(
                    f"Core database schema incomplete — missing tables: {missing_tables}. "
                    "Initialize zomato_restaurant_explorer.sql before running the ETL DAG."
                )
            db.apply_etl_metadata_migration()
            schema_verified = True

            if not force:
                meta = MetadataRepository(db)
                existing = meta.find_successful_batch_by_hash(file_hash)
                if existing is not None:
                    duplicate_source_detected = True
                    prior_batch_id = existing["batch_id"]
        finally:
            db.close()

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Validated source & schema | file=%s | bytes=%d | sha256=%s | duplicate=%s | prior_batch=%s | ms=%.2f",
        csv_path.name,
        file_size,
        file_hash[:12],
        duplicate_source_detected,
        prior_batch_id,
        duration_ms,
    )
    return {
        "batch_id": runtime_ctx["batch_id"],
        "source_file_name": csv_path.name,
        "source_file_size": file_size,
        "source_file_hash": file_hash,
        "sql_files_verified": list(REQUIRED_SQL_RELATIVE_PATHS),
        "schema_verified": schema_verified,
        "duplicate_source_detected": duplicate_source_detected,
        "prior_batch_id": prior_batch_id,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 3: Bronze Raw Ingestion (Retry-Safe)
# ---------------------------------------------------------------------------
def task_bronze_ingestion(
    runtime_ctx: Dict[str, Any],
    source_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract source CSV and archive an immutable Bronze snapshot using
    `pipeline.etl.extract.extract_csv` and `pipeline.etl.bronze.ingest_to_bronze`.
    Retry-safe: recognizes already-stored Bronze batches for the same batch_id
    or SHA-256 hash without failing on FileExistsError.
    """
    t0 = time.perf_counter()
    started_at = _utc_now_str()
    root = Path(runtime_ctx["project_root"])
    ensure_project_on_sys_path(root)
    csv_path = Path(runtime_ctx["source_csv_path"])
    batch_id = runtime_ctx["batch_id"]
    dry_run = bool(runtime_ctx["dry_run"])
    force = bool(runtime_ctx["force"])
    duplicate_detected = bool(source_ctx["duplicate_source_detected"])

    config = build_etl_config(
        project_root=str(root),
        mysql_conn_id=runtime_ctx["mysql_conn_id"],
    )

    from pipeline.etl.bronze import ingest_to_bronze  # type: ignore
    from pipeline.etl.extract import extract_csv  # type: ignore

    extraction = extract_csv(csv_path)
    bronze_status = "SKIPPED_DRY_RUN"
    bronze_uri: Optional[str] = None
    bronze_metadata_uri: Optional[str] = None

    if not dry_run:
        from pipeline.etl.database import DatabaseManager  # type: ignore
        from pipeline.etl.metadata import MetadataRepository  # type: ignore

        if duplicate_detected and not force:
            bronze_status = "SKIPPED_EXISTING_HASH"
        else:
            try:
                bronze_res = ingest_to_bronze(extraction=extraction, config=config, batch_id=batch_id)
                bronze_status = "STORED"
                bronze_uri = bronze_res.stored_object.uri
                bronze_metadata_uri = bronze_res.stored_object.metadata_uri
            except FileExistsError:
                # Retry-safe: batch directory already created in an earlier attempt of this DAG run
                bronze_status = "ALREADY_STORED_ON_RETRY"
                logger.warning(
                    "Bronze batch directory already exists for batch_id=%s; treating retry as idempotent.",
                    batch_id,
                )

        db = DatabaseManager(config)
        try:
            meta = MetadataRepository(db)
            if bronze_uri is None and bronze_status == "SKIPPED_EXISTING_HASH":
                prior_batch = meta.find_successful_batch_by_hash(extraction.file_hash_sha256)
                if prior_batch:
                    bronze_uri = prior_batch.get("bronze_uri")
            # Retry-safe batch registration: insert only if batch_id not yet present
            with db.transaction() as conn:
                existing_row = conn.fetchone(
                    "SELECT batch_id, bronze_uri FROM etl_ingestion_batches WHERE batch_id = %s",
                    (batch_id,),
                )
            if existing_row is not None and bronze_uri is None and len(existing_row) > 1:
                bronze_uri = existing_row[1]
            if existing_row is None:
                meta.register_batch_start(
                    batch_id=batch_id,
                    source_name="zomato",
                    source_file_name=extraction.file_name,
                    source_file_path=str(extraction.source_path),
                    source_file_hash=extraction.file_hash_sha256,
                    source_file_size=extraction.file_size_bytes,
                    source_row_count=extraction.row_count,
                    storage_backend=config.storage_backend,
                    bronze_uri=bronze_uri,
                )
            meta.record_stage_run(
                batch_id=batch_id,
                stage="EXTRACT",
                status="SUCCESS",
                started_at=started_at,
                extracted_count=extraction.row_count,
            )
        finally:
            db.close()

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Bronze ingestion complete | batch_id=%s | status=%s | rows=%d | ms=%.2f",
        batch_id,
        bronze_status,
        extraction.row_count,
        duration_ms,
    )
    return {
        "batch_id": batch_id,
        "extracted_rows": extraction.row_count,
        "bronze_status": bronze_status,
        "bronze_uri": bronze_uri,
        "bronze_metadata_uri": bronze_metadata_uri,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 4: Silver Validation, Quarantine & Data Quality Gate
# ---------------------------------------------------------------------------
def task_validate_and_quarantine(
    runtime_ctx: Dict[str, Any],
    bronze_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Run `pipeline.etl.validation.validate_dataframe` and route rejected records
    through `pipeline.etl.quarantine.write_local_quarantine` + `MetadataRepository`.
    Applies configurable quality gate without duplicating validation rules.
    """
    t0 = time.perf_counter()
    started_at = _utc_now_str()
    root = Path(runtime_ctx["project_root"])
    ensure_project_on_sys_path(root)
    csv_path = Path(runtime_ctx["source_csv_path"])
    batch_id = runtime_ctx["batch_id"]
    dry_run = bool(runtime_ctx["dry_run"])
    max_quarantine_ratio = float(runtime_ctx.get("max_quarantine_ratio", 1.0))

    config = build_etl_config(
        project_root=str(root),
        mysql_conn_id=runtime_ctx["mysql_conn_id"],
    )

    from pipeline.etl.extract import extract_csv  # type: ignore
    from pipeline.etl.quarantine import write_local_quarantine  # type: ignore
    from pipeline.etl.validation import validate_dataframe  # type: ignore

    readable_csv = _resolve_readable_csv(runtime_ctx, bronze_ctx.get("bronze_uri"))
    extraction = extract_csv(readable_csv)
    validation = validate_dataframe(extraction.dataframe)

    accepted_rows = len(validation.valid_df)
    rejected_rows = len(validation.quarantine_records)
    extracted_rows = extraction.row_count

    quarantine_file: Optional[str] = None
    if validation.quarantine_records and not dry_run:
        q_path = write_local_quarantine(validation.quarantine_records, config.quarantine_path, batch_id)
        quarantine_file = str(q_path) if q_path else None

    if not dry_run:
        from pipeline.etl.database import DatabaseManager  # type: ignore
        from pipeline.etl.metadata import MetadataRepository  # type: ignore

        db = DatabaseManager(config)
        try:
            meta = MetadataRepository(db)
            # Clear prior attempt rows for this batch_id so retries never duplicate DQ/quarantine rows
            with db.transaction() as conn:
                conn.execute("DELETE FROM etl_data_quality_issues WHERE batch_id = %s", (batch_id,))
                conn.execute("DELETE FROM etl_quarantine_records WHERE batch_id = %s", (batch_id,))
            meta.record_dq_issues(batch_id, validation.issues)
            meta.record_quarantine_records(batch_id, validation.quarantine_records)
            meta.record_stage_run(
                batch_id=batch_id,
                stage="VALIDATE",
                status="SUCCESS" if rejected_rows == 0 else "PARTIAL_SUCCESS",
                started_at=started_at,
                extracted_count=extracted_rows,
                accepted_count=accepted_rows,
                rejected_count=rejected_rows,
                dq_issue_count=len(validation.issues),
            )
        finally:
            db.close()

    # Quality gate evaluation
    quarantine_ratio = (rejected_rows / extracted_rows) if extracted_rows > 0 else 0.0
    if extracted_rows > 0 and accepted_rows == 0:
        msg = (
            f"Data quality gate failed for batch_id={batch_id}: "
            f"all {extracted_rows} extracted rows were quarantined (0 accepted)."
        )
        if not dry_run:
            _mark_batch_failed(config, batch_id, "VALIDATE", started_at, msg, accepted_rows, rejected_rows)
        raise ValueError(msg)
    if quarantine_ratio > max_quarantine_ratio:
        msg = (
            f"Data quality gate failed for batch_id={batch_id}: "
            f"quarantine ratio {quarantine_ratio:.2%} exceeded threshold {max_quarantine_ratio:.2%} "
            f"({rejected_rows}/{extracted_rows} rows rejected)."
        )
        if not dry_run:
            _mark_batch_failed(config, batch_id, "VALIDATE", started_at, msg, accepted_rows, rejected_rows)
        raise ValueError(msg)

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Validation complete | batch_id=%s | accepted=%d | rejected=%d | issues=%d | exact_dups=%d | ms=%.2f",
        batch_id,
        accepted_rows,
        rejected_rows,
        len(validation.issues),
        validation.exact_duplicate_count,
        duration_ms,
    )
    return {
        "batch_id": batch_id,
        "extracted_rows": extracted_rows,
        "accepted_rows": accepted_rows,
        "rejected_rows": rejected_rows,
        "bronze_uri": bronze_ctx.get("bronze_uri"),
        "quarantine_file": quarantine_file,
        "quarantine_ratio": round(quarantine_ratio, 6),
        "total_issues": len(validation.issues),
        "issues_by_severity": validation.summary_by_severity,
        "issues_by_type": validation.summary_by_type,
        "exact_duplicates": validation.exact_duplicate_count,
        "duplicate_restaurant_ids": validation.duplicate_restaurant_id_count,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 5: Silver Transformation & Atomic Database Load
# ---------------------------------------------------------------------------
def task_load_silver_layer(
    runtime_ctx: Dict[str, Any],
    validation_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Transform validated records via `pipeline.etl.transform.transform_to_silver`
    and load into the 8 normalized Silver/staging tables via
    `pipeline.etl.load_silver.load_silver_layer` in a single atomic transaction.
    """
    t0 = time.perf_counter()
    started_at = _utc_now_str()
    root = Path(runtime_ctx["project_root"])
    ensure_project_on_sys_path(root)
    csv_path = Path(runtime_ctx["source_csv_path"])
    batch_id = runtime_ctx["batch_id"]
    dry_run = bool(runtime_ctx["dry_run"])

    config = build_etl_config(
        project_root=str(root),
        mysql_conn_id=runtime_ctx["mysql_conn_id"],
    )

    from pipeline.etl.extract import extract_csv  # type: ignore
    from pipeline.etl.transform import transform_to_silver  # type: ignore
    from pipeline.etl.validation import validate_dataframe  # type: ignore

    readable_csv = _resolve_readable_csv(runtime_ctx, validation_ctx.get("bronze_uri"))
    extraction = extract_csv(readable_csv)
    validation = validate_dataframe(extraction.dataframe)
    silver_data = transform_to_silver(validation.valid_df)

    transform_summary = {
        "countries": len(silver_data.countries),
        "cities": len(silver_data.cities),
        "locations": len(silver_data.locations),
        "rating_tiers": len(silver_data.rating_tiers),
        "restaurants": len(silver_data.restaurants_df),
        "cuisines": len(silver_data.cuisines),
        "restaurant_cuisines": len(silver_data.restaurant_cuisines),
    }

    if dry_run:
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "batch_id": batch_id,
            "skipped_dry_run": True,
            "silver_transform": transform_summary,
            "silver_load": {},
            "duration_ms": duration_ms,
        }

    from pipeline.etl.database import DatabaseManager  # type: ignore
    from pipeline.etl.load_silver import load_silver_layer  # type: ignore
    from pipeline.etl.metadata import MetadataRepository  # type: ignore

    db = DatabaseManager(config)
    try:
        metrics = load_silver_layer(db, silver_data)
        meta = MetadataRepository(db)
        meta.record_stage_run(
            batch_id=batch_id,
            stage="SILVER_LOAD",
            status="SUCCESS",
            started_at=started_at,
            transformed_count=len(silver_data.restaurants_df),
            inserted_count=metrics.restaurants_inserted,
            updated_count=metrics.restaurants_updated,
            unchanged_count=metrics.restaurants_unchanged,
        )
    except Exception as exc:
        _mark_batch_failed(
            config,
            batch_id,
            "SILVER_LOAD",
            started_at,
            str(exc),
            accepted_rows=int(validation_ctx.get("accepted_rows", 0)),
            rejected_rows=int(validation_ctx.get("rejected_rows", 0)),
        )
        raise
    finally:
        db.close()

    silver_load_summary = {
        "staging_upserted": metrics.staging_upserted,
        "countries_inserted": metrics.countries_inserted,
        "cities_inserted": metrics.cities_inserted,
        "locations_inserted": metrics.locations_inserted,
        "rating_tiers_inserted": metrics.rating_tiers_inserted,
        "restaurants_inserted": metrics.restaurants_inserted,
        "restaurants_updated": metrics.restaurants_updated,
        "restaurants_unchanged": metrics.restaurants_unchanged,
        "cuisines_inserted": metrics.cuisines_inserted,
        "restaurant_cuisines_inserted": metrics.restaurant_cuisines_inserted,
        "restaurant_cuisines_deleted": metrics.restaurant_cuisines_deleted,
        "table_counts": metrics.table_counts,
    }
    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Silver load complete | batch_id=%s | inserted=%d | updated=%d | unchanged=%d | ms=%.2f",
        batch_id,
        metrics.restaurants_inserted,
        metrics.restaurants_updated,
        metrics.restaurants_unchanged,
        duration_ms,
    )
    return {
        "batch_id": batch_id,
        "skipped_dry_run": False,
        "silver_transform": transform_summary,
        "silver_load": silver_load_summary,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 6: Gold Analytical Views Refresh
# ---------------------------------------------------------------------------
def task_refresh_gold_views(
    runtime_ctx: Dict[str, Any],
    silver_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Refresh and benchmark all 8 Gold analytical views using
    `pipeline.etl.build_gold.build_gold_views`.
    """
    t0 = time.perf_counter()
    started_at = _utc_now_str()
    root = Path(runtime_ctx["project_root"])
    ensure_project_on_sys_path(root)
    batch_id = runtime_ctx["batch_id"]
    dry_run = bool(runtime_ctx["dry_run"])

    if dry_run:
        return {
            "batch_id": batch_id,
            "skipped_dry_run": True,
            "views_verified": {},
            "query_timings_ms": {},
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    config = build_etl_config(
        project_root=str(root),
        mysql_conn_id=runtime_ctx["mysql_conn_id"],
    )

    from pipeline.etl.build_gold import build_gold_views  # type: ignore
    from pipeline.etl.database import DatabaseManager  # type: ignore
    from pipeline.etl.metadata import MetadataRepository  # type: ignore

    db = DatabaseManager(config)
    try:
        gold_res = build_gold_views(db)
        meta = MetadataRepository(db)
        meta.record_stage_run(
            batch_id=batch_id,
            stage="GOLD_REFRESH",
            status="SUCCESS",
            started_at=started_at,
        )
    except Exception as exc:
        _mark_batch_failed(config, batch_id, "GOLD_REFRESH", started_at, str(exc))
        raise
    finally:
        db.close()

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Gold views refreshed | batch_id=%s | views=%d | ms=%.2f",
        batch_id,
        len(gold_res.views_verified),
        duration_ms,
    )
    return {
        "batch_id": batch_id,
        "skipped_dry_run": False,
        "views_verified": gold_res.views_verified,
        "query_timings_ms": gold_res.query_timings_ms,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 7: Post-Load Data Quality & Reconciliation Checks
# ---------------------------------------------------------------------------
def task_run_data_quality_checks(
    runtime_ctx: Dict[str, Any],
    validation_ctx: Dict[str, Any],
    silver_ctx: Dict[str, Any],
    gold_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Reconcile Silver table counts against Gold view counts (mirroring
    `sql/validation/etl_validation_queries.sql`) and fail on referential or
    row-count discrepancies.
    """
    t0 = time.perf_counter()
    batch_id = runtime_ctx["batch_id"]
    dry_run = bool(runtime_ctx["dry_run"])

    if dry_run:
        return {
            "batch_id": batch_id,
            "skipped_dry_run": True,
            "checks_passed": True,
            "discrepancies": [],
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    table_counts = silver_ctx.get("silver_load", {}).get("table_counts", {})
    views_verified = gold_ctx.get("views_verified", {})
    discrepancies: List[str] = []

    stg_cnt = table_counts.get("stg_zomato_cleaned")
    rest_cnt = table_counts.get("restaurants")
    explorer_cnt = views_verified.get("v_restaurant_explorer")
    search_cnt = views_verified.get("gold_restaurant_search")

    if stg_cnt is not None and rest_cnt is not None and stg_cnt != rest_cnt:
        discrepancies.append(f"stg_zomato_cleaned ({stg_cnt}) != restaurants ({rest_cnt})")
    if rest_cnt is not None and explorer_cnt is not None and rest_cnt != explorer_cnt:
        discrepancies.append(f"restaurants ({rest_cnt}) != v_restaurant_explorer ({explorer_cnt})")
    if rest_cnt is not None and search_cnt is not None and rest_cnt != search_cnt:
        discrepancies.append(f"restaurants ({rest_cnt}) != gold_restaurant_search ({search_cnt})")
    if validation_ctx.get("accepted_rows", 0) > 0 and (rest_cnt or 0) == 0:
        discrepancies.append("accepted_rows > 0 but restaurants table is empty")

    if discrepancies:
        msg = f"Post-load reconciliation failed for batch_id={batch_id}: {'; '.join(discrepancies)}"
        logger.error(msg)
        raise ValueError(msg)

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Post-load DQ reconciliation PASSED | batch_id=%s | restaurants=%s | gold_search=%s | ms=%.2f",
        batch_id,
        rest_cnt,
        search_cnt,
        duration_ms,
    )
    return {
        "batch_id": batch_id,
        "skipped_dry_run": False,
        "checks_passed": True,
        "discrepancies": [],
        "reconciled_restaurant_count": rest_cnt,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 8: Finalize Batch Status & Generate Execution Reports
# ---------------------------------------------------------------------------
def task_generate_pipeline_summary(
    runtime_ctx: Dict[str, Any],
    source_ctx: Dict[str, Any],
    bronze_ctx: Dict[str, Any],
    validation_ctx: Dict[str, Any],
    silver_ctx: Dict[str, Any],
    gold_ctx: Dict[str, Any],
    dq_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Finalize `etl_ingestion_batches` status and write JSON + Markdown reports
    using `pipeline.etl.reporting.write_execution_reports`.
    """
    t0 = time.perf_counter()
    root = Path(runtime_ctx["project_root"])
    ensure_project_on_sys_path(root)
    batch_id = runtime_ctx["batch_id"]
    dry_run = bool(runtime_ctx["dry_run"])

    config = build_etl_config(
        project_root=str(root),
        mysql_conn_id=runtime_ctx["mysql_conn_id"],
    )

    rejected_rows = int(validation_ctx.get("rejected_rows", 0))
    accepted_rows = int(validation_ctx.get("accepted_rows", 0))
    final_status = "SUCCESS" if rejected_rows == 0 else "PARTIAL_SUCCESS"

    if not dry_run:
        from pipeline.etl.database import DatabaseManager  # type: ignore
        from pipeline.etl.metadata import MetadataRepository  # type: ignore

        db = DatabaseManager(config)
        try:
            meta = MetadataRepository(db)
            meta.complete_batch(
                batch_id=batch_id,
                status=final_status,
                accepted_row_count=accepted_rows,
                rejected_row_count=rejected_rows,
            )
        finally:
            db.close()

    timings_ms = {
        "validate_runtime_config": runtime_ctx.get("duration_ms", 0.0),
        "validate_source_and_schema": source_ctx.get("duration_ms", 0.0),
        "bronze_ingestion": bronze_ctx.get("duration_ms", 0.0),
        "validate_and_quarantine": validation_ctx.get("duration_ms", 0.0),
        "load_silver_layer": silver_ctx.get("duration_ms", 0.0),
        "refresh_gold_views": gold_ctx.get("duration_ms", 0.0),
        "run_data_quality_checks": dq_ctx.get("duration_ms", 0.0),
    }
    timings_ms["total_pipeline"] = round(sum(timings_ms.values()), 2)

    report_data: Dict[str, Any] = {
        "batch_id": batch_id,
        "dag_run_id": runtime_ctx.get("dag_run_id"),
        "mode": "full",
        "dry_run": dry_run,
        "force": bool(runtime_ctx.get("force", False)),
        "db_dialect": config.db_dialect,
        "storage_backend": config.storage_backend,
        "status": final_status,
        "generated_at_utc": _utc_now_str(),
        "timings_ms": timings_ms,
        "source_file_name": source_ctx.get("source_file_name"),
        "source_file_hash": source_ctx.get("source_file_hash"),
        "source_file_size": source_ctx.get("source_file_size"),
        "duplicate_source_detected": source_ctx.get("duplicate_source_detected", False),
        "prior_batch_id": source_ctx.get("prior_batch_id"),
        "extracted_rows": validation_ctx.get("extracted_rows", 0),
        "accepted_rows": accepted_rows,
        "rejected_rows": rejected_rows,
        "bronze": {
            "status": bronze_ctx.get("bronze_status"),
            "backend": config.storage_backend,
            "uri": bronze_ctx.get("bronze_uri"),
            "metadata_uri": bronze_ctx.get("bronze_metadata_uri"),
        },
        "data_quality": {
            "total_issues": validation_ctx.get("total_issues", 0),
            "issues_by_severity": validation_ctx.get("issues_by_severity", {}),
            "issues_by_type": validation_ctx.get("issues_by_type", {}),
            "exact_duplicates": validation_ctx.get("exact_duplicates", 0),
            "duplicate_restaurant_ids": validation_ctx.get("duplicate_restaurant_ids", 0),
            "quarantine_file": validation_ctx.get("quarantine_file"),
            "reconciliation_passed": dq_ctx.get("checks_passed", False),
        },
        "silver_transform": silver_ctx.get("silver_transform", {}),
        "silver_load": silver_ctx.get("silver_load", {}),
        "gold_layer": {
            "views_verified": gold_ctx.get("views_verified", {}),
            "query_timings_ms": gold_ctx.get("query_timings_ms", {}),
        },
    }

    from pipeline.etl.reporting import write_execution_reports  # type: ignore

    json_path, md_path = write_execution_reports(config.reports_path, batch_id, report_data)
    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    logger.info(
        "Pipeline summary written | batch_id=%s | status=%s | json=%s | md=%s | ms=%.2f",
        batch_id,
        final_status,
        json_path.name,
        md_path.name,
        duration_ms,
    )
    return {
        "batch_id": batch_id,
        "status": final_status,
        "accepted_rows": accepted_rows,
        "rejected_rows": rejected_rows,
        "json_report_path": str(json_path),
        "markdown_report_path": str(md_path),
        "duration_ms": duration_ms,
    }
