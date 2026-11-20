"""Data extraction module for CSV files (with strict 21-column schema verification)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import pandas as pd

EXPECTED_CSV_COLUMNS: List[str] = [
    "Restaurant ID",
    "Restaurant Name",
    "Country Code",
    "City",
    "Address",
    "Locality",
    "Locality Verbose",
    "Longitude",
    "Latitude",
    "Cuisines",
    "Average Cost for two",
    "Currency",
    "Has Table booking",
    "Has Online delivery",
    "Is delivering now",
    "Switch to order menu",
    "Price range",
    "Aggregate rating",
    "Rating color",
    "Rating text",
    "Votes",
]


@dataclass
class ExtractionResult:
    dataframe: pd.DataFrame
    source_path: Path
    file_name: str
    file_size_bytes: int
    file_hash_sha256: str
    row_count: int
    columns: List[str]


def compute_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def validate_csv_schema(columns: List[str]) -> Tuple[List[str], List[str]]:
    """Return (missing_columns, unexpected_columns) relative to EXPECTED_CSV_COLUMNS."""
    actual_set = set(columns)
    expected_set = set(EXPECTED_CSV_COLUMNS)
    missing = [c for c in EXPECTED_CSV_COLUMNS if c not in actual_set]
    unexpected = [c for c in columns if c not in expected_set]
    return missing, unexpected


def extract_csv(source_path: Path) -> ExtractionResult:
    """Read source CSV strictly as strings (preserving exact raw values) and verify schema."""
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source CSV file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Source path is not a file: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError(f"Unsupported source format '{path.suffix}'; expected .csv")

    file_size = path.stat().st_size
    file_hash = compute_sha256(path)

    # Read everything as raw strings with keep_default_na=False so empty cells vs literal 'NA'
    # are handled deterministically during Silver validation & cleaning.
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")

    missing, unexpected = validate_csv_schema(list(df.columns))
    if missing or unexpected:
        raise ValueError(
            f"Unsupported CSV schema in {path.name}. "
            f"Missing columns: {missing}; Unexpected columns: {unexpected}"
        )

    # Preserve 1-based CSV data row numbers (header is line 1, first data row is line 2)
    df.insert(0, "_source_row_number", range(2, len(df) + 2))

    return ExtractionResult(
        dataframe=df,
        source_path=path.resolve(),
        file_name=path.name,
        file_size_bytes=file_size,
        file_hash_sha256=file_hash,
        row_count=len(df),
        columns=list(EXPECTED_CSV_COLUMNS),
    )
