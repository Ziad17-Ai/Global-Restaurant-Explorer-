-- ============================================================================
-- Migration 002: Gold Layer Analytical & Application-Facing Views
-- Target Database: zomato_restaurant_explorer (MySQL 8.0+)
-- Safety: Preserves existing v_restaurant_explorer and all 8 core tables.
--         Uses CREATE OR REPLACE VIEW for safe, idempotent re-execution.
-- ============================================================================

-- A. gold_restaurant_search
-- One row per restaurant with aggregated cuisines (preserves NULL cuisines and NULL coordinates).
CREATE OR REPLACE VIEW gold_restaurant_search AS
SELECT
    v.restaurant_id,
    v.restaurant_name,
    v.country_code,
    v.city_name AS city,
    v.address,
    v.locality,
    v.longitude,
    v.latitude,
    GROUP_CONCAT(DISTINCT c.cuisine_name ORDER BY c.cuisine_name SEPARATOR ', ') AS cuisines,
    COUNT(DISTINCT c.cuisine_id) AS cuisine_count,
    v.average_cost_for_two,
    v.currency,
    v.has_table_booking,
    v.has_online_delivery,
    v.is_delivering_now,
    v.price_range,
    v.aggregate_rating,
    v.rating_color,
    v.rating_text,
    v.votes
FROM v_restaurant_explorer v
LEFT JOIN restaurant_cuisines rc ON rc.restaurant_id = v.restaurant_id
LEFT JOIN cuisines c             ON c.cuisine_id     = rc.cuisine_id
GROUP BY
    v.restaurant_id,
    v.restaurant_name,
    v.country_code,
    v.city_name,
    v.address,
    v.locality,
    v.longitude,
    v.latitude,
    v.average_cost_for_two,
    v.currency,
    v.has_table_booking,
    v.has_online_delivery,
    v.is_delivering_now,
    v.price_range,
    v.aggregate_rating,
    v.rating_color,
    v.rating_text,
    v.votes;

-- B. gold_city_restaurant_stats
-- City-level KPIs including rated-only average rating, price-range breakdown, and geolocation counts.
CREATE OR REPLACE VIEW gold_city_restaurant_stats AS
SELECT
    v.country_code,
    v.city_id,
    v.city_name AS city,
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
GROUP BY v.country_code, v.city_id, v.city_name;

-- C. gold_country_restaurant_stats
-- Country-level aggregate statistics without inventing country names.
CREATE OR REPLACE VIEW gold_country_restaurant_stats AS
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
GROUP BY v.country_code;

-- D. gold_cuisine_stats
-- Cuisine popularity, rated-only average rating, cost, votes, and geographic reach.
CREATE OR REPLACE VIEW gold_cuisine_stats AS
SELECT
    c.cuisine_id,
    c.cuisine_name,
    COUNT(DISTINCT rc.restaurant_id) AS restaurant_count,
    ROUND(AVG(CASE WHEN r.aggregate_rating > 0 THEN r.aggregate_rating END), 2) AS avg_restaurant_rating,
    ROUND(AVG(r.average_cost_for_two), 2) AS avg_restaurant_cost,
    SUM(r.votes) AS total_votes,
    COUNT(DISTINCT l.city_id) AS distinct_cities
FROM cuisines c
JOIN restaurant_cuisines rc ON rc.cuisine_id    = c.cuisine_id
JOIN restaurants r          ON r.restaurant_id  = rc.restaurant_id
JOIN locations l            ON l.location_id    = r.location_id
GROUP BY c.cuisine_id, c.cuisine_name;

-- E. gold_price_range_stats
-- Restaurant volume, cost bounds, ratings, and service adoption grouped by price range.
CREATE OR REPLACE VIEW gold_price_range_stats AS
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
GROUP BY r.price_range;

-- F. gold_rating_distribution
-- Restaurant counts and votes grouped by exact rating value and rating tier.
CREATE OR REPLACE VIEW gold_rating_distribution AS
SELECT
    r.aggregate_rating,
    rt.rating_color,
    rt.rating_text,
    COUNT(r.restaurant_id) AS restaurant_count,
    SUM(r.votes) AS total_votes,
    ROUND(AVG(r.votes), 1) AS avg_votes
FROM restaurants r
JOIN rating_tiers rt ON rt.rating_tier_id = r.rating_tier_id
GROUP BY r.aggregate_rating, rt.rating_color, rt.rating_text;

-- G. gold_geographic_coverage
-- Coordinate completeness breakdown by country and city.
CREATE OR REPLACE VIEW gold_geographic_coverage AS
SELECT
    v.country_code,
    v.city_id,
    v.city_name AS city,
    COUNT(v.restaurant_id) AS total_restaurants,
    SUM(CASE WHEN v.longitude IS NOT NULL AND v.latitude IS NOT NULL THEN 1 ELSE 0 END) AS restaurants_with_coordinates,
    SUM(CASE WHEN v.longitude IS NULL     AND v.latitude IS NULL     THEN 1 ELSE 0 END) AS restaurants_without_coordinates,
    ROUND(
        100.0 * SUM(CASE WHEN v.longitude IS NOT NULL AND v.latitude IS NOT NULL THEN 1 ELSE 0 END)
        / NULLIF(COUNT(v.restaurant_id), 0),
        2
    ) AS coordinate_completeness_pct
FROM v_restaurant_explorer v
GROUP BY v.country_code, v.city_id, v.city_name;

INSERT IGNORE INTO etl_schema_migrations (migration_version, migration_name)
VALUES ('002', 'create_gold_views');
