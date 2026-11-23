# Code Style Guide

> **Status:** Draft v0.12, a living document. No open items remain in section 12.
> **Last updated:** 2026-11-23

Keywords **MUST** and **SHOULD** follow their usual meaning. Every rule names how it is enforced: a tool (blocks the merge), or review (a human checks it).

## 1. Principles

1. **Readable over clever.** Someone else will read this code at 2 a.m. during an incident.
2. **Consistent.** Follow the rules here, even where you prefer another style.
3. **Automated.** Formatters and linters enforce style; reviews focus on logic.
4. **Safe by default.** Parameterized SQL, no secrets in code, validated inputs.
5. **Re-runnable.** Pipeline code must be idempotent.

## 2. General rules

- Language for code, comments, and commits: English.
- Files use UTF-8, LF line endings, a final newline, and no trailing whitespace (enforced by `.editorconfig`).
- Comments explain *why*, not *what*. Delete commented-out code.
- No magic numbers or strings: use named constants or config.
- TODO comments include an owner or issue: `# TODO(#42): handle currency conversion`.
- A `TBD` in code or docs has an entry in section 12 with an owner and a due date; a `TBD` without an entry is a defect.
- Keep functions short and single-purpose. If a function needs a long comment to explain it, split it.

### Repository layout

The folders that the rules and CI refer to. If the repository skeleton differs, update this list rather than the rules.

```text
web/backend/      FastAPI app: routers/, services/, repositories/, schemas/, settings.py
web/streamlit/    Streamlit app: app.py, api_client.py, pages/, components/, .streamlit/
pipeline/         ETL modules (no FastAPI, Streamlit, or Airflow imports)
pipeline/dags/    Airflow DAG files (wiring only)
sql/              Numbered SQL scripts
tests/            pytest tests, mirroring web/backend/, web/streamlit/, and pipeline/
docs/             Project documents (this guide, requirements, architecture)
```

### Data conventions

These apply to Python, SQL, the API, and the Streamlit app alike.

- **Time:** all timestamps are UTC. In Python, use timezone-aware values (`datetime.now(UTC)`). Columns are named `<event>_at` (`ingested_at`).
- **Coordinates:** latitude comes before longitude in variables, columns (`latitude`, `longitude`), and JSON. Silver stores them as `DECIMAL(9, 6)`; Gold map tables store one `POINT SRID 4326` column (section 4). GeoJSON uses `[lng, lat]` and Leaflet uses `[lat, lng]`; convert only at those boundaries, in one helper per language.
- **Money:** `Decimal` in Python and `DECIMAL(p, s)` in SQL, never floats. Silver keeps the original amount and its ISO 4217 code (`avg_cost_for_two`, `currency_code`) and never overwrites them. At fetch time, standardization also computes a US dollar amount (`avg_cost_for_two_usd`) and stores the rate and its date (`fx_rate`, `fx_rate_date`). The rate comes from one source and is pinned per batch, so a re-run reproduces the same values. Filtering and sorting across countries use the USD column.
- **Unrated places:** stored with a `NULL` rating, never `0`. Sources that encode "unrated" as `0` are converted during standardization.
- **Provenance:** every Silver row keeps its source and batch keys (`source_id`, `batch_id`) and the source's own record key (`source_restaurant_id`).

## 3. Python (pipeline, FastAPI, and Streamlit)

**Tools:** Ruff (lint and format), mypy (types), pytest (tests). Configuration lives in `pyproject.toml` at the repository root.

| Topic | Rule | Enforced by |
| ------- | ------ | ------------- |
| Style | PEP 8; line length 88 | `ruff format --check`, Ruff `E`, `W` |
| Version | Python 3.12 or newer | CI |
| Types | Type hints on all function signatures; `mypy` passes | mypy, Ruff `ANN` |
| Docstrings | Google style for public modules, functions, and classes (purpose, args, returns, raises) | Ruff `D` |
| Imports | Standard library, third party, local; no wildcard imports | Ruff `I`, `F` |
| Logging | `logging` with module-level loggers; no `print`; include `run_id` and `batch_id` in pipeline logs; never log secrets; log user query text only truncated | Ruff `T20`, review |
| Errors | Raise specific exceptions; never a bare `except:`; log with context, then re-raise or handle | Ruff `E722`, `B`, review |
| Config | Environment variables read through one settings module per app; never hardcode credentials | Ruff `S105`, `S106`, review |
| Paths | `pathlib.Path`, not string concatenation | Ruff `PTH` |
| Time | Timezone-aware datetimes only | Ruff `DTZ` |
| Complexity | Cyclomatic complexity of 18 or less; no magic numbers | Ruff `C90`, `PLR2004` |
| Pandas | Vectorized operations; no chained assignment; name DataFrames by content or layer (`raw_df`, `restaurants_df`, `silver_df`), never a bare `df`; pass `encoding` and `dtype` explicitly when reading files; never `to_sql(if_exists="replace")`, because it drops indexes and constraints | Ruff `PD`, review |
| Layering | Routers call services, services call repositories. SQL appears only in repositories, in `pipeline/` load modules, and in `sql/` scripts | review |
| Import boundaries | `pipeline/` (outside `pipeline/dags/`) never imports FastAPI, Streamlit, or Airflow. `web/backend/` never imports Streamlit or Airflow, and its routers and services never import `pymysql`. `web/streamlit/` never imports `pymysql`, `web/backend/`, or `pipeline/` | `tests/test_architecture.py` |
| FastAPI | Pydantic models for request and response schemas; routers per resource; one dependency that opens and closes the DB connection per request; routes that use PyMySQL are plain `def`, not `async def`, because PyMySQL blocks; proper status codes; see section 5 | review |
| Dependencies | Pinned. The API, the Streamlit app, and Airflow each have their own requirements file: Airflow constraint files commonly conflict with an application stack, and the apps deploy separately | review, CI |

**Example**

```python
"""Rating validation for the Silver layer."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

MIN_RATING = 0.0
MAX_RATING = 5.0
RULE_RATING_OUT_OF_RANGE = "rating_out_of_range"


def split_valid_ratings(
    restaurants_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split rows into valid rows and rejected rows with a rejection reason.

    Unrated restaurants (missing rating) are valid and keep a NULL rating.

    Args:
        restaurants_df: Restaurants with a numeric `rating` column.

    Returns:
        A tuple of (valid_df, rejected_df). `rejected_df` gains `rule_name`
        and `reason` columns for the quarantine table.
    """
    is_unrated = restaurants_df["rating"].isna()
    is_in_range = restaurants_df["rating"].between(MIN_RATING, MAX_RATING)
    is_valid = is_unrated | is_in_range

    valid_df = restaurants_df[is_valid]
    rejected_df = restaurants_df[~is_valid].assign(
        rule_name=RULE_RATING_OUT_OF_RANGE,
        reason=f"rating outside {MIN_RATING}-{MAX_RATING}",
    )
    logger.info("Rating check: %d valid, %d rejected", len(valid_df), len(rejected_df))
    return valid_df, rejected_df
```

### NLP adapter rules

- We use a third-party open model hosted through Hugging Face Inference Providers. The repository contains no model training, fine-tuning, or self-hosting code.
- The model ID and provider are configuration (environment variables), not constants in code. Which model was chosen, and its license, are recorded in the decision log (D-3), not in this guide.
- Changing the model or provider means re-running the sample-query suite (section 9) before merge.
- The prompt template lives in its own versioned file, not inline in code.
- The model fills a `SearchParams` Pydantic model with `extra="forbid"`; it never writes SQL, and its output is never executed.
- Adapters implement one `NLPAdapter` interface (`parse(query) -> SearchParams`), so the Hugging Face and rule-based implementations are swappable.
- Every provider call sets a timeout, a maximum output size, and temperature 0. Limits are named constants or config values.
- Input text has a maximum length, checked at the API boundary.
- Parsed values are checked against the known vocabulary (countries, cities, localities, cuisines); unknown values are dropped or flagged.
- On timeout, error, or invalid output, fall back to the rule-based parser.
- The parse cache has a size bound and a TTL.
- The endpoint is rate limited.

## 4. SQL (MySQL)

| Topic | Rule | Enforced by |
| ------- | ------ | ------------- |
| Engine and charset | InnoDB; `utf8mb4` with an explicit collation (`utf8mb4_0900_ai_ci`, the MySQL 8.0 default), set in the database-creation script | review |
| Keywords | UPPERCASE (`SELECT`, `JOIN`, `WHERE`) | review |
| Names | `snake_case`; tables plural (`restaurants`, `cities`); columns singular. ERD entities are singular, tables are plural | review |
| Keys | Primary key `<name>_id`, where `<name>` is a short singular name that is clear from context (`batch_id` for `ingestion_batches`); foreign keys use the same name as the referenced key. Not strictly enforced: a reviewer checks that it is understandable | review |
| Constraints | Foreign keys `fk_<table>_<column>` | review |
| Booleans | Columns start with `is_` or `has_` (`has_table_booking`) | review |
| Types | `DECIMAL(p, s)` with explicit precision for money (for example `DECIMAL(14, 2)`), ratings, and Silver coordinates (`DECIMAL(9, 6)`); `JSON` for raw payloads, not text | review |
| Silver tables | No prefix. Operational tables: `data_quality_issues` (quarantine), `ingestion_batches`, `pipeline_runs`, `source_metadata` | review |
| Gold objects | Prefix `gold_` for views and tables built for the app (a table, not a view, where a spatial index is needed) | review |
| Indexes | `idx_<table>_<columns>`; unique indexes `uq_<table>_<columns>`; declared inside the `CREATE TABLE` statement | review |
| Idempotent loads | Unique key on `(source_id, source_restaurant_id)`; load with `INSERT ... ON DUPLICATE KEY UPDATE` | review, test |
| Joins | Explicit `JOIN ... ON`; never implicit comma joins | review |
| Selecting | List columns explicitly; avoid `SELECT *` in application and Gold code | review |
| Layout | One clause per line, indented joins and conditions | review |
| Ordering | Every `ORDER BY` that feeds pagination ends with a unique tie-breaker | review |
| Driver | PyMySQL, with `charset='utf8mb4'` and TLS enabled. Values are always passed separately (`cursor.execute(sql, params)`) with named `%(name)s` placeholders. For DataFrames, build them from `cursor.fetchall()`; `to_sql` and `read_sql` expect SQLAlchemy, which we do not use. PyMySQL has no pool; one connection per request is acceptable at this scale. Never share one connection across requests or sessions (for example through `st.cache_resource`): PyMySQL connections are not thread-safe and go stale | review |
| Safety | Application code uses parameterized queries only; never build SQL by string formatting | review, Ruff `S608` |
| Scripts | Numbered files in `sql/` (`001_create_tables.sql`, `002_create_gold_views.sql`). There are no migrations: the schema is rebuilt, not altered. To change it, edit the numbered script, recreate the database, and reload from Bronze (Silver and Gold are derived data). Table scripts use `CREATE TABLE IF NOT EXISTS`; Gold view scripts use `CREATE OR REPLACE VIEW`. `sql/000_reset.sql` drops everything and is for development and demo databases only. Revisit this rule if data that Bronze cannot rebuild, such as `pipeline_runs` history, must survive a schema change. MySQL has no `IF NOT EXISTS` for indexes, columns, or views. Keep `;` out of comments and strings so simple script runners can split statements | review |
| Spatial | Gold map tables hold `location POINT SRID 4326 NOT NULL` with a `SPATIAL INDEX`; rows without valid coordinates are not in them. Build every point the same way: `ST_SRID(POINT(longitude, latitude), 4326)`. `POINT(x, y)` takes longitude first, but WKT text with SRID 4326 is latitude first, and swapped coordinates raise no error. Radius search uses a bounding box on the index (`MBRContains`), then the exact `ST_Distance_Sphere` check (meters); the distance function alone does not use the index. Validate coordinate ranges before building a point | review, tests |

**Example** (named `%(name)s` placeholders are the PyMySQL style)

```sql
SELECT
    r.restaurant_id,
    r.name,
    r.rating,
    c.city_name
FROM restaurants AS r
JOIN locations AS l ON l.location_id = r.location_id
JOIN cities AS c ON c.city_id = l.city_id
WHERE c.city_name = %(city)s
  AND r.rating >= %(min_rating)s
ORDER BY r.rating DESC, r.restaurant_id ASC
LIMIT %(limit)s OFFSET %(offset)s;
```

**Spatial example**

```sql
-- Load a point. POINT takes longitude first, then latitude.
INSERT INTO gold_map_points (restaurant_id, name, location)
VALUES (
    %(restaurant_id)s,
    %(name)s,
    ST_SRID(POINT(%(longitude)s, %(latitude)s), 4326)
) AS new_row
ON DUPLICATE KEY UPDATE
    name = new_row.name,
    location = new_row.location;

-- Radius search. The bounding box (from the helper below) uses the spatial
-- index, and the distance check makes the result exact.
SELECT
    restaurant_id,
    name
FROM gold_map_points
WHERE MBRContains(ST_GeomFromText(%(bounding_box_wkt)s, 4326), location)
  AND ST_Distance_Sphere(
        location,
        ST_SRID(POINT(%(longitude)s, %(latitude)s), 4326)
      ) <= %(radius_m)s
ORDER BY restaurant_id ASC
LIMIT %(limit)s;
```

The bounding box comes from one helper, so the coordinate order is written once:

```python
"""Spatial helpers for radius search."""

import math

METERS_PER_DEGREE_LATITUDE = 111_320.0
MAX_SEARCH_RADIUS_M = 50_000.0
MAX_ABS_LATITUDE = 85.0
MAX_ABS_LONGITUDE = 180.0
BOX_MARGIN = 1.01


def bounding_box_wkt(latitude: float, longitude: float, radius_m: float) -> str:
    """Return a WKT rectangle that fully contains a search circle.

    The text is latitude first, as MySQL expects for SRID 4326. The rectangle
    is slightly larger than the circle, so the exact distance check must still
    run after it. The antimeridian is not handled.

    Args:
        latitude: Circle center latitude in degrees.
        longitude: Circle center longitude in degrees.
        radius_m: Circle radius in meters.

    Returns:
        A closed POLYGON in WKT.

    Raises:
        ValueError: If a value is outside the supported range.
    """
    if abs(latitude) > MAX_ABS_LATITUDE or abs(longitude) > MAX_ABS_LONGITUDE:
        raise ValueError("coordinates outside the supported range")
    if not 0 < radius_m <= MAX_SEARCH_RADIUS_M:
        raise ValueError("radius_m must be positive and within the maximum")

    delta_lat = BOX_MARGIN * radius_m / METERS_PER_DEGREE_LATITUDE
    delta_lon = delta_lat / math.cos(math.radians(latitude))
    south, north = latitude - delta_lat, latitude + delta_lat
    west, east = longitude - delta_lon, longitude + delta_lon
    corners = [
        (south, west),
        (south, east),
        (north, east),
        (north, west),
        (south, west),
    ]
    ring = ",".join(f"{lat} {lon}" for lat, lon in corners)
    return f"POLYGON(({ring}))"
```

## 5. API conventions

| Topic | Rule |
| ------- | ------ |
| Paths | Under `/api`; static segments lowercase `kebab-case` (`/api/data-quality-issues`); collections are plural nouns. No version prefix |
| Parameters | Path and query parameters are `snake_case` (`/api/restaurants/{restaurant_id}`, `min_rating`) |
| JSON | Keys and enum values are `snake_case` on request and response. No alias generators and no case conversion in the client |
| Pagination | Collections take `limit` and `offset`. The default and maximum `limit` are named constants. Responses use `items`, `total`, `limit`, `offset` |
| Errors | One error body schema (a Pydantic model) for every non-2xx response |
| Status codes | 201 on create, 404 when missing, 422 on validation errors, 429 when rate limited |
| OpenAPI | Every route sets `response_model`, `summary`, and `tags`; the generated schema is the API documentation |

## 6. Streamlit

**Requirement:** Streamlit MUST be used. It provides the user-facing screens, and every screen must work on both PC and phone screens with a flexible layout. Streamlit does not have to handle every feature: FastAPI remains the API and `pipeline/` remains the ETL. Any other UI technology, such as a separate frontend app, needs a team decision and its own section in this guide before anyone uses it.

**Pinned stack:** Streamlit 1.67.x (the current release at the time of writing) on Python 3.12 or newer. The exact version is recorded in `web/streamlit/requirements.txt`.

| Topic | Rule | Enforced by |
| ------- | ------ | ------------- |
| Structure | Entry point `web/streamlit/app.py`; pages in `web/streamlit/pages/`; reusable UI in `web/streamlit/components/`; navigation declared once in `app.py` with `st.navigation` and `st.Page`. Files and functions are `snake_case` | review |
| Responsive layout | Every screen works on a phone (about 375 px wide) and on a desktop. Use flexible containers: `st.columns` (keep `wrap=True`, so columns stack on narrow screens), `st.grid` with `min_column_width` for lists of cards, and `st.tabs` or `st.expander` for dense content. Use `width="stretch"` instead of fixed pixel widths; fixed values are for heights only (maps, charts). Keep `initial_sidebar_state="auto"`: the sidebar is hidden on small devices, so primary controls go in the page, not only in the sidebar. Check each screen at phone and desktop width before merge | review |
| Data access | Option A adopted (CS-15 closed): pages get data exclusively through `web/streamlit/api_client.py`, which calls the FastAPI API over HTTP with a timeout on every call. Streamlit code never embeds SQL, never imports `pymysql`, `sqlalchemy`, `web/backend/`, or `pipeline/`, and holds no database credentials. Only `api_client.py` imports an HTTP client | `tests/test_architecture.py` |
| Rerun model | Streamlit reruns the page script on every interaction. Keep top-level code cheap: network and heavy work go through cached functions. Put the widgets that feed one query in one `st.form` | review |
| State | `st.session_state` for session state; initialize keys explicitly at the top of the page and change them next to the widget that owns them | review |
| Caching | `st.cache_data` for API results, with an explicit `ttl`. `st.cache_resource` only for objects that are safe to share across sessions, such as an HTTP client; never a database connection | review |
| Layout | Streamlit layout primitives (`st.columns`, `st.container`, `st.tabs`, `st.sidebar`, `st.expander`); no custom HTML layout | `tests/test_architecture.py`, review |
| Raw HTML and components | No `unsafe_allow_html=True`, `st.html`, or `streamlit.components`. A reviewed exception is added to `RAW_HTML_ALLOWED` in the architecture test, with its justification in the pull request. Third-party components (for example `streamlit-folium` for a Leaflet map) need team approval and a pinned version; prefer built-ins such as `st.map` and `st.pydeck_chart` | `tests/test_architecture.py` |
| Untrusted text | Restaurant names and addresses come from open datasets, and user queries are user input. Show them with `st.text` or `st.dataframe`; if markdown formatting is needed, escape the value first. Never build HTML from them | review |
| Theme and config | Theme and server settings live in `.streamlit/config.toml` (Streamlit reads it from the directory where `streamlit run` starts), not in page code. `st.set_page_config` is called once, in `app.py` | review |
| Secrets | Environment variables through the settings module, as in section 3. No `st.secrets`; `.streamlit/secrets.toml` is git-ignored and unused | `tests/test_architecture.py`, secret scan |
| Server hardening | Leave XSRF protection and CORS at their defaults unless a pull request justifies a change. Keep the experimental `server.enableAgentApi` option off in `.streamlit/config.toml` and in every deployed app. For a local check by a coding agent, pass it on the command line together with `--server.address=127.0.0.1`, never in a config file | review |
| Accessibility | Every input has a label; do not rely on color alone; charts and maps come with a table or text equivalent | review |
| Strings | User-facing text is centralized when shared and English by default. Streamlit has limited right-to-left layout support, so Arabic stays a Could item and needs a spike first | review |
| Testing | Each page has a smoke test with `streamlit.testing.v1.AppTest`. Interaction tests stub `api_client` and never call the live API | `tests/test_streamlit_smoke.py` |

**Warning for AI-assisted coding.** Streamlit adds widgets and deprecates older patterns in most releases, so generated code often reflects an older version. Check it against the documentation for the pinned version; newer layout tools such as `st.grid` (added in 1.67) and `width="stretch"` (which replaces the older `use_container_width`) are often missing from generated code. Streamlit also publishes agent skills that update with the installed version. Install them with `streamlit skills` so an assistant writes for the version you run.

## 7. Airflow DAGs

- DAG files only wire tasks together; business logic lives in `pipeline/` modules that DAGs import.
- `dag_id` in `snake_case` with a purpose (`restaurants_daily_etl`); tasks named by verb (`ingest_zomato`, `validate_silver`).
- Every task is idempotent: running it twice gives the same result. Batch IDs are derived deterministically from source and logical date.
- Set explicit `retries`, `retry_delay` (with exponential backoff), `execution_timeout`, `max_active_runs`, `catchup=False` (unless backfills are intended), and tags.
- Pass paths and IDs between tasks, never DataFrames.
- The `pipeline_runs` summary is written by a task that runs even when upstream tasks fail (`trigger_rule="all_done"`).
- No secrets in DAG files; use Airflow connections or environment variables.
- No heavy work at DAG parse time (no network or database calls at module level).
- A CI test imports every DAG file and fails on import errors.
- The Airflow major version is pinned to 3.x.

## 8. Naming conventions summary

| Item | Convention | Example |
| ------ | ----------- | --------- |
| Python files and functions | `snake_case` | `clean_restaurants.py`, `load_silver()` |
| Python classes | `PascalCase` | `SearchService` |
| Python constants | `UPPER_SNAKE_CASE` | `MAX_RATING` |
| SQL tables and columns | `snake_case` | `restaurant_cuisines` |
| SQL constraints | `fk_`, `idx_`, `uq_` prefixes | `fk_restaurants_location_id` |
| SQL booleans | `is_` or `has_` prefix | `has_online_delivery` |
| Gold objects | `gold_` prefix | `gold_map_points` |
| API paths | lowercase `kebab-case` | `/api/data-quality-issues` |
| API parameters, JSON keys, enum values | `snake_case` | `min_rating` |
| Quality rule names | `snake_case` constants | `rating_out_of_range` |
| Blob containers | lowercase letters, digits, hyphens (Azure rule) | `bronze` |
| Blob paths | `<source>/<yyyy-mm-dd>/<batch_id>/<original_file>` | `zomato/2026-11-18/b0042/zomato.csv` |
| Streamlit pages and modules | `snake_case`, `.py` extension | `restaurant_search.py` |
| Streamlit functions | `snake_case` | `render_restaurant_card()` |
| Branches | `type/area-description`; types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`; areas: `backend`, `streamlit`, `pipeline`, `sql`, `docs` | `feat/streamlit-search-page` |
| Commits | Conventional Commits, with the same areas as scopes | `feat(backend): add nl search endpoint` |
| Env variables | `UPPER_SNAKE_CASE` | `MYSQL_HOST` |
| Airflow DAGs | `snake_case` | `restaurants_daily_etl` |

## 9. Testing conventions

- Python: pytest; files `test_<module>.py`; functions `test_<behavior>`; use small fixtures instead of real datasets.
- Every data-quality rule has tests with both valid and invalid examples.
- Test the NLP layer with the fixed sample-query set from spike S3 (queries and expected parameters, including failures); it doubles as the regression suite.
- Loads, upserts, and repository queries get integration tests against a real MySQL container (SHOULD), because idempotency cannot be proven with mocks.
- Every Streamlit page has an `AppTest` smoke test (`tests/test_streamlit_smoke.py`). Tests that interact with a page stub `web/streamlit/api_client.py`.
- `AppTest` does not check layout. Check each screen by hand at phone and desktop width before merge.
- Import boundaries and the raw-HTML rule are checked by `tests/test_architecture.py`. A failing boundary test is a design question, not something to silence.
- A bug fix includes a test that fails before the fix.
- Test files may relax some lint rules.

## 10. Security checklist

- [ ] No secrets, tokens, or `.env` in the repository; `.env.example` lists variable names only
- [ ] Secret scanning runs in pre-commit and CI
- [ ] All SQL parameterized
- [ ] Inputs validated at the API boundary, including a maximum length on NLP text
- [ ] Model output validated and never executed
- [ ] NLP endpoint rate limited
- [ ] The application connects with a least-privilege, read-only database user; pipeline and application use separate accounts
- [ ] The Streamlit app holds no database credentials and does not use `st.secrets`; `.streamlit/secrets.toml` is git-ignored
- [ ] Untrusted text (restaurant data, user queries) is never rendered as HTML
- [ ] Streamlit XSRF protection and CORS are at their defaults, and `server.enableAgentApi` is off in config and in deployment
- [ ] TLS required for MySQL connections
- [ ] CORS on the API limited to an explicit origin allowlist; HTTPS everywhere
- [ ] Dependencies pinned in `requirements.txt` or a Python lock file
- [ ] Python dependency audits run in CI (`pip-audit`) or through Dependabot

## 11. Git and CI

- `main` is protected: changes arrive by pull request with at least one review.
- Commit messages follow Conventional Commits. Branch names follow section 8.
- These checks MUST pass before merge (GitHub Actions):

| Check | Tool |
| ------- | ------ |
| Python lint and format | `ruff check`, `ruff format --check` (covers `web/`, `pipeline/`, and `tests/`) |
| Python types | `mypy` |
| Python tests | `pytest`, including `tests/test_architecture.py` and `tests/test_streamlit_smoke.py` |
| DAG import test | `pytest` (DAG import test) |
| Secret scan | secret-scanning tool (for example `gitleaks`) |

Dependency audits run on the same pipeline but do not block a merge until the team agrees on a severity threshold.

## 12. Open items

Decisions that block or shape rules in this guide. Needed before Sprint 2 work starts (22 Nov), because feature freeze is 28 Nov.

No open items at this time. All design and style decisions required for Sprint 2 are resolved (CS-15 closed with Option A).

## 13. Change log

| Date       | Change                                |
|------------|---------------------------------------|
| 2026-10-30 | v0.2 created as an adoptable template |
| 2026-11-18 | v0.3: added status header, enforcement columns, data conventions, API conventions, NLP adapter rules, Git and CI, reference configuration, and open items; fixed MySQL script rules (`IF NOT EXISTS` is not valid for views and indexes); corrected the Python example (unused import, bare `df`, unrated ratings, rejection reason); fixed typo and naming gaps |
| 2026-11-18 | v0.4: JavaScript (D-7 closed) with JSDoc for complex code and a reference ESLint config; third-party open model for NLP (S3 chooses the model) |
| 2026-11-18 | v0.6: PyMySQL as the driver; no migrations (schema rebuilt from Bronze); spatial storage and radius search with tested examples; USD price normalization with original amounts kept; relaxed primary-key naming; repository layout; complexity aligned to 18; model choice moved to the decision log; CODEOWNERS dropped |
| 2026-11-19 | v0.7: consolidated source layout under `web/backend/` and `web/frontend/`; moved frontend package and ESLint configuration into `web/frontend/`; removed frontend tests; added owned TBD-marker rules |
| 2026-11-20 | v0.8: Streamlit adopted as the primary and only approved web presentation framework; replaced React/MUI frontend rules with Streamlit conventions |
| 2026-11-20 | v0.9: removed obsolete Node, React, ESLint, and Prettier tooling and updated repository settings for Streamlit |
| 2026-11-22 | v0.10: Streamlit required but no longer exclusive (scope tracked as CS-14); Streamlit reads data through one API client (proposed, CS-15); import boundaries, raw-HTML, and `st.secrets` rules enforced by an architecture test; Streamlit smoke tests; Streamlit version pinned; layout and cross-references fixed; open items restored |
| 2026-11-23 | v0.11: removed the price-display rule (CS-11); Streamlit covers screens for PC and phone with a flexible layout (CS-14 closed), with a responsive-layout rule and a manual layout check; clarified CS-15; `server.enableAgentApi` allowed only as a local command-line flag; `streamlit skills` named |
| 2026-11-23 | v0.12: closed CS-15 (adopted Option A: Streamlit accesses data exclusively via FastAPI over HTTP through `web/streamlit/api_client.py`, holding no database credentials); updated open items and data access rules |
| 2026-11-23 | v0.12: closed CS-15 (adopted Option A: Streamlit accesses data exclusively via FastAPI over HTTP through `web/streamlit/api_client.py`, holding no database credentials); updated open items and data access rules |