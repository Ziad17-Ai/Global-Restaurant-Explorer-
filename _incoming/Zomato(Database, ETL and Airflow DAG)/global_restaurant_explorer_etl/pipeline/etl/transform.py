"""Silver-layer Pandas cleaning, standardization, and relational dataset preparation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import pandas as pd

COLUMN_MAPPING: Dict[str, str] = {
    "Restaurant ID": "restaurant_id",
    "Restaurant Name": "restaurant_name",
    "Country Code": "country_code",
    "City": "city",
    "Address": "address",
    "Locality": "locality",
    "Locality Verbose": "locality_verbose",
    "Longitude": "longitude",
    "Latitude": "latitude",
    "Cuisines": "cuisines",
    "Average Cost for two": "average_cost_for_two",
    "Currency": "currency",
    "Has Table booking": "has_table_booking",
    "Has Online delivery": "has_online_delivery",
    "Is delivering now": "is_delivering_now",
    "Switch to order menu": "switch_to_order_menu",
    "Price range": "price_range",
    "Aggregate rating": "aggregate_rating",
    "Rating color": "rating_color",
    "Rating text": "rating_text",
    "Votes": "votes",
}


@dataclass
class TransformedSilverData:
    staging_df: pd.DataFrame
    countries: List[int]
    cities: List[Tuple[int, str]]
    locations: List[Tuple[int, str, str, str, str, Optional[str], Optional[str]]]
    rating_tiers: List[Tuple[str, str]]
    restaurants_df: pd.DataFrame
    cuisines: List[str]
    restaurant_cuisines: List[Tuple[int, str]]


def _quantize_str(val: object, places: int) -> Optional[str]:
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if s == "":
        return None
    d = Decimal(s)
    q = Decimal(10) ** (-places)
    return str(d.quantize(q))


def _none_if_na(val: object) -> Optional[str]:
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    return s if s != "" else None


def split_cuisines(raw_cuisines: Optional[str]) -> List[str]:
    """Split comma-separated cuisines, trim whitespace, drop empties, and deduplicate preserving order."""
    if raw_cuisines is None:
        return []
    s = str(raw_cuisines).strip()
    if not s:
        return []
    seen = set()
    result = []
    for token in s.split(","):
        cleaned = token.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def transform_to_silver(valid_df: pd.DataFrame) -> TransformedSilverData:
    """
    Convert validated raw DataFrame into standardized Silver structures matching
    the exact zomato_restaurant_explorer MySQL 8.0 schema.
    """
    if valid_df.empty:
        empty_cols = list(COLUMN_MAPPING.values())
        return TransformedSilverData(
            staging_df=pd.DataFrame(columns=empty_cols),
            countries=[],
            cities=[],
            locations=[],
            rating_tiers=[],
            restaurants_df=pd.DataFrame(),
            cuisines=[],
            restaurant_cuisines=[],
        )

    df = valid_df[list(COLUMN_MAPPING.keys())].rename(columns=COLUMN_MAPPING).copy()

    # Trim surrounding whitespace on text columns
    text_cols = [
        "restaurant_name", "city", "address", "locality",
        "locality_verbose", "currency", "rating_color", "rating_text",
        "has_table_booking", "has_online_delivery", "is_delivering_now", "switch_to_order_menu",
    ]
    for col in text_cols:
        df[col] = df[col].astype(str).str.strip()

    # Preserve Python None (never float NaN under Pandas 3.x) for nullable columns
    df["cuisines"] = pd.Series([_none_if_na(x) for x in df["cuisines"]], index=df.index, dtype=object)

    # Exact numeric & decimal formatting (preserving precision)
    df["restaurant_id"] = df["restaurant_id"].astype(str).str.strip().astype(int)
    df["country_code"] = df["country_code"].astype(str).str.strip().astype(int)
    df["price_range"] = df["price_range"].astype(str).str.strip().astype(int)
    df["votes"] = df["votes"].astype(str).str.strip().astype(int)
    df["longitude"] = pd.Series([_quantize_str(x, 9) for x in df["longitude"]], index=df.index, dtype=object)
    df["latitude"] = pd.Series([_quantize_str(x, 9) for x in df["latitude"]], index=df.index, dtype=object)
    df["average_cost_for_two"] = pd.Series([_quantize_str(x, 2) for x in df["average_cost_for_two"]], index=df.index, dtype=object)
    df["aggregate_rating"] = pd.Series([_quantize_str(x, 1) for x in df["aggregate_rating"]], index=df.index, dtype=object)

    staging_df = df.copy()

    # Normalized boolean flags (Yes -> 1, No -> 0) for restaurants table
    restaurants_df = df.copy()
    for bcol in ["has_table_booking", "has_online_delivery", "is_delivering_now", "switch_to_order_menu"]:
        restaurants_df[bcol] = (restaurants_df[bcol] == "Yes").astype(int)

    # Distinct normalized entities
    countries = sorted(df["country_code"].unique().tolist())

    cities = sorted(
        {(int(r.country_code), str(r.city)) for r in df[["country_code", "city"]].itertuples(index=False)}
    )

    locations_set = {
        (
            int(r.country_code),
            str(r.city),
            str(r.address),
            str(r.locality),
            str(r.locality_verbose),
            _none_if_na(r.longitude),
            _none_if_na(r.latitude),
        )
        for r in df[
            ["country_code", "city", "address", "locality", "locality_verbose", "longitude", "latitude"]
        ].itertuples(index=False)
    }
    locations = sorted(
        locations_set,
        key=lambda x: (x[0], x[1], x[3], x[2], "" if x[5] is None else str(x[5]), "" if x[6] is None else str(x[6])),
    )

    rating_tiers = sorted(
        {(str(r.rating_color), str(r.rating_text)) for r in df[["rating_color", "rating_text"]].itertuples(index=False)},
        key=lambda x: x[1],
    )

    # Atomic cuisines and M:N restaurant_cuisines pairs
    cuisine_set = set()
    rc_pairs = set()
    for r in df[["restaurant_id", "cuisines"]].itertuples(index=False):
        for c_name in split_cuisines(r.cuisines):
            cuisine_set.add(c_name)
            rc_pairs.add((int(r.restaurant_id), c_name))

    cuisines = sorted(cuisine_set)
    restaurant_cuisines = sorted(rc_pairs)

    return TransformedSilverData(
        staging_df=staging_df,
        countries=countries,
        cities=cities,
        locations=locations,
        rating_tiers=rating_tiers,
        restaurants_df=restaurants_df,
        cuisines=cuisines,
        restaurant_cuisines=restaurant_cuisines,
    )
