"""Immutable local filesystem Bronze storage backend."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

from pipeline.storage.base import BronzeStorageBackend, StoredObject


class LocalBronzeStorage(BronzeStorageBackend):
    """Stores raw CSV snapshots under <base>/<source_name>/YYYY/MM/DD/batch_<UUID>/."""

    backend_name = "local"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def store_batch(
        self,
        source_file: Path,
        source_name: str,
        batch_id: str,
        ingestion_date: str,
        metadata: Dict[str, Any],
    ) -> StoredObject:
        year, month, day = ingestion_date.split("-")
        batch_dir = self.base_dir / source_name / year / month / day / f"batch_{batch_id}"

        if batch_dir.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing Bronze batch directory: {batch_dir}"
            )

        batch_dir.mkdir(parents=True, exist_ok=False)
        dest_file = batch_dir / source_file.name
        shutil.copy2(source_file, dest_file)

        enriched_meta = dict(metadata)
        enriched_meta["bronze_file_path"] = str(dest_file.resolve())
        enriched_meta["storage_backend"] = self.backend_name

        meta_file = batch_dir / "metadata.json"
        meta_file.write_text(json.dumps(enriched_meta, indent=2), encoding="utf-8")

        return StoredObject(
            backend=self.backend_name,
            uri=str(dest_file.resolve()),
            metadata_uri=str(meta_file.resolve()),
            checksum_sha256=metadata["source_file_hash"],
            size_bytes=metadata["source_file_size"],
        )
