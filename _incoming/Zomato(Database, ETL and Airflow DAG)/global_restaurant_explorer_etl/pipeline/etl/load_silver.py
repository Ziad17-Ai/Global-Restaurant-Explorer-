"""
Dependency-aware, transactional, idempotent Silver-layer database loader.
Loads into the existing zomato_restaurant_explorer schema without dropping or
truncating any tables:
  1. stg_zomato_cleaned
  2. countries
  3. cities
  4. locations (never writes MySQL's generated location_hash column)
  5. rating_tiers
  6. restaurants (tracks exact inserted / updated / unchanged counts)
  7. cuisines
  8. restaurant_cuisines (synchronizes changed associations cleanly)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from pipeline.etl.database import DatabaseConnection, DatabaseManager
from pipeline.etl.transform import TransformedSilverData

LocationKey = Tuple[int, str, str, str, Optional[str], Optional[str]]


@dataclass
class SilverLoadMetrics:
    staging_upserted: int = 0
    countries_inserted: int = 0
    cities_inserted: int = 0
    locations_inserted: int = 0
    rating_tiers_inserted: int = 0
    restaurants_inserted: int = 0
    restaurants_updated: int = 0
    restaurants_unchanged: int = 0
    cuisines_inserted: int = 0
    restaurant_cuisines_inserted: int = 0
    restaurant_cuisines_deleted: int = 0
    table_counts: Dict[str, int] = field(default_factory=dict)


KNOWN_COUNTRY_NAMES: Dict[int, str] = {
    1: "India",
    14: "Australia",
    30: "Brazil",
    37: "Canada",
    94: "Indonesia",
    148: "New Zealand",
    162: "Phillipines",
    166: "Qatar",
    184: "Singapore",
    189: "South Africa",
    191: "Sri Lanka",
    208: "Turkey",
    214: "UAE",
    215: "United Kingdom",
    216: "United States",
}


def _norm_dec(val, places: int) -> Optional[str]:
    if val is None:
        return None
    q = Decimal(10) ** (-places)
    return str(Decimal(str(val).strip()).quantize(q))


def _location_key(
    city_id: int,
    address: str,
    locality: str,
    locality_verbose: str,
    longitude,
    latitude,
) -> LocationKey:
    return (
        int(city_id),
        str(address).strip(),
        str(locality).strip(),
        str(locality_verbose).strip(),
        _norm_dec(longitude, 9),
        _norm_dec(latitude, 9),
    )


def _location_fingerprint(key: LocationKey) -> str:
    city_id, address, locality, locality_verbose, lon, lat = key
    lon_s = "NULL" if lon is None else lon
    lat_s = "NULL" if lat is None else lat
    raw = f"{city_id}|{address}|{locality}|{locality_verbose}|{lon_s}|{lat_s}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_silver_layer(db: DatabaseManager, data: TransformedSilverData) -> SilverLoadMetrics:
    """Execute the full Silver relational load inside a single atomic transaction."""
    metrics = SilverLoadMetrics()
    if data.restaurants_df.empty:
        return metrics

    with db.transaction() as conn:
        # 1. Upsert stg_zomato_cleaned
        _upsert_staging(conn, data, metrics)

        # 2. Insert distinct countries
        _load_countries(conn, data.countries, metrics)

        # 3. Insert distinct cities and fetch lookup map
        city_map = _load_cities(conn, data.cities, metrics)

        # 4. Insert distinct locations (NULL-safe) and fetch lookup map
        location_map = _load_locations(conn, data.locations, city_map, metrics)

        # 5. Insert distinct rating_tiers and fetch lookup map
        tier_map = _load_rating_tiers(conn, data.rating_tiers, metrics)

        # 6. Idempotent upsert into restaurants with inserted/updated/unchanged tracking
        _load_restaurants(conn, data, city_map, location_map, tier_map, metrics)

        # 7. Insert distinct cuisines and fetch lookup map
        cuisine_map = _load_cuisines(conn, data.cuisines, metrics)

        # 8. Synchronize restaurant_cuisines M:N bridge
        _sync_restaurant_cuisines(conn, data, cuisine_map, metrics)

        # Capture post-load table counts inside the same transaction
        for tbl in [
            "stg_zomato_cleaned", "countries", "cities", "locations",
            "rating_tiers", "restaurants", "cuisines", "restaurant_cuisines",
        ]:
            row = conn.fetchone(f"SELECT COUNT(*) FROM {tbl}")
            metrics.table_counts[tbl] = int(row[0]) if row else 0

    return metrics


def _upsert_staging(conn: DatabaseConnection, data: TransformedSilverData, metrics: SilverLoadMetrics) -> None:
    rows = [
        (
            int(r.restaurant_id), r.restaurant_name, int(r.country_code), r.city, r.address,
            r.locality, r.locality_verbose, r.longitude, r.latitude, r.cuisines,
            r.average_cost_for_two, r.currency, r.has_table_booking, r.has_online_delivery,
            r.is_delivering_now, r.switch_to_order_menu, int(r.price_range),
            r.aggregate_rating, r.rating_color, r.rating_text, int(r.votes),
        )
        for r in data.staging_df.itertuples(index=False)
    ]

    if conn.dialect == "mysql":
        sql = """
        INSERT INTO stg_zomato_cleaned (
            restaurant_id, restaurant_name, country_code, city, address,
            locality, locality_verbose, longitude, latitude, cuisines,
            average_cost_for_two, currency, has_table_booking, has_online_delivery,
            is_delivering_now, switch_to_order_menu, price_range, aggregate_rating,
            rating_color, rating_text, votes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            restaurant_name      = VALUES(restaurant_name),
            country_code         = VALUES(country_code),
            city                 = VALUES(city),
            address              = VALUES(address),
            locality             = VALUES(locality),
            locality_verbose     = VALUES(locality_verbose),
            longitude            = VALUES(longitude),
            latitude             = VALUES(latitude),
            cuisines             = VALUES(cuisines),
            average_cost_for_two = VALUES(average_cost_for_two),
            currency             = VALUES(currency),
            has_table_booking    = VALUES(has_table_booking),
            has_online_delivery  = VALUES(has_online_delivery),
            is_delivering_now    = VALUES(is_delivering_now),
            switch_to_order_menu = VALUES(switch_to_order_menu),
            price_range          = VALUES(price_range),
            aggregate_rating     = VALUES(aggregate_rating),
            rating_color         = VALUES(rating_color),
            rating_text          = VALUES(rating_text),
            votes                = VALUES(votes)
        """
    else:
        sql = """
        INSERT INTO stg_zomato_cleaned (
            restaurant_id, restaurant_name, country_code, city, address,
            locality, locality_verbose, longitude, latitude, cuisines,
            average_cost_for_two, currency, has_table_booking, has_online_delivery,
            is_delivering_now, switch_to_order_menu, price_range, aggregate_rating,
            rating_color, rating_text, votes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT(restaurant_id) DO UPDATE SET
            restaurant_name      = excluded.restaurant_name,
            country_code         = excluded.country_code,
            city                 = excluded.city,
            address              = excluded.address,
            locality             = excluded.locality,
            locality_verbose     = excluded.locality_verbose,
            longitude            = excluded.longitude,
            latitude             = excluded.latitude,
            cuisines             = excluded.cuisines,
            average_cost_for_two = excluded.average_cost_for_two,
            currency             = excluded.currency,
            has_table_booking    = excluded.has_table_booking,
            has_online_delivery  = excluded.has_online_delivery,
            is_delivering_now    = excluded.is_delivering_now,
            switch_to_order_menu = excluded.switch_to_order_menu,
            price_range          = excluded.price_range,
            aggregate_rating     = excluded.aggregate_rating,
            rating_color         = excluded.rating_color,
            rating_text          = excluded.rating_text,
            votes                = excluded.votes
        """
    conn.executemany(sql, rows)
    metrics.staging_upserted = len(rows)


def _table_has_column(conn: DatabaseConnection, table: str, column: str) -> bool:
    if conn.dialect == "sqlite":
        rows = conn.fetchall(f"PRAGMA table_info({table})")
        return any(str(r[1]).lower() == column.lower() for r in rows)
    rows = conn.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s",
        (table,),
    )
    return any(str(r[0]).lower() == column.lower() for r in rows)


def _load_country_name_lookup(conn: DatabaseConnection) -> Dict[int, str]:
    lookup = dict(KNOWN_COUNTRY_NAMES)
    try:
        for code, name in conn.fetchall("SELECT country_code, country_name FROM stg_country_codes"):
            if name and str(name).strip():
                lookup[int(code)] = str(name).strip()
    except Exception:
        pass
    return lookup


def _load_countries(conn: DatabaseConnection, countries: List[int], metrics: SilverLoadMetrics) -> None:
    existing = {int(r[0]) for r in conn.fetchall("SELECT country_code FROM countries")}
    missing_codes = [c for c in countries if c not in existing]
    if missing_codes:
        verb = "INSERT IGNORE INTO" if conn.dialect == "mysql" else "INSERT OR IGNORE INTO"
        if _table_has_column(conn, "countries", "country_name"):
            name_lookup = _load_country_name_lookup(conn)
            to_insert = [(c, name_lookup.get(c, f"Country {c}")) for c in missing_codes]
            conn.executemany(f"{verb} countries (country_code, country_name) VALUES (%s, %s)", to_insert)
        else:
            to_insert = [(c,) for c in missing_codes]
            conn.executemany(f"{verb} countries (country_code) VALUES (%s)", to_insert)
    metrics.countries_inserted = len(missing_codes)


def _load_cities(
    conn: DatabaseConnection,
    cities: List[Tuple[int, str]],
    metrics: SilverLoadMetrics,
) -> Dict[Tuple[int, str], int]:
    existing_map = {
        (int(r[1]), str(r[2]).strip()): int(r[0])
        for r in conn.fetchall("SELECT city_id, country_code, city_name FROM cities")
    }
    to_insert = [c for c in cities if c not in existing_map]
    if to_insert:
        verb = "INSERT IGNORE INTO" if conn.dialect == "mysql" else "INSERT OR IGNORE INTO"
        conn.executemany(f"{verb} cities (country_code, city_name) VALUES (%s, %s)", to_insert)
    metrics.cities_inserted = len(to_insert)

    return {
        (int(r[1]), str(r[2]).strip()): int(r[0])
        for r in conn.fetchall("SELECT city_id, country_code, city_name FROM cities")
    }


def _fetch_location_map(conn: DatabaseConnection) -> Dict[LocationKey, int]:
    rows = conn.fetchall(
        "SELECT location_id, city_id, address, locality, locality_verbose, longitude, latitude FROM locations"
    )
    return {
        _location_key(r[1], r[2], r[3], r[4], r[5], r[6]): int(r[0])
        for r in rows
    }


def _load_locations(
    conn: DatabaseConnection,
    locations: List[Tuple[int, str, str, str, str, Optional[str], Optional[str]]],
    city_map: Dict[Tuple[int, str], int],
    metrics: SilverLoadMetrics,
) -> Dict[LocationKey, int]:
    existing_map = _fetch_location_map(conn)

    to_insert_mysql = []
    to_insert_sqlite = []
    for country_code, city, address, locality, locality_verbose, lon, lat in locations:
        city_id = city_map[(country_code, city)]
        key = _location_key(city_id, address, locality, locality_verbose, lon, lat)
        if key not in existing_map:
            to_insert_mysql.append((city_id, address, locality, locality_verbose, lon, lat))
            to_insert_sqlite.append((city_id, address, locality, locality_verbose, lon, lat, _location_fingerprint(key)))

    if to_insert_mysql:
        if conn.dialect == "mysql":
            # Never specify location_hash in MySQL — it is a STORED GENERATED column
            conn.executemany(
                """
                INSERT IGNORE INTO locations (
                    city_id, address, locality, locality_verbose, longitude, latitude
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                to_insert_mysql,
            )
        else:
            conn.executemany(
                """
                INSERT OR IGNORE INTO locations (
                    city_id, address, locality, locality_verbose, longitude, latitude, location_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                to_insert_sqlite,
            )
    metrics.locations_inserted = len(to_insert_mysql)

    return _fetch_location_map(conn)


def _load_rating_tiers(
    conn: DatabaseConnection,
    tiers: List[Tuple[str, str]],
    metrics: SilverLoadMetrics,
) -> Dict[Tuple[str, str], int]:
    existing_map = {
        (str(r[1]).strip(), str(r[2]).strip()): int(r[0])
        for r in conn.fetchall("SELECT rating_tier_id, rating_color, rating_text FROM rating_tiers")
    }
    to_insert = [t for t in tiers if t not in existing_map]
    if to_insert:
        verb = "INSERT IGNORE INTO" if conn.dialect == "mysql" else "INSERT OR IGNORE INTO"
        conn.executemany(f"{verb} rating_tiers (rating_color, rating_text) VALUES (%s, %s)", to_insert)
    metrics.rating_tiers_inserted = len(to_insert)

    return {
        (str(r[1]).strip(), str(r[2]).strip()): int(r[0])
        for r in conn.fetchall("SELECT rating_tier_id, rating_color, rating_text FROM rating_tiers")
    }


def _load_restaurants(
    conn: DatabaseConnection,
    data: TransformedSilverData,
    city_map: Dict[Tuple[int, str], int],
    location_map: Dict[LocationKey, int],
    tier_map: Dict[Tuple[str, str], int],
    metrics: SilverLoadMetrics,
) -> None:
    existing_rows = {
        int(r[0]): (
            str(r[1]).strip(), int(r[2]), _norm_dec(r[3], 2), str(r[4]).strip(),
            int(r[5]), int(r[6]), int(r[7]), int(r[8]),
            int(r[9]), _norm_dec(r[10], 1), int(r[11]), int(r[12]),
        )
        for r in conn.fetchall(
            """
            SELECT restaurant_id, restaurant_name, location_id, average_cost_for_two,
                   currency, has_table_booking, has_online_delivery, is_delivering_now,
                   switch_to_order_menu, price_range, aggregate_rating, rating_tier_id, votes
            FROM restaurants
            """
        )
    }

    to_insert = []
    to_update = []
    unchanged = 0

    for r in data.restaurants_df.itertuples(index=False):
        rid = int(r.restaurant_id)
        city_id = city_map[(int(r.country_code), str(r.city))]
        loc_key = _location_key(city_id, r.address, r.locality, r.locality_verbose, r.longitude, r.latitude)
        location_id = location_map[loc_key]
        rating_tier_id = tier_map[(str(r.rating_color), str(r.rating_text))]

        comparable = (
            str(r.restaurant_name),
            int(location_id),
            _norm_dec(r.average_cost_for_two, 2),
            str(r.currency),
            int(r.has_table_booking),
            int(r.has_online_delivery),
            int(r.is_delivering_now),
            int(r.switch_to_order_menu),
            int(r.price_range),
            _norm_dec(r.aggregate_rating, 1),
            int(rating_tier_id),
            int(r.votes),
        )

        if rid not in existing_rows:
            to_insert.append((rid, *comparable))
        elif existing_rows[rid] != comparable:
            to_update.append((*comparable, rid))
        else:
            unchanged += 1

    if to_insert:
        conn.executemany(
            """
            INSERT INTO restaurants (
                restaurant_id, restaurant_name, location_id, average_cost_for_two,
                currency, has_table_booking, has_online_delivery, is_delivering_now,
                switch_to_order_menu, price_range, aggregate_rating, rating_tier_id, votes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            to_insert,
        )

    if to_update:
        conn.executemany(
            """
            UPDATE restaurants
            SET restaurant_name      = %s,
                location_id          = %s,
                average_cost_for_two = %s,
                currency             = %s,
                has_table_booking    = %s,
                has_online_delivery  = %s,
                is_delivering_now    = %s,
                switch_to_order_menu = %s,
                price_range          = %s,
                aggregate_rating     = %s,
                rating_tier_id       = %s,
                votes                = %s
            WHERE restaurant_id = %s
            """,
            to_update,
        )

    metrics.restaurants_inserted = len(to_insert)
    metrics.restaurants_updated = len(to_update)
    metrics.restaurants_unchanged = unchanged


def _load_cuisines(
    conn: DatabaseConnection,
    cuisines: List[str],
    metrics: SilverLoadMetrics,
) -> Dict[str, int]:
    existing_map = {
        str(r[1]).strip(): int(r[0])
        for r in conn.fetchall("SELECT cuisine_id, cuisine_name FROM cuisines")
    }
    to_insert = [(c,) for c in cuisines if c not in existing_map]
    if to_insert:
        verb = "INSERT IGNORE INTO" if conn.dialect == "mysql" else "INSERT OR IGNORE INTO"
        conn.executemany(f"{verb} cuisines (cuisine_name) VALUES (%s)", to_insert)
    metrics.cuisines_inserted = len(to_insert)

    return {
        str(r[1]).strip(): int(r[0])
        for r in conn.fetchall("SELECT cuisine_id, cuisine_name FROM cuisines")
    }


def _sync_restaurant_cuisines(
    conn: DatabaseConnection,
    data: TransformedSilverData,
    cuisine_map: Dict[str, int],
    metrics: SilverLoadMetrics,
) -> None:
    """
    Synchronize M:N associations for all restaurants in the incoming batch:
    - Removes outdated cuisine associations for restaurants whose cuisines changed.
    - Inserts missing new associations.
    - Leaves untouched restaurants absent from the current batch.
    """
    batch_rids = set(int(x) for x in data.restaurants_df["restaurant_id"].tolist())

    desired_by_rid: Dict[int, Set[int]] = {rid: set() for rid in batch_rids}
    for rid, c_name in data.restaurant_cuisines:
        desired_by_rid[rid].add(cuisine_map[c_name])

    existing_by_rid: Dict[int, Set[int]] = {}
    for rid, cid in conn.fetchall("SELECT restaurant_id, cuisine_id FROM restaurant_cuisines"):
        rid_i = int(rid)
        if rid_i in batch_rids:
            existing_by_rid.setdefault(rid_i, set()).add(int(cid))

    to_delete = []
    to_insert = []
    for rid, desired_cids in desired_by_rid.items():
        current_cids = existing_by_rid.get(rid, set())
        for stale_cid in current_cids - desired_cids:
            to_delete.append((rid, stale_cid))
        for new_cid in desired_cids - current_cids:
            to_insert.append((rid, new_cid))

    if to_delete:
        conn.executemany(
            "DELETE FROM restaurant_cuisines WHERE restaurant_id = %s AND cuisine_id = %s",
            to_delete,
        )
    if to_insert:
        verb = "INSERT IGNORE INTO" if conn.dialect == "mysql" else "INSERT OR IGNORE INTO"
        conn.executemany(
            f"{verb} restaurant_cuisines (restaurant_id, cuisine_id) VALUES (%s, %s)",
            to_insert,
        )

    metrics.restaurant_cuisines_deleted = len(to_delete)
    metrics.restaurant_cuisines_inserted = len(to_insert)
