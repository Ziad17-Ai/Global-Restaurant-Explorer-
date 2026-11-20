-- ============================================================================
-- ETL Post-Load Validation & Reconciliation Queries (MySQL 8.0+)
-- ============================================================================

-- 1. Core Silver & Staging Table Counts
SELECT 'stg_zomato_cleaned'  AS object_name, COUNT(*) AS row_count FROM stg_zomato_cleaned
UNION ALL SELECT 'countries',           COUNT(*) FROM countries
UNION ALL SELECT 'cities',              COUNT(*) FROM cities
UNION ALL SELECT 'locations',           COUNT(*) FROM locations
UNION ALL SELECT 'rating_tiers',        COUNT(*) FROM rating_tiers
UNION ALL SELECT 'restaurants',         COUNT(*) FROM restaurants
UNION ALL SELECT 'cuisines',            COUNT(*) FROM cuisines
UNION ALL SELECT 'restaurant_cuisines', COUNT(*) FROM restaurant_cuisines;

-- 2. Gold View Counts
SELECT 'v_restaurant_explorer'        AS gold_view, COUNT(*) AS row_count FROM v_restaurant_explorer
UNION ALL SELECT 'gold_restaurant_search',        COUNT(*) FROM gold_restaurant_search
UNION ALL SELECT 'gold_city_restaurant_stats',    COUNT(*) FROM gold_city_restaurant_stats
UNION ALL SELECT 'gold_country_restaurant_stats', COUNT(*) FROM gold_country_restaurant_stats
UNION ALL SELECT 'gold_cuisine_stats',            COUNT(*) FROM gold_cuisine_stats
UNION ALL SELECT 'gold_price_range_stats',        COUNT(*) FROM gold_price_range_stats
UNION ALL SELECT 'gold_rating_distribution',      COUNT(*) FROM gold_rating_distribution
UNION ALL SELECT 'gold_geographic_coverage',      COUNT(*) FROM gold_geographic_coverage;

-- 3. Latest ETL Ingestion Batches & Stage Runs
SELECT batch_id, source_file_name, source_row_count, accepted_row_count, rejected_row_count, ingestion_status, storage_backend, ingestion_started_at
FROM etl_ingestion_batches
ORDER BY ingestion_started_at DESC
LIMIT 10;

SELECT batch_id, stage, status, extracted_count, accepted_count, rejected_count, inserted_count, updated_count, unchanged_count, dq_issue_count
FROM etl_pipeline_runs
ORDER BY started_at DESC
LIMIT 20;

-- 4. Data Quality Summary by Severity & Issue Type
SELECT severity, issue_type, COUNT(*) AS issue_count
FROM etl_data_quality_issues
GROUP BY severity, issue_type
ORDER BY FIELD(severity, 'CRITICAL', 'ERROR', 'WARNING', 'INFO'), issue_count DESC;
