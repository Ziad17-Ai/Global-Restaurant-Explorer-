"""ETL metadata tracking for batches, pipeline stage runs, DQ issues, and quarantine records."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pipeline.etl.database import DatabaseManager
from pipeline.etl.validation import DataQualityIssue, QuarantineRecord


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class MetadataRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def find_successful_batch_by_hash(self, file_hash: str) -> Optional[Dict[str, str]]:
        with self.db.transaction() as conn:
            row = conn.fetchone(
                """
                SELECT batch_id, source_file_name, bronze_uri, ingestion_started_at
                FROM etl_ingestion_batches
                WHERE source_file_hash = %s
                  AND ingestion_status IN ('SUCCESS', 'PARTIAL_SUCCESS')
                ORDER BY ingestion_started_at DESC
                LIMIT 1
                """,
                (file_hash,),
            )
            if not row:
                return None
            return {
                "batch_id": row[0],
                "source_file_name": row[1],
                "bronze_uri": row[2],
                "ingestion_started_at": str(row[3]),
            }

    def register_batch_start(
        self,
        batch_id: str,
        source_name: str,
        source_file_name: str,
        source_file_path: str,
        source_file_hash: str,
        source_file_size: int,
        source_row_count: int,
        storage_backend: str,
        bronze_uri: Optional[str],
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO etl_ingestion_batches (
                    batch_id, source_name, source_file_name, source_file_path,
                    source_file_hash, source_file_size, source_row_count,
                    ingestion_started_at, ingestion_status, storage_backend, bronze_uri
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'RUNNING', %s, %s)
                """,
                (
                    batch_id,
                    source_name,
                    source_file_name,
                    source_file_path,
                    source_file_hash,
                    source_file_size,
                    source_row_count,
                    _utc_now_str(),
                    storage_backend,
                    bronze_uri,
                ),
            )

    def complete_batch(
        self,
        batch_id: str,
        status: str,
        accepted_row_count: int,
        rejected_row_count: int,
        error_message: Optional[str] = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE etl_ingestion_batches
                SET accepted_row_count = %s,
                    rejected_row_count = %s,
                    ingestion_finished_at = %s,
                    ingestion_status = %s,
                    error_message = %s
                WHERE batch_id = %s
                """,
                (
                    accepted_row_count,
                    rejected_row_count,
                    _utc_now_str(),
                    status,
                    error_message,
                    batch_id,
                ),
            )

    def record_stage_run(
        self,
        batch_id: str,
        stage: str,
        status: str,
        started_at: str,
        extracted_count: int = 0,
        transformed_count: int = 0,
        accepted_count: int = 0,
        rejected_count: int = 0,
        inserted_count: int = 0,
        updated_count: int = 0,
        unchanged_count: int = 0,
        dq_issue_count: int = 0,
        error_message: Optional[str] = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO etl_pipeline_runs (
                    run_id, batch_id, stage, started_at, finished_at,
                    extracted_count, transformed_count, accepted_count, rejected_count,
                    inserted_count, updated_count, unchanged_count, dq_issue_count,
                    status, error_message
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    batch_id,
                    stage,
                    started_at,
                    _utc_now_str(),
                    extracted_count,
                    transformed_count,
                    accepted_count,
                    rejected_count,
                    inserted_count,
                    updated_count,
                    unchanged_count,
                    dq_issue_count,
                    status,
                    error_message,
                ),
            )
        return run_id

    def record_dq_issues(self, batch_id: str, issues: List[DataQualityIssue]) -> int:
        if not issues:
            return 0
        rows = [
            (
                batch_id,
                i.restaurant_id,
                i.source_row_number,
                i.column_name[:64],
                i.issue_type[:64],
                i.severity,
                (i.original_value[:500] if i.original_value is not None else None),
                i.issue_description[:500],
            )
            for i in issues
        ]
        with self.db.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO etl_data_quality_issues (
                    batch_id, restaurant_id, source_row_number, column_name,
                    issue_type, severity, original_value, issue_description
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        return len(rows)

    def record_quarantine_records(self, batch_id: str, records: List[QuarantineRecord]) -> int:
        if not records:
            return 0
        rows = [
            (
                batch_id,
                r.source_row_number,
                r.restaurant_id,
                json.dumps(r.raw_record, ensure_ascii=False),
                r.rejection_reason[:500],
            )
            for r in records
        ]
        with self.db.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO etl_quarantine_records (
                    batch_id, source_row_number, restaurant_id, raw_record, rejection_reason
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                rows,
            )
        return len(rows)
