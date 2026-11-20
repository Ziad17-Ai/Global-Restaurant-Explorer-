# Global Restaurant Explorer Platform — ETL Execution & Data Quality Report

**Source File:** `zomato_cleaned.csv` (`2,184,843` bytes)  
**SHA-256 Checksum:** `b7b827b6a61a23b281af014b5622a0f5cc979052b107269fe54e841a233eb27e`  
**Execution Environment:** Python 3.11.2 / Pandas 2.2.3 / Isolated SQLite 3 schema mirror (`PRAGMA foreign_keys = ON`)  
**Important Environment Note:** Live MySQL 8.0 Server (`mysqld`), `SQLAlchemy`, `PyMySQL`, and Azure credentials are not installed or configured in this offline sandbox. All MySQL 8.0 migrations (`001_create_etl_metadata.sql`, `002_create_gold_views.sql`) and SQLAlchemy/PyMySQL + Azure Blob adapters are implemented and ready for execution against your local MySQL 8.0 Server, while full end-to-end execution, idempotency, incremental updates, quarantine, and Gold view verification ran against the isolated SQLite mirror of `zomato_restaurant_explorer`.

## 1. End-to-End CLI Execution Summary (Run 1 vs. Run 2 Idempotency)

| Metric | Run 1 (`baseline-run-001`) | Run 2 (`idempotency-run-002`) | Dry Run (`dryrun-003`) |
| :--- | ---: | ---: | ---: |
| Execution Status | `SUCCESS` | `SUCCESS` | `SUCCESS` |
| Extracted Rows | 9,550 | 9,550 | 9,550 |
| Accepted Rows | 9,550 | 9,550 | 9,550 |
| Quarantined (Rejected) Rows | 0 | 0 | 0 |
| Bronze Status | `STORED` | `SKIPPED_EXISTING_HASH` | Not Written (`dry_run=True`) |
| Silver Restaurants Inserted | 9,550 | 0 | 0 |
| Silver Restaurants Updated | 0 | 0 | 0 |
| Silver Restaurants Unchanged | 0 | 9,550 | 0 |
| `restaurant_cuisines` Inserted / Deleted | 19,703 / 0 | 0 / 0 | 0 / 0 |
| Total Execution Time (ms) | 1,374.40 | 1,337.02 | 832.10 |

## 2. Silver Layer Baseline Reconciliation

| Target Table | Post-Run 1 Count | Post-Run 2 Count | Expected Baseline | Status |
| :--- | ---: | ---: | ---: | :---: |
| `stg_zomato_cleaned` | 9,550 | 9,550 | 9,550 | PASS |
| `countries` | 15 | 15 | 15 | PASS |
| `cities` | 141 | 141 | 141 | PASS |
| `locations` | 9,453 | 9,453 | 9,453 | PASS |
| `rating_tiers` | 6 | 6 | 6 | PASS |
| `restaurants` | 9,550 | 9,550 | 9,550 | PASS |
| `cuisines` | 145 | 145 | 145 | PASS |
| `restaurant_cuisines` | 19,703 | 19,703 | 19,703 | PASS |

## 3. Data Quality Findings (Baseline Dataset)

| Severity | Issue Type | Count | Pipeline Action |
| :--- | :--- | ---: | :--- |
| `WARNING` | `MISSING_COORDINATES` | 497 | Accepted; preserved as SQL `NULL` in `locations` |
| `INFO` | `MISSING_CUISINES` | 9 | Accepted; 0 rows in `restaurant_cuisines` |
| `INFO` | `DUPLICATE_CUISINE_IN_ROW` | 5 | Accepted; deduplicated during Silver transformation |
| `ERROR` | Schema / Domain Violations | 0 | None in baseline CSV (quarantine verified in unit & integration tests) |
| `CRITICAL` | Missing / Invalid Restaurant ID | 0 | None in baseline CSV (quarantine verified in unit tests) |

## 4. Gold Layer View Verification & Query Latency

| Gold View | Verified Row Count | Run 1 Query Latency (ms) | Run 2 Query Latency (ms) |
| :--- | ---: | ---: | ---: |
| `v_restaurant_explorer` (preserved) | 9,550 | 5.42 | 6.30 |
| `gold_restaurant_search` | 9,550 | 30.05 | 30.13 |
| `gold_city_restaurant_stats` | 141 | 13.88 | 14.82 |
| `gold_country_restaurant_stats` | 15 | 9.78 | 9.78 |
| `gold_cuisine_stats` | 145 | 27.23 | 24.91 |
| `gold_price_range_stats` | 4 | 4.88 | 4.83 |
| `gold_rating_distribution` | 33 | 7.77 | 7.60 |
| `gold_geographic_coverage` | 141 | 10.96 | 10.72 |

## 5. Stage Performance Breakdown (`baseline-run-001`)

| Pipeline Stage | Duration (ms) |
| :--- | ---: |
| `extract` | 39.94 |
| `bronze` | 1.61 |
| `validate` | 679.26 |
| `transform` | 120.57 |
| `silver_load` | 313.82 |
| `gold_refresh` | 141.70 |
| `total_pipeline` | 1,374.40 |

## 6. Automated Test Suite Results (`python -m unittest discover -s tests -v`)

All **8 / 8** automated tests passed in **2.625 seconds**:

- **Unit Tests (7/7 PASS):** Schema validation, cuisine splitting/dedup/non-ASCII preservation, missing coordinate & cuisine acceptance, 6 quarantine failure modes (half-null coords, negative cost, bad price range, invalid boolean, invalid rating, unknown rating tier), duplicate restaurant ID quarantine, boolean/Silver transform accuracy, and Bronze immutability/SHA-256 verification.
- **Integration Test (1/1 PASS):** Full 9,550-row Run 1 + Run 2 idempotency + Run 3 incremental update (updated restaurant + cuisine synchronization deleting stale links + new restaurant insert + negative-cost record quarantined to `quarantine_batch_*.jsonl` and `etl_quarantine_records`).
