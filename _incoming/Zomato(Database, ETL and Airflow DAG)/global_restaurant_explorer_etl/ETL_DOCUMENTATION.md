# Global Restaurant Explorer Platform — ETL Pipeline Documentation

**Project:** Global Restaurant Explorer Platform ([GitHub Repository](https://github.com/nhahub/NHA-5-083))  
**Target Database:** `zomato_restaurant_explorer` (MySQL 8.0+ / InnoDB / `utf8mb4`)  
**Source Dataset:** `zomato_cleaned.csv` (9,550 rows, 21 columns)  
**Architecture:** Medallion Pattern (`Bronze -> Silver -> Gold`) integrated non-destructively with the existing relational schema

## 1. ETL Overview & Medallion Architecture

The pipeline ingests restaurant CSV datasets into immutable Bronze storage, validates and transforms records with Pandas in the Silver layer, loads the existing 8-table MySQL 8.0 schema idempotently inside atomic transactions, and refreshes 7 Gold analytical views alongside the existing `v_restaurant_explorer` view.

| Layer | Implementation | Key Objects |
| :--- | :--- | :--- |
| **Bronze** | Immutable raw CSV snapshots + SHA-256 checksums + `metadata.json` | `data/bronze/zomato/YYYY/MM/DD/batch_<UUID>/`, `etl_ingestion_batches` |
| **Silver** | Pandas cleaning, validation, quarantine, and dependency-aware idempotent loading | `stg_zomato_cleaned`, `countries`, `cities`, `locations`, `rating_tiers`, `restaurants`, `cuisines`, `restaurant_cuisines`, `etl_data_quality_issues`, `etl_quarantine_records` |
| **Gold** | Application-facing & analytical MySQL 8.0 views (`CREATE OR REPLACE VIEW`) | `v_restaurant_explorer` (preserved), `gold_restaurant_search`, `gold_city_restaurant_stats`, `gold_country_restaurant_stats`, `gold_cuisine_stats`, `gold_price_range_stats`, `gold_rating_distribution`, `gold_geographic_coverage` |

## 2. Database Safety & Existing Schema Integration

- **Zero Destructive Operations:** The ETL never executes `DROP DATABASE`, `TRUNCATE`, or `zomato_restaurant_explorer.sql`.
- **Preflight Verification:** Before loading, `DatabaseManager.preflight_verify_core_schema()` confirms all 8 core tables exist.
- **Additive Migrations:** `sql/migrations/001_create_etl_metadata.sql` and `002_create_gold_views.sql` use `CREATE TABLE IF NOT EXISTS` and `CREATE OR REPLACE VIEW`, tracked in `etl_schema_migrations`.
- **Generated Column Safety:** `load_silver.py` never inserts into or updates `locations.location_hash` on MySQL (`STORED GENERATED` column), matching locations deterministically via SHA-256 fingerprint (`IFNULL(..., 'NULL')`).

## 3. Bronze Storage Structure (Local & Azure)

Local Bronze snapshots are stored immutably under:

```text
data/bronze/zomato/YYYY/MM/DD/batch_<UUID>/
├── zomato_cleaned.csv
└── metadata.json
```

`LocalBronzeStorage` raises `FileExistsError` if a batch directory already exists and never mutates the original source file. Switching `STORAGE_BACKEND=azure` activates `pipeline/storage/azure_blob_storage.py` (`AzureBlobBronzeStorage`), which uses `azure-storage-blob` (`BlobServiceClient`) with environment-based credentials (`AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT_URL` + `DefaultAzureCredential`).

## 4. Silver Cleaning, Validation & Quarantine Rules

- **Schema Verification (`extract.py`):** Reads all 21 columns as strings (`keep_default_na=False`) and rejects missing or unexpected columns before transformation.
- **Missing Values:** Paired missing `Longitude`/`Latitude` (`497` rows) are logged as `WARNING` (`MISSING_COORDINATES`) and preserved as SQL `NULL`. Missing `Cuisines` (`9` rows) are logged as `INFO` (`MISSING_CUISINES`) and preserved with 0 rows in `restaurant_cuisines`. Half-missing coordinate pairs are quarantined as `ERROR`.
- **Boolean Standardization:** `'Yes'` -> `1`, `'No'` -> `0` for `has_table_booking`, `has_online_delivery`, `is_delivering_now`, and `switch_to_order_menu`; staging retains `'Yes'`/`'No'`. Any other value is quarantined.
- **Numeric & Domain Checks:** Enforces positive `Restaurant ID` and `Country Code`, `Longitude` in `[-180, 180]`, `Latitude` in `[-90, 90]`, `Price range` in `1..4`, `Aggregate rating` in `0.0..5.0` (preserving `0.0` as `Not rated`), non-negative `Average Cost for two` and `Votes`, and verified `rating_color <-> rating_text` pairs.
- **Cuisine Splitting:** Splits comma-separated cuisines, trims whitespace, preserves non-ASCII characters, drops empties, and deduplicates intra-row duplicates (logged as `INFO`).
- **Quarantine:** Invalid rows are written both to `data/quarantine/quarantine_batch_<UUID>.jsonl` and `etl_quarantine_records` (full JSON payload + rejection reason).

## 5. Idempotency & Incremental Processing

- **Source Checksum Tracking:** `etl_ingestion_batches` records `source_file_hash` (SHA-256). Re-running an identical file detects the prior successful batch, skips duplicating the Bronze copy (unless `--force` is passed), reconciles Silver without creating duplicates, and reports `inserted=0, updated=0, unchanged=9550`.
- **Incremental Updates & Cuisine Sync:** Matching by `restaurant_id`, new restaurants are inserted, modified restaurants are updated in place, and `restaurant_cuisines` removes stale associations and inserts new associations within the same transaction. Absent restaurants are never deleted by default.

## 6. Installation, Migration & Execution Commands

### Setup (Local MySQL 8.0)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Fill in DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
```

### Apply Additive Migrations (Optional Manual Step — Also Applied Automatically by ETL)

```bash
mysql -u <user> -p zomato_restaurant_explorer < sql/migrations/001_create_etl_metadata.sql
mysql -u <user> -p zomato_restaurant_explorer < sql/migrations/002_create_gold_views.sql
```

### CLI Execution Modes

```bash
# Full Bronze -> Silver -> Gold pipeline
python -m pipeline.etl run --source data/zomato_cleaned.csv --mode full

# Bronze ingestion only
python -m pipeline.etl run --source data/zomato_cleaned.csv --mode bronze

# Silver validation, transformation & database load only
python -m pipeline.etl run --source data/zomato_cleaned.csv --mode silver

# Refresh Gold analytical views from current Silver tables
python -m pipeline.etl run --mode gold

# Validation / Dry-run (zero database writes)
python -m pipeline.etl run --source data/zomato_cleaned.csv --mode validate
python -m pipeline.etl run --source data/zomato_cleaned.csv --mode full --dry-run

# Force reprocessing of an already-ingested checksum
python -m pipeline.etl run --source data/zomato_cleaned.csv --mode full --force
```

### Automated Test Suite

```bash
python -m unittest discover -s tests -v
# Or with pytest installed:
pytest -v
```

## 7. Airflow & Azure Integration Readiness

- **Apache Airflow:** `pipeline/etl/runner.py` and individual stage functions (`extract_csv`, `ingest_to_bronze`, `validate_dataframe`, `transform_to_silver`, `load_silver_layer`, `build_gold_views`) are stateless, accept explicit `batch_id` and `ETLConfig`, return JSON-serializable status dictionaries, and are safe to retry via Airflow TaskFlow or `PythonOperator`.
- **Microsoft Azure:** Changing `.env` switches Bronze storage to `AzureBlobBronzeStorage` (`STORAGE_BACKEND=azure`) and points SQLAlchemy to **Azure Database for MySQL – Flexible Server** (`DB_HOST`, `DB_USER`, `DB_PASSWORD`), with credentials injectable from Azure Key Vault at runtime.
