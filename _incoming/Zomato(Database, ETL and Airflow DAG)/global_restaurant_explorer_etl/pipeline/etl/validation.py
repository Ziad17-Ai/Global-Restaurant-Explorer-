"""Silver-layer data quality validation and record quarantine classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

KNOWN_RATING_TIERS: Dict[str, str] = {
    "White": "Not rated",
    "Red": "Poor",
    "Orange": "Average",
    "Yellow": "Good",
    "Green": "Very Good",
    "Dark Green": "Excellent",
}

BOOLEAN_COLUMNS: List[str] = [
    "Has Table booking",
    "Has Online delivery",
    "Is delivering now",
    "Switch to order menu",
]


@dataclass
class DataQualityIssue:
    source_row_number: int
    restaurant_id: Optional[int]
    column_name: str
    issue_type: str
    severity: str  # INFO | WARNING | ERROR | CRITICAL
    original_value: Optional[str]
    issue_description: str


@dataclass
class QuarantineRecord:
    source_row_number: int
    restaurant_id: Optional[int]
    raw_record: Dict[str, Any]
    rejection_reason: str


@dataclass
class ValidationResult:
    valid_df: pd.DataFrame
    quarantine_records: List[QuarantineRecord] = field(default_factory=list)
    issues: List[DataQualityIssue] = field(default_factory=list)
    exact_duplicate_count: int = 0
    duplicate_restaurant_id_count: int = 0

    @property
    def summary_by_severity(self) -> Dict[str, int]:
        counts = {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0}
        for issue in self.issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        return counts

    @property
    def summary_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for issue in self.issues:
            counts[issue.issue_type] = counts.get(issue.issue_type, 0) + 1
        return counts


COLUMN_MAX_LENGTHS: Dict[str, int] = {
    "Restaurant Name": 100,
    "City": 100,
    "Address": 255,
    "Locality": 100,
    "Locality Verbose": 150,
    "Currency": 50,
    "Cuisines": 255,
    "Rating color": 20,
    "Rating text": 20,
}


def _parse_int(val: str) -> Optional[int]:
    s = val.strip()
    if not s:
        return None
    try:
        d = Decimal(s)
        if not d.is_finite() or d != int(d):
            return None
        return int(d)
    except (InvalidOperation, ValueError):
        return None


def _parse_decimal(val: str) -> Optional[Decimal]:
    s = val.strip()
    if not s:
        return None
    try:
        d = Decimal(s)
        if not d.is_finite():
            return None
        return d
    except InvalidOperation:
        return None


def validate_dataframe(
    raw_df: pd.DataFrame,
    known_rating_tiers: Optional[Dict[str, str]] = None,
) -> ValidationResult:
    """
    Validate raw string DataFrame against all Silver business & schema rules.
    - Legitimate missing coordinates (both NULL) -> WARNING (row accepted).
    - Legitimate missing cuisines (NULL) -> INFO (row accepted).
    - Intra-row duplicate cuisines -> INFO (deduplicated during transform, row accepted).
    - Schema-breaking errors -> ERROR/CRITICAL (row quarantined).
    """
    tiers = known_rating_tiers if known_rating_tiers is not None else KNOWN_RATING_TIERS
    issues: List[DataQualityIssue] = []
    quarantine: List[QuarantineRecord] = []
    valid_indices: List[int] = []

    # Check exact duplicate rows (excluding synthetic _source_row_number)
    data_cols = [c for c in raw_df.columns if c != "_source_row_number"]
    exact_dup_mask = raw_df.duplicated(subset=data_cols, keep="first")
    exact_dup_count = int(exact_dup_mask.sum())

    seen_restaurant_ids: Set[int] = set()
    dup_id_count = 0

    for idx, row in raw_df.iterrows():
        row_num = int(row["_source_row_number"])
        row_errors: List[str] = []

        # 1. Restaurant ID
        raw_rid = str(row["Restaurant ID"]).strip()
        rid = _parse_int(raw_rid)
        if not raw_rid:
            msg = "Missing required Restaurant ID"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, None, "Restaurant ID", "MISSING_RESTAURANT_ID", "CRITICAL", raw_rid, msg))
        elif rid is None or rid <= 0:
            msg = f"Invalid Restaurant ID '{raw_rid}' (must be positive integer)"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, None, "Restaurant ID", "INVALID_RESTAURANT_ID", "CRITICAL", raw_rid, msg))
        elif rid in seen_restaurant_ids:
            dup_id_count += 1
            msg = f"Duplicate Restaurant ID {rid} within batch"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Restaurant ID", "DUPLICATE_RESTAURANT_ID", "ERROR", raw_rid, msg))
        else:
            seen_restaurant_ids.add(rid)

        if bool(exact_dup_mask.loc[idx]):
            issues.append(DataQualityIssue(row_num, rid, "*", "EXACT_DUPLICATE_ROW", "ERROR", None, "Exact duplicate CSV row detected"))

        # 2. Required text fields
        for col, itype in [
            ("Restaurant Name", "MISSING_RESTAURANT_NAME"),
            ("City", "MISSING_CITY"),
            ("Address", "MISSING_ADDRESS"),
            ("Locality", "MISSING_LOCALITY"),
            ("Locality Verbose", "MISSING_LOCALITY_VERBOSE"),
            ("Currency", "MISSING_CURRENCY"),
        ]:
            val = str(row[col]).strip()
            if not val:
                msg = f"Missing required {col}"
                row_errors.append(msg)
                issues.append(DataQualityIssue(row_num, rid, col, itype, "ERROR", val, msg))
            elif len(val) > COLUMN_MAX_LENGTHS.get(col, 255):
                max_len = COLUMN_MAX_LENGTHS[col]
                msg = f"{col} length {len(val)} exceeds MySQL schema limit of {max_len}"
                row_errors.append(msg)
                issues.append(DataQualityIssue(row_num, rid, col, "VALUE_TOO_LONG", "ERROR", val[:100], msg))

        # 3. Country Code
        raw_cc = str(row["Country Code"]).strip()
        cc = _parse_int(raw_cc)
        if not raw_cc or cc is None or cc <= 0:
            msg = f"Invalid or missing Country Code '{raw_cc}'"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Country Code", "INVALID_COUNTRY_CODE", "ERROR", raw_cc, msg))

        # 4. Geographic coordinates (paired NULL is valid -> WARNING; half-null or out-of-range -> ERROR)
        raw_lon = str(row["Longitude"]).strip()
        raw_lat = str(row["Latitude"]).strip()
        if raw_lon == "" and raw_lat == "":
            issues.append(DataQualityIssue(
                row_num, rid, "Longitude,Latitude", "MISSING_COORDINATES", "WARNING", None,
                "Both Longitude and Latitude are missing; preserved as NULL",
            ))
        elif (raw_lon == "") != (raw_lat == ""):
            msg = f"Incomplete coordinate pair (Longitude='{raw_lon}', Latitude='{raw_lat}')"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Longitude,Latitude", "INCOMPLETE_COORDINATE_PAIR", "ERROR", f"{raw_lon},{raw_lat}", msg))
        else:
            lon = _parse_decimal(raw_lon)
            lat = _parse_decimal(raw_lat)
            if lon is None or lon < Decimal("-180") or lon > Decimal("180"):
                msg = f"Invalid Longitude '{raw_lon}' (must be between -180 and 180)"
                row_errors.append(msg)
                issues.append(DataQualityIssue(row_num, rid, "Longitude", "INVALID_LONGITUDE", "ERROR", raw_lon, msg))
            if lat is None or lat < Decimal("-90") or lat > Decimal("90"):
                msg = f"Invalid Latitude '{raw_lat}' (must be between -90 and 90)"
                row_errors.append(msg)
                issues.append(DataQualityIssue(row_num, rid, "Latitude", "INVALID_LATITUDE", "ERROR", raw_lat, msg))

        # 5. Cuisines (NULL is valid -> INFO; intra-row duplicates -> INFO)
        raw_cuisines = str(row["Cuisines"]).strip()
        if raw_cuisines == "":
            issues.append(DataQualityIssue(
                row_num, rid, "Cuisines", "MISSING_CUISINES", "INFO", None,
                "Cuisines field is missing; restaurant preserved with 0 cuisine links",
            ))
        else:
            if len(raw_cuisines) > COLUMN_MAX_LENGTHS["Cuisines"]:
                msg = f"Cuisines length {len(raw_cuisines)} exceeds MySQL schema limit of {COLUMN_MAX_LENGTHS['Cuisines']}"
                row_errors.append(msg)
                issues.append(DataQualityIssue(row_num, rid, "Cuisines", "VALUE_TOO_LONG", "ERROR", raw_cuisines[:100], msg))
            tokens = [t.strip() for t in raw_cuisines.split(",") if t.strip()]
            if not tokens:
                msg = f"Invalid Cuisines format '{raw_cuisines}' (no valid tokens)"
                row_errors.append(msg)
                issues.append(DataQualityIssue(row_num, rid, "Cuisines", "INVALID_CUISINE_FORMAT", "ERROR", raw_cuisines, msg))
            elif len(tokens) != len(set(tokens)):
                issues.append(DataQualityIssue(
                    row_num, rid, "Cuisines", "DUPLICATE_CUISINE_IN_ROW", "INFO", raw_cuisines,
                    "Duplicate cuisine category repeated within same restaurant; deduplicated in Silver",
                ))

        # 6. Average Cost for two (>= 0)
        raw_cost = str(row["Average Cost for two"]).strip()
        cost = _parse_decimal(raw_cost)
        if cost is None or cost < Decimal("0"):
            msg = f"Invalid or negative Average Cost for two '{raw_cost}'"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Average Cost for two", "INVALID_AVERAGE_COST", "ERROR", raw_cost, msg))

        # 7. Boolean Yes/No columns
        for bcol in BOOLEAN_COLUMNS:
            bval = str(row[bcol]).strip()
            if bval not in ("Yes", "No"):
                msg = f"Invalid boolean value '{bval}' in '{bcol}' (expected Yes or No)"
                row_errors.append(msg)
                issues.append(DataQualityIssue(row_num, rid, bcol, "INVALID_BOOLEAN", "ERROR", bval, msg))

        # 8. Price range (1..4)
        raw_pr = str(row["Price range"]).strip()
        pr = _parse_int(raw_pr)
        if pr is None or pr < 1 or pr > 4:
            msg = f"Invalid Price range '{raw_pr}' (expected integer 1..4)"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Price range", "INVALID_PRICE_RANGE", "ERROR", raw_pr, msg))

        # 9. Aggregate rating (0.0..5.0; 0.0 preserved as Not rated)
        raw_rat = str(row["Aggregate rating"]).strip()
        rat = _parse_decimal(raw_rat)
        if rat is None or rat < Decimal("0.0") or rat > Decimal("5.0"):
            msg = f"Invalid Aggregate rating '{raw_rat}' (expected 0.0..5.0)"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Aggregate rating", "INVALID_RATING", "ERROR", raw_rat, msg))

        # 10. Rating color <-> Rating text consistency
        r_color = str(row["Rating color"]).strip()
        r_text = str(row["Rating text"]).strip()
        if not r_color or not r_text:
            msg = f"Missing Rating color ('{r_color}') or Rating text ('{r_text}')"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Rating color,Rating text", "MISSING_RATING_TIER", "ERROR", f"{r_color}|{r_text}", msg))
        elif r_color not in tiers or tiers[r_color] != r_text:
            msg = f"Unknown or inconsistent rating tier mapping ('{r_color}' -> '{r_text}')"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Rating color,Rating text", "UNKNOWN_RATING_TIER", "ERROR", f"{r_color}|{r_text}", msg))

        # 11. Votes (>= 0)
        raw_votes = str(row["Votes"]).strip()
        votes = _parse_int(raw_votes)
        if votes is None or votes < 0:
            msg = f"Invalid or negative Votes '{raw_votes}'"
            row_errors.append(msg)
            issues.append(DataQualityIssue(row_num, rid, "Votes", "INVALID_VOTES", "ERROR", raw_votes, msg))

        if row_errors:
            raw_dict = {col: row[col] for col in data_cols}
            quarantine.append(
                QuarantineRecord(
                    source_row_number=row_num,
                    restaurant_id=rid,
                    raw_record=raw_dict,
                    rejection_reason="; ".join(row_errors),
                )
            )
        else:
            valid_indices.append(idx)

    valid_df = raw_df.loc[valid_indices].copy().reset_index(drop=True)
    return ValidationResult(
        valid_df=valid_df,
        quarantine_records=quarantine,
        issues=issues,
        exact_duplicate_count=exact_dup_count,
        duplicate_restaurant_id_count=dup_id_count,
    )
