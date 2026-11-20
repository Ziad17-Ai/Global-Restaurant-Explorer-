"""
Airflow-ready modular ETL orchestrator.
Every stage is independently callable, deterministic, transaction-safe, and
returns structured dictionaries suitable for CLI execution or Airflow TaskFlow.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline.etl.bronze import ingest_to_bronze
from pipeline.etl.build_gold import build_gold_views
from pipeline.etl.config import ETLConfig
from pipeline.etl.database import DatabaseManager
from pipeline.etl.extract import extract_csv
from pipeline.etl.load_silver import load_silver_layer
from pipeline.etl.logging_config import configure_logging
from pipeline.etl.metadata import MetadataRepository
from pipeline.etl.quarantine import write_local_quarantine
from pipeline.etl.reporting import write_execution_reports
from pipeline.etl.transform import transform_to_silver
from pipeline.etl.validation import validate_dataframe


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def run_pipeline(
    config: ETLConfig,
    source_path: Optional[Path] = None,
    mode: str = "full",
    dry_run: bool = False,
    force: bool = False,
    batch_id: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Execute the Global Restaurant Explorer ETL pipeline.
    Supported modes: full | bronze | silver | gold | validate
    """
    logger = configure_logging(config.logs_path, verbose=verbose)
    total_t0 = time.perf_counter()
    resolved_batch_id = batch_id or str(uuid.uuid4())
    timings_ms: Dict[str, float] = {}

    report: Dict[str, Any] = {
        "batch_id": resolved_batch_id,
        "mode": mode,
        "dry_run": dry_run,
        "force": force,
        "db_dialect": config.db_dialect,
        "storage_backend": config.storage_backend,
        "status": "RUNNING",
        "timings_ms": timings_ms,
    }

    logger.info("Starting ETL pipeline | batch_id=%s mode=%s dry_run=%s force=%s", resolved_batch_id, mode, dry_run, force)
    logger.debug("Config summary: %s", config.safe_summary())

    db: Optional[DatabaseManager] = None
    meta: Optional[MetadataRepository] = None

    needs_db = (mode in ("full", "silver", "gold")) and not dry_run
    if needs_db:
        db = DatabaseManager(config)
        if not db.test_connection():
            raise ConnectionError("Failed to establish database connection.")
        missing_core = db.preflight_verify_core_schema()
        if missing_core:
            raise RuntimeError(
                f"Core database schema incomplete — missing tables: {missing_core}. "
                "Execute zomato_restaurant_explorer.sql first before running the ETL."
            )
        db.apply_etl_metadata_migration()
        meta = MetadataRepository(db)

    accepted_count = 0
    rejected_count = 0
    prior: Optional[Dict[str, str]] = None

    try:
        # Gold-only shortcut
        if mode == "gold":
            assert db is not None
            g_t0 = time.perf_counter()
            gold_res = build_gold_views(db)
            timings_ms["gold_refresh"] = round((time.perf_counter() - g_t0) * 1000.0, 2)
            report["gold_layer"] = {
                "views_verified": gold_res.views_verified,
                "query_timings_ms": gold_res.query_timings_ms,
            }
            report["status"] = "SUCCESS"
            timings_ms["total_pipeline"] = round((time.perf_counter() - total_t0) * 1000.0, 2)
            j_path, m_path = write_execution_reports(config.reports_path, resolved_batch_id, report)
            report["report_files"] = {"json": str(j_path), "markdown": str(m_path)}
            return report

        if source_path is None:
            raise ValueError(f"--source CSV path is required for mode='{mode}'")

        # ------------------------------------------------------------------
        # STAGE 1: EXTRACT
        # ------------------------------------------------------------------
        ext_started = _utc_now()
        t0 = time.perf_counter()
        extraction = extract_csv(source_path)
        timings_ms["extract"] = round((time.perf_counter() - t0) * 1000.0, 2)

        report.update({
            "source_file_name": extraction.file_name,
            "source_file_hash": extraction.file_hash_sha256,
            "source_file_size": extraction.file_size_bytes,
            "extracted_rows": extraction.row_count,
        })
        logger.info("Extracted %d rows from %s (sha256=%s)", extraction.row_count, extraction.file_name, extraction.file_hash_sha256[:12])

        # Idempotent hash check against already-processed batches
        if meta is not None and not force and mode in ("full", "silver"):
            prior = meta.find_successful_batch_by_hash(extraction.file_hash_sha256)
            if prior is not None:
                logger.info(
                    "Identical source file hash already processed in batch %s. "
                    "Reconciling Silver/Gold idempotently without duplicating Bronze.",
                    prior["batch_id"],
                )
                report["duplicate_source_detected"] = True
                report["prior_batch_id"] = prior["batch_id"]

        # ------------------------------------------------------------------
        # STAGE 2: BRONZE INGESTION
        # ------------------------------------------------------------------
        bronze_uri: Optional[str] = None
        if mode in ("full", "bronze") and not dry_run:
            if report.get("duplicate_source_detected") and not force and prior is not None:
                bronze_uri = prior["bronze_uri"]
                report["bronze"] = {"status": "SKIPPED_EXISTING_HASH", "uri": bronze_uri}
            else:
                b_t0 = time.perf_counter()
                bronze_res = ingest_to_bronze(extraction, config, source_name="zomato", batch_id=resolved_batch_id)
                timings_ms["bronze"] = round((time.perf_counter() - b_t0) * 1000.0, 2)
                bronze_uri = bronze_res.stored_object.uri
                report["bronze"] = {
                    "status": "STORED",
                    "backend": bronze_res.stored_object.backend,
                    "uri": bronze_res.stored_object.uri,
                    "metadata_uri": bronze_res.stored_object.metadata_uri,
                }
                logger.info("Bronze snapshot preserved at %s", bronze_uri)

        if meta is not None and db is not None:
            with db.transaction() as conn:
                existing_batch = conn.fetchone(
                    "SELECT batch_id FROM etl_ingestion_batches WHERE batch_id = %s",
                    (resolved_batch_id,),
                )
            if existing_batch is None:
                meta.register_batch_start(
                    batch_id=resolved_batch_id,
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
                batch_id=resolved_batch_id,
                stage="EXTRACT",
                status="SUCCESS",
                started_at=ext_started,
                extracted_count=extraction.row_count,
            )

        if mode == "bronze":
            if meta is not None:
                meta.complete_batch(resolved_batch_id, "SUCCESS", extraction.row_count, 0)
            report["status"] = "SUCCESS"
            timings_ms["total_pipeline"] = round((time.perf_counter() - total_t0) * 1000.0, 2)
            j_path, m_path = write_execution_reports(config.reports_path, resolved_batch_id, report)
            report["report_files"] = {"json": str(j_path), "markdown": str(m_path)}
            return report

        # ------------------------------------------------------------------
        # STAGE 3: DATA QUALITY VALIDATION & QUARANTINE
        # ------------------------------------------------------------------
        val_started = _utc_now()
        v_t0 = time.perf_counter()
        validation = validate_dataframe(extraction.dataframe)
        timings_ms["validate"] = round((time.perf_counter() - v_t0) * 1000.0, 2)

        accepted_count = len(validation.valid_df)
        rejected_count = len(validation.quarantine_records)
        report["accepted_rows"] = accepted_count
        report["rejected_rows"] = rejected_count
        report["data_quality"] = {
            "total_issues": len(validation.issues),
            "issues_by_severity": validation.summary_by_severity,
            "issues_by_type": validation.summary_by_type,
            "exact_duplicates": validation.exact_duplicate_count,
            "duplicate_restaurant_ids": validation.duplicate_restaurant_id_count,
        }

        q_file = write_local_quarantine(validation.quarantine_records, config.quarantine_path, resolved_batch_id)
        if q_file:
            report["quarantine_file"] = str(q_file)

        if meta is not None:
            meta.record_dq_issues(resolved_batch_id, validation.issues)
            meta.record_quarantine_records(resolved_batch_id, validation.quarantine_records)
            meta.record_stage_run(
                batch_id=resolved_batch_id,
                stage="VALIDATE",
                status="SUCCESS" if rejected_count == 0 else "PARTIAL_SUCCESS",
                started_at=val_started,
                extracted_count=extraction.row_count,
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                dq_issue_count=len(validation.issues),
            )

        logger.info(
            "Validation complete | accepted=%d rejected=%d dq_issues=%d",
            accepted_count, rejected_count, len(validation.issues),
        )

        # ------------------------------------------------------------------
        # STAGE 4: SILVER TRANSFORMATION
        # ------------------------------------------------------------------
        tr_started = _utc_now()
        t_t0 = time.perf_counter()
        silver_data = transform_to_silver(validation.valid_df)
        timings_ms["transform"] = round((time.perf_counter() - t_t0) * 1000.0, 2)

        report["silver_transform"] = {
            "countries": len(silver_data.countries),
            "cities": len(silver_data.cities),
            "locations": len(silver_data.locations),
            "rating_tiers": len(silver_data.rating_tiers),
            "restaurants": len(silver_data.restaurants_df),
            "cuisines": len(silver_data.cuisines),
            "restaurant_cuisines": len(silver_data.restaurant_cuisines),
        }

        if meta is not None:
            meta.record_stage_run(
                batch_id=resolved_batch_id,
                stage="TRANSFORM",
                status="SUCCESS",
                started_at=tr_started,
                transformed_count=len(silver_data.restaurants_df),
            )

        if mode == "validate" or dry_run:
            report["status"] = "SUCCESS" if rejected_count == 0 else "PARTIAL_SUCCESS"
            timings_ms["total_pipeline"] = round((time.perf_counter() - total_t0) * 1000.0, 2)
            j_path, m_path = write_execution_reports(config.reports_path, resolved_batch_id, report)
            report["report_files"] = {"json": str(j_path), "markdown": str(m_path)}
            return report

        # ------------------------------------------------------------------
        # STAGE 5: SILVER LOAD (IDEMPOTENT & TRANSACTIONAL)
        # ------------------------------------------------------------------
        assert db is not None and meta is not None
        sl_started = _utc_now()
        s_t0 = time.perf_counter()
        load_metrics = load_silver_layer(db, silver_data)
        timings_ms["silver_load"] = round((time.perf_counter() - s_t0) * 1000.0, 2)

        report["silver_load"] = {
            "staging_upserted": load_metrics.staging_upserted,
            "countries_inserted": load_metrics.countries_inserted,
            "cities_inserted": load_metrics.cities_inserted,
            "locations_inserted": load_metrics.locations_inserted,
            "rating_tiers_inserted": load_metrics.rating_tiers_inserted,
            "restaurants_inserted": load_metrics.restaurants_inserted,
            "restaurants_updated": load_metrics.restaurants_updated,
            "restaurants_unchanged": load_metrics.restaurants_unchanged,
            "cuisines_inserted": load_metrics.cuisines_inserted,
            "restaurant_cuisines_inserted": load_metrics.restaurant_cuisines_inserted,
            "restaurant_cuisines_deleted": load_metrics.restaurant_cuisines_deleted,
            "table_counts": load_metrics.table_counts,
        }

        meta.record_stage_run(
            batch_id=resolved_batch_id,
            stage="SILVER_LOAD",
            status="SUCCESS",
            started_at=sl_started,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            inserted_count=load_metrics.restaurants_inserted,
            updated_count=load_metrics.restaurants_updated,
            unchanged_count=load_metrics.restaurants_unchanged,
        )
        logger.info(
            "Silver load complete | inserted=%d updated=%d unchanged=%d",
            load_metrics.restaurants_inserted,
            load_metrics.restaurants_updated,
            load_metrics.restaurants_unchanged,
        )

        # ------------------------------------------------------------------
        # STAGE 6: GOLD LAYER REFRESH
        # ------------------------------------------------------------------
        if mode == "full":
            g_started = _utc_now()
            g_t0 = time.perf_counter()
            gold_res = build_gold_views(db)
            timings_ms["gold_refresh"] = round((time.perf_counter() - g_t0) * 1000.0, 2)
            report["gold_layer"] = {
                "views_verified": gold_res.views_verified,
                "query_timings_ms": gold_res.query_timings_ms,
            }
            meta.record_stage_run(
                batch_id=resolved_batch_id,
                stage="GOLD_REFRESH",
                status="SUCCESS",
                started_at=g_started,
            )
            logger.info("Gold views refreshed and verified (%d views)", len(gold_res.views_verified))

        final_status = "SUCCESS" if rejected_count == 0 else "PARTIAL_SUCCESS"
        meta.complete_batch(resolved_batch_id, final_status, accepted_count, rejected_count)
        report["status"] = final_status
        timings_ms["total_pipeline"] = round((time.perf_counter() - total_t0) * 1000.0, 2)

        j_path, m_path = write_execution_reports(config.reports_path, resolved_batch_id, report)
        report["report_files"] = {"json": str(j_path), "markdown": str(m_path)}
        logger.info("ETL pipeline finished | status=%s total_ms=%.2f", final_status, timings_ms["total_pipeline"])
        return report

    except Exception as exc:
        logger.exception("ETL pipeline failed: %s", exc)
        report["status"] = "FAILED"
        report["error"] = str(exc)
        if meta is not None:
            try:
                meta.complete_batch(resolved_batch_id, "FAILED", accepted_count, rejected_count, error_message=str(exc))
            except Exception:
                pass
        raise
    finally:
        if db is not None:
            db.close()
        for h in list(logger.handlers):
            h.close()
            logger.removeHandler(h)
