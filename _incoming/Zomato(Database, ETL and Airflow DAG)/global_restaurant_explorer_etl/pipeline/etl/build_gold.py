"""Gold layer view builder and query-verification module."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List

from pipeline.etl.database import DatabaseManager, _split_sql_statements

GOLD_VIEWS: List[str] = [
    "v_restaurant_explorer",
    "gold_restaurant_search",
    "gold_city_restaurant_stats",
    "gold_country_restaurant_stats",
    "gold_cuisine_stats",
    "gold_price_range_stats",
    "gold_rating_distribution",
    "gold_geographic_coverage",
]


@dataclass
class GoldBuildResult:
    views_verified: Dict[str, int] = field(default_factory=dict)
    query_timings_ms: Dict[str, float] = field(default_factory=dict)
    total_duration_ms: float = 0.0


def build_gold_views(db: DatabaseManager) -> GoldBuildResult:
    """Apply additive Gold views (Migration 002) and verify row counts & query latencies."""
    t0 = time.perf_counter()
    if db.dialect == "mysql":
        migration_file = db.config.project_root / "sql" / "migrations" / "002_create_gold_views.sql"
        sql_script = migration_file.read_text(encoding="utf-8")
        with db.transaction() as conn:
            for stmt in _split_sql_statements(sql_script):
                conn.execute(stmt)
    else:
        with db.transaction() as conn:
            for stmt in _sqlite_gold_views_ddl():
                conn.execute(stmt)

    result = GoldBuildResult()
    with db.transaction() as conn:
        for view_name in GOLD_VIEWS:
            q_start = time.perf_counter()
            row = conn.fetchone(f"SELECT COUNT(*) FROM {view_name}")
            q_ms = (time.perf_counter() - q_start) * 1000.0
            result.views_verified[view_name] = int(row[0]) if row else 0
            result.query_timings_ms[view_name] = round(q_ms, 2)

    result.total_duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return result


def _sqlite_gold_views_ddl() -> List[str]:
    """SQLite-compatible equivalents of 002_create_gold_views.sql for isolated testing."""
    return [
        "DROP VIEW IF EXISTS gold_restaurant_search",
        """CREATE VIEW gold_restaurant_search AS
        SELECT
            v.restaurant_id, v.restaurant_name, v.country_code, v.city_name AS city,
            v.address, v.locality, v.longitude, v.latitude,
            GROUP_CONCAT(c.cuisine_name, ', ') AS cuisines,
            COUNT(DISTINCT c.cuisine_id) AS cuisine_count,
            v.average_cost_for_two, v.currency,
            v.has_table_booking, v.has_online_delivery, v.is_delivering_now,
            v.price_range, v.aggregate_rating, v.rating_color, v.rating_text, v.votes
        FROM v_restaurant_explorer v
        LEFT JOIN restaurant_cuisines rc ON rc.restaurant_id = v.restaurant_id
        LEFT JOIN cuisines c             ON c.cuisine_id     = rc.cuisine_id
        GROUP BY v.restaurant_id""",

        "DROP VIEW IF EXISTS gold_city_restaurant_stats",
        """CREATE VIEW gold_city_restaurant_stats AS
        SELECT
            v.country_code, v.city_id, v.city_name AS city,
            COUNT(v.restaurant_id) AS total_restaurants,
            SUM(CASE WHEN v.aggregate_rating > 0 THEN 1 ELSE 0 END) AS rated_restaurants,
            ROUND(AVG(CASE WHEN v.aggregate_rating > 0 THEN v.aggregate_rating END), 2) AS avg_rated_rating,
            ROUND(AVG(v.average_cost_for_two), 2) AS avg_cost_for_two,
            SUM(CASE WHEN v.price_range = 1 THEN 1 ELSE 0 END) AS price_range_1_count,
            SUM(CASE WHEN v.price_range = 2 THEN 1 ELSE 0 END) AS price_range_2_count,
            SUM(CASE WHEN v.price_range = 3 THEN 1 ELSE 0 END) AS price_range_3_count,
            SUM(CASE WHEN v.price_range = 4 THEN 1 ELSE 0 END) AS price_range_4_count,
            SUM(CASE WHEN v.longitude IS NOT NULL AND v.latitude IS NOT NULL THEN 1 ELSE 0 END) AS restaurants_with_coordinates
        FROM v_restaurant_explorer v
        GROUP BY v.country_code, v.city_id, v.city_name""",

        "DROP VIEW IF EXISTS gold_country_restaurant_stats",
        """CREATE VIEW gold_country_restaurant_stats AS
        SELECT
            v.country_code,
            COUNT(DISTINCT v.city_id) AS city_count,
            COUNT(v.restaurant_id) AS total_restaurants,
            SUM(CASE WHEN v.aggregate_rating > 0 THEN 1 ELSE 0 END) AS rated_restaurants,
            ROUND(AVG(CASE WHEN v.aggregate_rating > 0 THEN v.aggregate_rating END), 2) AS avg_rated_rating,
            ROUND(AVG(v.average_cost_for_two), 2) AS avg_cost_for_two,
            ROUND(100.0 * AVG(v.has_online_delivery), 2) AS pct_online_delivery,
            ROUND(100.0 * AVG(v.has_table_booking), 2) AS pct_table_booking,
            SUM(CASE WHEN v.longitude IS NOT NULL AND v.latitude IS NOT NULL THEN 1 ELSE 0 END) AS restaurants_with_coordinates
        FROM v_restaurant_explorer v
        GROUP BY v.country_code""",

        "DROP VIEW IF EXISTS gold_cuisine_stats",
        """CREATE VIEW gold_cuisine_stats AS
        SELECT
            c.cuisine_id, c.cuisine_name,
            COUNT(DISTINCT rc.restaurant_id) AS restaurant_count,
            ROUND(AVG(CASE WHEN r.aggregate_rating > 0 THEN r.aggregate_rating END), 2) AS avg_restaurant_rating,
            ROUND(AVG(r.average_cost_for_two), 2) AS avg_restaurant_cost,
            SUM(r.votes) AS total_votes,
            COUNT(DISTINCT l.city_id) AS distinct_cities
        FROM cuisines c
        JOIN restaurant_cuisines rc ON rc.cuisine_id    = c.cuisine_id
        JOIN restaurants r          ON r.restaurant_id  = rc.restaurant_id
        JOIN locations l            ON l.location_id    = r.location_id
        GROUP BY c.cuisine_id, c.cuisine_name""",

        "DROP VIEW IF EXISTS gold_price_range_stats",
        """CREATE VIEW gold_price_range_stats AS
        SELECT
            r.price_range,
            COUNT(*) AS restaurant_count,
            ROUND(MIN(r.average_cost_for_two), 2) AS min_cost,
            ROUND(AVG(r.average_cost_for_two), 2) AS avg_cost,
            ROUND(MAX(r.average_cost_for_two), 2) AS max_cost,
            ROUND(AVG(CASE WHEN r.aggregate_rating > 0 THEN r.aggregate_rating END), 2) AS avg_rated_rating,
            ROUND(100.0 * AVG(r.has_table_booking), 2) AS pct_table_booking,
            ROUND(100.0 * AVG(r.has_online_delivery), 2) AS pct_online_delivery
        FROM restaurants r
        GROUP BY r.price_range""",

        "DROP VIEW IF EXISTS gold_rating_distribution",
        """CREATE VIEW gold_rating_distribution AS
        SELECT
            r.aggregate_rating, rt.rating_color, rt.rating_text,
            COUNT(r.restaurant_id) AS restaurant_count,
            SUM(r.votes) AS total_votes,
            ROUND(AVG(r.votes), 1) AS avg_votes
        FROM restaurants r
        JOIN rating_tiers rt ON rt.rating_tier_id = r.rating_tier_id
        GROUP BY r.aggregate_rating, rt.rating_color, rt.rating_text""",

        "DROP VIEW IF EXISTS gold_geographic_coverage",
        """CREATE VIEW gold_geographic_coverage AS
        SELECT
            v.country_code, v.city_id, v.city_name AS city,
            COUNT(v.restaurant_id) AS total_restaurants,
            SUM(CASE WHEN v.longitude IS NOT NULL AND v.latitude IS NOT NULL THEN 1 ELSE 0 END) AS restaurants_with_coordinates,
            SUM(CASE WHEN v.longitude IS NULL     AND v.latitude IS NULL     THEN 1 ELSE 0 END) AS restaurants_without_coordinates,
            ROUND(
                100.0 * SUM(CASE WHEN v.longitude IS NOT NULL AND v.latitude IS NOT NULL THEN 1 ELSE 0 END)
                / NULLIF(COUNT(v.restaurant_id), 0),
                2
            ) AS coordinate_completeness_pct
        FROM v_restaurant_explorer v
        GROUP BY v.country_code, v.city_id, v.city_name""",

        "INSERT OR IGNORE INTO etl_schema_migrations (migration_version, migration_name) VALUES ('002', 'create_gold_views')",
    ]
