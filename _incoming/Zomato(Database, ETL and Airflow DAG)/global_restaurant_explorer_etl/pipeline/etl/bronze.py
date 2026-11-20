"""Bronze layer ingestion: immutable raw CSV preservation and metadata generation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pipeline.etl.config import ETLConfig
from pipeline.etl.extract import ExtractionResult
from pipeline.storage import AzureBlobBronzeStorage, BronzeStorageBackend, LocalBronzeStorage, StoredObject


@dataclass
class BronzeResult:
    batch_id: str
    source_name: str
    stored_object: StoredObject
    ingestion_timestamp: str
    metadata: dict


def build_storage_backend(config: ETLConfig) -> BronzeStorageBackend:
    if config.storage_backend == "local":
        return LocalBronzeStorage(config.bronze_local_path)
    if config.storage_backend == "azure":
        return AzureBlobBronzeStorage(
            container_name=config.azure_container,
            connection_string=config.azure_connection_string,
            account_url=config.azure_account_url,
        )
    raise ValueError(f"Unsupported STORAGE_BACKEND: '{config.storage_backend}'")


def ingest_to_bronze(
    extraction: ExtractionResult,
    config: ETLConfig,
    source_name: str = "zomato",
    batch_id: Optional[str] = None,
) -> BronzeResult:
    """Copy the raw source file immutably to Bronze storage and write metadata.json."""
    resolved_batch_id = batch_id or str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    ingestion_date = now_utc.strftime("%Y-%m-%d")
    ingestion_ts = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    metadata = {
        "batch_id": resolved_batch_id,
        "source_name": source_name,
        "source_file_name": extraction.file_name,
        "source_file_path": str(extraction.source_path),
        "source_format": "csv",
        "source_file_hash": extraction.file_hash_sha256,
        "source_file_size": extraction.file_size_bytes,
        "source_row_count": extraction.row_count,
        "column_count": len(extraction.columns),
        "columns": extraction.columns,
        "ingestion_timestamp_utc": ingestion_ts,
    }

    backend = build_storage_backend(config)
    stored = backend.store_batch(
        source_file=extraction.source_path,
        source_name=source_name,
        batch_id=resolved_batch_id,
        ingestion_date=ingestion_date,
        metadata=metadata,
    )

    return BronzeResult(
        batch_id=resolved_batch_id,
        source_name=source_name,
        stored_object=stored,
        ingestion_timestamp=ingestion_ts,
        metadata=metadata,
    )
