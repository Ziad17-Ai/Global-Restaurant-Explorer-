"""Shared constants, bounds, and UI microcopy for the Streamlit application."""

from __future__ import annotations

APP_NAME = "EatoSphere"
APP_SUBTITLE = "Global Restaurant Intelligence & Auditable Culinary Briefing"

GOLD_MAX_AGE_DAYS = 7
QUERY_LOG_MAX_CHARS = 220
MAX_NLP_INPUT_CHARS = 500
MAX_QUARANTINE_RATE_PCT = 15.0

DEFAULT_API_TIMEOUT_SECONDS = 10
DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
PAGE_LIMIT_OPTIONS: tuple[int, ...] = (10, 20, 50, 100)

DEFAULT_MAP_POINTS_LIMIT = 500
MAX_MAP_POINTS_LIMIT = 1000
MAP_POINTS_MIN_LIMIT = 50
MAP_POINTS_STEP = 50

MIN_RATING = 0.0
MAX_RATING = 5.0
RATING_STEP = 0.5
RATING_TIER_HIGH = 4.0
RATING_TIER_MID = 3.0

MAX_COST_USD_LIMIT = 1000.0
COST_USD_STEP = 5.0

DEFAULT_RADIUS_M = 5000
MIN_RADIUS_M = 500
MAX_RADIUS_M = 50000
RADIUS_STEP_M = 500
METERS_PER_KM = 1000.0

PRICE_TIER_LABELS: dict[int, str] = {
    1: "Tier 1 · Budget",
    2: "Tier 2 · Moderate",
    3: "Tier 3 · Upscale",
    4: "Tier 4 · Fine Dining",
}
PRICE_RANGE_OPTIONS: tuple[int, ...] = (1, 2, 3, 4)

SORT_LABELS: dict[str, str] = {
    "rating": "Highest rated",
    "votes": "Most voted",
    "cost_usd_asc": "Lowest cost (USD)",
    "cost_usd_desc": "Highest cost (USD)",
    "name": "Alphabetical (A–Z)",
}

MAX_COMPARE_ITEMS = 4
MAX_JOURNEY_STOPS = 8
MIN_JOURNEY_STOPS = 2
EARTH_RADIUS_KM = 6371.0
WALKING_SPEED_KMH = 4.5
DRIVING_SPEED_KMH = 25.0
MINUTES_PER_HOUR = 60.0

MAX_ABS_LATITUDE = 90.0
MAX_ABS_LONGITUDE = 180.0

UNRATED_LABEL = "Unrated"
UNRATED_DETAIL_LABEL = "No rating in source"
UNKNOWN_SOURCE_LABEL = "Dataset source"
UNKNOWN_LICENSE_LABEL = "License unspecified"

BASEMAP_LIGHT = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
BASEMAP_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
CHART_HEIGHT_PX = 360
MAP_HEIGHT_PX = 480
DEFAULT_MAP_CENTER_LAT = 26.0
DEFAULT_MAP_CENTER_LON = 30.0
DEFAULT_MAP_ZOOM = 2
CITY_MAP_ZOOM = 11
DETAIL_MAP_ZOOM = 13

# Light theme (*Warm Paper*) spatial colors aligned with docs/UI_UX.md §3.3
COLOR_HIGH_RATING: list[int] = [30, 77, 59, 225]
COLOR_MID_RATING: list[int] = [166, 61, 47, 225]
COLOR_LOW_RATING: list[int] = [180, 83, 9, 225]
COLOR_UNRATED: list[int] = [100, 116, 139, 195]
COLOR_FOCUS: list[int] = [166, 61, 47, 245]
COLOR_ROUTE_PATH: list[int] = [166, 61, 47, 210]
COLOR_STROKE_LIGHT: list[int] = [250, 249, 245, 235]

# Dark theme (*Warm Ink*) spatial colors aligned with docs/UI_UX.md §3.3
COLOR_DARK_HIGH_RATING: list[int] = [82, 168, 138, 235]
COLOR_DARK_MID_RATING: list[int] = [224, 122, 107, 235]
COLOR_DARK_LOW_RATING: list[int] = [229, 161, 75, 235]
COLOR_DARK_UNRATED: list[int] = [168, 162, 158, 210]
COLOR_DARK_FOCUS: list[int] = [196, 77, 61, 245]
COLOR_DARK_ROUTE_PATH: list[int] = [224, 122, 107, 220]
COLOR_STROKE_DARK: list[int] = [23, 22, 20, 235]

MARKER_RADIUS_PX = 7
FOCUS_MARKER_RADIUS_PX = 10

HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_UNPROCESSABLE = 422
HTTP_STATUS_RATE_LIMITED = 429
HTTP_STATUS_SERVICE_UNAVAILABLE = 503
HTTP_STATUS_SERVER_ERROR_MIN = 500

NL_EXAMPLE_QUERIES: tuple[str, ...] = (
    "Top rated Italian in Cairo under $30",
    "Best Japanese in Dubai with table booking",
    "Affordable North Indian in New Delhi with online delivery",
    "Fine dining in London rated above 4.5",
)

PIPELINE_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "success": (":material/check_circle:", "Success"),
    "skipped_unchanged": (":material/fast_forward:", "Skipped (unchanged)"),
    "quality_gate_failed": (":material/gpp_bad:", "Quality gate failed"),
    "failed": (":material/error:", "Failed"),
}
