"""Unit tests covering extraction, Bronze storage, Silver validation, and transformations."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from pipeline.etl.extract import EXPECTED_CSV_COLUMNS, compute_sha256, validate_csv_schema
from pipeline.etl.transform import split_cuisines, transform_to_silver
from pipeline.etl.validation import validate_dataframe
from pipeline.storage.local_storage import LocalBronzeStorage


def _make_row(**overrides) -> dict:
    base = {
        "_source_row_number": 2,
        "Restaurant ID": "1001",
        "Restaurant Name": "Cafe Éclair",
        "Country Code": "1",
        "City": "New Delhi",
        "Address": "12 Main St",
        "Locality": "Central",
        "Locality Verbose": "Central, New Delhi",
        "Longitude": "77.216721",
        "Latitude": "28.644800",
        "Cuisines": "French, Japanese, Desserts",
        "Average Cost for two": "25.50",
        "Currency": "Dollar($)",
        "Has Table booking": "Yes",
        "Has Online delivery": "No",
        "Is delivering now": "No",
        "Switch to order menu": "No",
        "Price range": "2",
        "Aggregate rating": "4.5",
        "Rating color": "Dark Green",
        "Rating text": "Excellent",
        "Votes": "150",
    }
    base.update(overrides)
    return base


class TestETLUnit(unittest.TestCase):
    def test_schema_validation(self):
        missing, unexpected = validate_csv_schema(EXPECTED_CSV_COLUMNS)
        self.assertEqual(missing, [])
        self.assertEqual(unexpected, [])

        missing2, unexpected2 = validate_csv_schema(EXPECTED_CSV_COLUMNS[:-1] + ["Extra Col"])
        self.assertEqual(missing2, ["Votes"])
        self.assertEqual(unexpected2, ["Extra Col"])

    def test_split_cuisines_dedup_and_non_ascii(self):
        self.assertEqual(split_cuisines("French, Japanese, Desserts"), ["French", "Japanese", "Desserts"])
        self.assertEqual(split_cuisines("Bakery, Desserts, Bakery"), ["Bakery", "Desserts"])
        self.assertEqual(split_cuisines("Café,  , Patisserie"), ["Café", "Patisserie"])
        self.assertEqual(split_cuisines(""), [])
        self.assertEqual(split_cuisines(None), [])

    def test_missing_coords_and_cuisines_accepted(self):
        df = pd.DataFrame([_make_row(Longitude="", Latitude="", Cuisines="")])
        res = validate_dataframe(df)
        self.assertEqual(len(res.valid_df), 1)
        self.assertEqual(len(res.quarantine_records), 0)
        self.assertEqual(res.summary_by_severity["WARNING"], 1)
        self.assertEqual(res.summary_by_severity["INFO"], 1)

        silver = transform_to_silver(res.valid_df)
        self.assertIsNone(silver.staging_df.iloc[0]["longitude"])
        self.assertIsNone(silver.staging_df.iloc[0]["latitude"])
        self.assertIsNone(silver.staging_df.iloc[0]["cuisines"])
        self.assertEqual(silver.restaurant_cuisines, [])

    def test_invalid_records_quarantined(self):
        bad_rows = [
            _make_row(**{"_source_row_number": 2, "Restaurant ID": "1001", "Longitude": "77.2", "Latitude": ""}),  # half null
            _make_row(**{"_source_row_number": 3, "Restaurant ID": "1002", "Average Cost for two": "-5.00"}),       # negative cost
            _make_row(**{"_source_row_number": 4, "Restaurant ID": "1003", "Price range": "9"}),                    # bad price range
            _make_row(**{"_source_row_number": 5, "Restaurant ID": "1004", "Has Online delivery": "Maybe"}),        # bad boolean
            _make_row(**{"_source_row_number": 6, "Restaurant ID": "1005", "Aggregate rating": "6.2"}),             # bad rating
            _make_row(**{"_source_row_number": 7, "Restaurant ID": "1006", "Rating color": "Blue", "Rating text": "Super"}),  # unknown tier
        ]
        res = validate_dataframe(pd.DataFrame(bad_rows))
        self.assertEqual(len(res.valid_df), 0)
        self.assertEqual(len(res.quarantine_records), 6)

    def test_duplicate_restaurant_id_quarantined(self):
        df = pd.DataFrame([
            _make_row(**{"_source_row_number": 2, "Restaurant ID": "555"}),
            _make_row(**{"_source_row_number": 3, "Restaurant ID": "555", "Restaurant Name": "Duplicate ID"}),
        ])
        res = validate_dataframe(df)
        self.assertEqual(len(res.valid_df), 1)
        self.assertEqual(len(res.quarantine_records), 1)
        self.assertEqual(res.duplicate_restaurant_id_count, 1)

    def test_boolean_and_transform_accuracy(self):
        df = pd.DataFrame([_make_row()])
        res = validate_dataframe(df)
        silver = transform_to_silver(res.valid_df)
        row = silver.restaurants_df.iloc[0]
        self.assertEqual(int(row["has_table_booking"]), 1)
        self.assertEqual(int(row["has_online_delivery"]), 0)
        self.assertEqual(silver.staging_df.iloc[0]["has_table_booking"], "Yes")
        self.assertEqual(len(silver.restaurant_cuisines), 3)

    def test_bronze_immutability_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "sample.csv"
            src.write_text("a,b\n1,2\n", encoding="utf-8")
            sha = compute_sha256(src)
            storage = LocalBronzeStorage(tmp_path / "bronze")
            meta = {"source_file_hash": sha, "source_file_size": src.stat().st_size}

            stored = storage.store_batch(src, "zomato", "batch-1", "2026-11-19", meta)
            self.assertTrue(Path(stored.uri).exists())
            self.assertTrue(Path(stored.metadata_uri).exists())
            self.assertEqual(compute_sha256(Path(stored.uri)), sha)

            with self.assertRaises(FileExistsError):
                storage.store_batch(src, "zomato", "batch-1", "2026-11-19", meta)

    def test_nan_infinity_and_oversized_strings_quarantined(self):
        bad_rows = [
            _make_row(**{"_source_row_number": 2, "Restaurant ID": "2001", "Longitude": "NaN", "Latitude": "28.6"}),
            _make_row(**{"_source_row_number": 3, "Restaurant ID": "2002", "Average Cost for two": "Infinity"}),
            _make_row(**{"_source_row_number": 4, "Restaurant ID": "2003", "Aggregate rating": "NaN"}),
            _make_row(**{"_source_row_number": 5, "Restaurant ID": "2004", "Restaurant Name": "X" * 101}),
        ]
        res = validate_dataframe(pd.DataFrame(bad_rows))
        self.assertEqual(len(res.valid_df), 0)
        self.assertEqual(len(res.quarantine_records), 4)


if __name__ == "__main__":
    unittest.main()
