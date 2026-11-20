"""
End-to-end integration, idempotency, incremental sync, and quarantine tests
running the full ETL pipeline against the actual 9,550-row zomato_cleaned.csv
using an isolated SQLite mirror of the zomato_restaurant_explorer schema.
"""

from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline.etl.config import ETLConfig
from pipeline.etl.runner import run_pipeline

REAL_CSV = Path(__file__).resolve().parents[2] / "data" / "zomato_cleaned.csv"


def _init_core_sqlite_schema(db_path: Path) -> None:
    """Provision the exact 8 existing core tables + v_restaurant_explorer view in an isolated test DB."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE stg_zomato_cleaned (
        restaurant_id INTEGER PRIMARY KEY, restaurant_name TEXT NOT NULL, country_code INTEGER NOT NULL,
        city TEXT NOT NULL, address TEXT NOT NULL, locality TEXT NOT NULL, locality_verbose TEXT NOT NULL,
        longitude REAL NULL, latitude REAL NULL, cuisines TEXT NULL, average_cost_for_two REAL NOT NULL,
        currency TEXT NOT NULL, has_table_booking TEXT NOT NULL, has_online_delivery TEXT NOT NULL,
        is_delivering_now TEXT NOT NULL, switch_to_order_menu TEXT NOT NULL, price_range INTEGER NOT NULL,
        aggregate_rating REAL NOT NULL, rating_color TEXT NOT NULL, rating_text TEXT NOT NULL, votes INTEGER NOT NULL
    );
    CREATE TABLE countries (country_code INTEGER PRIMARY KEY, country_name TEXT NOT NULL UNIQUE CHECK (LENGTH(TRIM(country_name)) > 0));
    CREATE TABLE cities (
        city_id INTEGER PRIMARY KEY AUTOINCREMENT,
        country_code INTEGER NOT NULL REFERENCES countries(country_code),
        city_name TEXT NOT NULL,
        UNIQUE(country_code, city_name)
    );
    CREATE TABLE locations (
        location_id INTEGER PRIMARY KEY AUTOINCREMENT,
        city_id INTEGER NOT NULL REFERENCES cities(city_id),
        address TEXT NOT NULL, locality TEXT NOT NULL, locality_verbose TEXT NOT NULL,
        longitude REAL NULL, latitude REAL NULL, location_hash TEXT NOT NULL UNIQUE,
        CHECK ((longitude IS NULL) = (latitude IS NULL))
    );
    CREATE TABLE rating_tiers (
        rating_tier_id INTEGER PRIMARY KEY AUTOINCREMENT,
        rating_color TEXT NOT NULL UNIQUE,
        rating_text TEXT NOT NULL UNIQUE
    );
    CREATE TABLE restaurants (
        restaurant_id INTEGER PRIMARY KEY, restaurant_name TEXT NOT NULL,
        location_id INTEGER NOT NULL REFERENCES locations(location_id),
        average_cost_for_two REAL NOT NULL CHECK (average_cost_for_two >= 0.0),
        currency TEXT NOT NULL,
        has_table_booking INTEGER NOT NULL CHECK (has_table_booking IN (0, 1)),
        has_online_delivery INTEGER NOT NULL CHECK (has_online_delivery IN (0, 1)),
        is_delivering_now INTEGER NOT NULL CHECK (is_delivering_now IN (0, 1)),
        switch_to_order_menu INTEGER NOT NULL CHECK (switch_to_order_menu IN (0, 1)),
        price_range INTEGER NOT NULL CHECK (price_range BETWEEN 1 AND 4),
        aggregate_rating REAL NOT NULL CHECK (aggregate_rating BETWEEN 0.0 AND 5.0),
        rating_tier_id INTEGER NOT NULL REFERENCES rating_tiers(rating_tier_id),
        votes INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE cuisines (
        cuisine_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cuisine_name TEXT NOT NULL UNIQUE
    );
    CREATE TABLE restaurant_cuisines (
        restaurant_id INTEGER NOT NULL REFERENCES restaurants(restaurant_id) ON DELETE CASCADE,
        cuisine_id INTEGER NOT NULL REFERENCES cuisines(cuisine_id) ON DELETE RESTRICT,
        PRIMARY KEY (restaurant_id, cuisine_id)
    );
    CREATE VIEW v_restaurant_explorer AS
    SELECT
        r.restaurant_id, r.restaurant_name, co.country_code, co.country_name, ci.city_id, ci.city_name,
        l.location_id, l.address, l.locality, l.locality_verbose, l.longitude, l.latitude,
        r.average_cost_for_two, r.currency, r.has_table_booking, r.has_online_delivery,
        r.is_delivering_now, r.switch_to_order_menu, r.price_range, r.aggregate_rating,
        rt.rating_color, rt.rating_text, r.votes
    FROM restaurants r
    JOIN locations l ON l.location_id = r.location_id
    JOIN cities ci ON ci.city_id = l.city_id
    JOIN countries co ON co.country_code = ci.country_code
    JOIN rating_tiers rt ON rt.rating_tier_id = r.rating_tier_id;
    """)
    conn.commit()
    conn.close()


class TestPipelineE2E(unittest.TestCase):
    def test_full_pipeline_idempotency_and_incremental_quarantine(self):
        self.assertTrue(REAL_CSV.exists(), "zomato_cleaned.csv must exist for E2E test")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test_zomato.sqlite"
            _init_core_sqlite_schema(db_path)

            cfg = ETLConfig(
                db_dialect="sqlite",
                db_host="localhost",
                db_port=3306,
                db_name="zomato_restaurant_explorer",
                db_user="",
                db_password="",
                db_pool_size=5,
                db_connect_timeout=15,
                sqlite_db_path=db_path,
                storage_backend="local",
                bronze_local_path=root / "bronze",
                quarantine_path=root / "quarantine",
                reports_path=root / "reports",
                logs_path=root / "logs",
                azure_connection_string=None,
                azure_account_url=None,
                azure_container="",
                project_root=Path(__file__).resolve().parents[2],
            )

            # 1. First Full Run on actual 9,550-row CSV
            r1 = run_pipeline(cfg, source_path=REAL_CSV, mode="full")
            self.assertEqual(r1["status"], "SUCCESS")
            self.assertEqual(r1["extracted_rows"], 9550)
            self.assertEqual(r1["accepted_rows"], 9550)
            self.assertEqual(r1["rejected_rows"], 0)
            self.assertEqual(r1["silver_load"]["restaurants_inserted"], 9550)
            self.assertEqual(r1["silver_load"]["table_counts"], {
                "stg_zomato_cleaned": 9550,
                "countries": 15,
                "cities": 141,
                "locations": 9453,
                "rating_tiers": 6,
                "restaurants": 9550,
                "cuisines": 145,
                "restaurant_cuisines": 19703,
            })
            self.assertEqual(r1["gold_layer"]["views_verified"]["gold_restaurant_search"], 9550)
            self.assertEqual(r1["gold_layer"]["views_verified"]["gold_city_restaurant_stats"], 141)
            self.assertEqual(r1["gold_layer"]["views_verified"]["gold_country_restaurant_stats"], 15)
            self.assertEqual(r1["gold_layer"]["views_verified"]["gold_cuisine_stats"], 145)
            self.assertEqual(r1["gold_layer"]["views_verified"]["gold_price_range_stats"], 4)

            # 2. Second Identical Run (Idempotency Check)
            r2 = run_pipeline(cfg, source_path=REAL_CSV, mode="full")
            self.assertEqual(r2["status"], "SUCCESS")
            self.assertTrue(r2.get("duplicate_source_detected"))
            self.assertEqual(r2["silver_load"]["restaurants_inserted"], 0)
            self.assertEqual(r2["silver_load"]["restaurants_updated"], 0)
            self.assertEqual(r2["silver_load"]["restaurants_unchanged"], 9550)
            self.assertEqual(r2["silver_load"]["restaurant_cuisines_inserted"], 0)
            self.assertEqual(r2["silver_load"]["restaurant_cuisines_deleted"], 0)
            self.assertEqual(r2["silver_load"]["table_counts"]["restaurants"], 9550)

            # 3. Incremental Update + Cuisine Synchronization + Quarantine Test
            inc_csv = root / "incremental.csv"
            with REAL_CSV.open("r", encoding="utf-8", newline="") as f:
                first_row = next(csv.DictReader(f))

            updated_row = dict(first_row)
            updated_row["Aggregate rating"] = "4.9"
            updated_row["Rating color"] = "Dark Green"
            updated_row["Rating text"] = "Excellent"
            updated_row["Cuisines"] = "Egyptian, Mediterranean"

            new_row = dict(first_row)
            new_row["Restaurant ID"] = "99999901"
            new_row["Restaurant Name"] = "Alexandria Harbor Grill"
            new_row["Country Code"] = "999"  # Unseeded country_code verifies strict countries.country_name insert
            new_row["Cuisines"] = "Seafood, Egyptian"

            bad_row = dict(first_row)
            bad_row["Restaurant ID"] = "99999902"
            bad_row["Average Cost for two"] = "-10.00"

            with inc_csv.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(first_row.keys()))
                writer.writeheader()
                writer.writerows([updated_row, new_row, bad_row])

            r3 = run_pipeline(cfg, source_path=inc_csv, mode="full")
            self.assertEqual(r3["status"], "PARTIAL_SUCCESS")
            self.assertEqual(r3["accepted_rows"], 2)
            self.assertEqual(r3["rejected_rows"], 1)
            self.assertEqual(r3["silver_load"]["restaurants_inserted"], 1)
            self.assertEqual(r3["silver_load"]["restaurants_updated"], 1)
            self.assertGreater(r3["silver_load"]["restaurant_cuisines_deleted"], 0)
            self.assertTrue(Path(r3["quarantine_file"]).exists())
            self.assertEqual(r3["silver_load"]["table_counts"]["restaurants"], 9551)


if __name__ == "__main__":
    unittest.main()
