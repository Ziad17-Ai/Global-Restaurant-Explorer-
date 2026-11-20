"""Abstract Bronze storage interface for immutable raw data preservation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class StoredObject:
    backend: str
    uri: str
    metadata_uri: str
    checksum_sha256: str
    size_bytes: int


class BronzeStorageBackend(ABC):
    """Pluggable storage contract supporting local filesystem and Azure Blob Storage."""

    backend_name: str = "abstract"

    @abstractmethod
    def store_batch(
        self,
        source_file: Path,
        source_name: str,
        batch_id: str,
        ingestion_date: str,
        metadata: Dict[str, Any],
    ) -> StoredObject:
        """Copy the raw source file immutably into Bronze storage with metadata.json."""
