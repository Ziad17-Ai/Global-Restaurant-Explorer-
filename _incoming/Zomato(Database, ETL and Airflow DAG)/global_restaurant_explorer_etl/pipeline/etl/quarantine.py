"""Quarantine persistence for rejected records (local JSONL + database table)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pipeline.etl.validation import QuarantineRecord


def write_local_quarantine(
    quarantine_records: List[QuarantineRecord],
    quarantine_dir: Path,
    batch_id: str,
) -> Optional[Path]:
    """Write quarantined records to a batch-scoped JSONL file; returns None if empty."""
    if not quarantine_records:
        return None

    quarantine_dir.mkdir(parents=True, exist_ok=True)
    out_file = quarantine_dir / f"quarantine_batch_{batch_id}.jsonl"
    with out_file.open("w", encoding="utf-8") as f:
        for rec in quarantine_records:
            payload = {
                "batch_id": batch_id,
                "source_row_number": rec.source_row_number,
                "restaurant_id": rec.restaurant_id,
                "rejection_reason": rec.rejection_reason,
                "raw_record": rec.raw_record,
            }
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return out_file
