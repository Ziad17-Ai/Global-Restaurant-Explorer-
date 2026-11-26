# EatoSphere Platform

> **Status:** Draft v0.4, a living document. We work iteratively (Agile), so items marked **TBD** are pending timeboxed spikes or post-refactoring updates. See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) for how decisions are made.
> **Last updated:** 2026-11-24
> **Repository:** <https://github.com/nhahub/NHA-5-083>

> **Naming note:** the final name is TBD. "Global" overstates our initial data coverage (see section 4), and the name should not duplicate existing public projects (see [`docs/LITERATURE_REVIEW.md`](docs/LITERATURE_REVIEW.md)).

## 1. What is this?

A data engineering platform that programmatically ingests restaurant data on per-source schedules, cleans, standardizes, and validates it through Bronze, Silver, and Gold Medallion layers (with a 15% quarantine safety gate and incremental upserts), stores it in MySQL 8.0 on Microsoft Azure, and serves it through a FastAPI backend and an Editorial-themed Streamlit web app.

The data pipeline is the core of the project. The web app is the layer users interact with.

## 2. Where to find each academy deliverable

| Academy requirement | File(s) |
| --------------------- | --------- |
| **Project Planning and Management** (objectives, incremental delivery, scope, methodology, roles, sprints, risks) | [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) |
| **Literature Review** (related work, data sources review, technical background, positioning, references) | [`docs/LITERATURE_REVIEW.md`](docs/LITERATURE_REVIEW.md) |
| **Requirements Gathering** (stakeholders, user stories, use cases, functional and non-functional requirements) | [`docs/SRS.md`](docs/SRS.md) |
| **System Analysis and Design** | |
| - Problem statement and objectives | [`docs/SRS.md`](docs/SRS.md), section 1 |
| - Use case diagram and descriptions | [`docs/SRS.md`](docs/SRS.md), section 4 |
| - Software architecture, capacity targets, component diagram, tech stack | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), sections 1, 2, 4, 13 |
| - ERD, logical and physical schema, enrichment rules | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), section 9 |
| - DFD, sequence, activity, schedule table, state, class diagrams | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), sections 3, 6–8, 10 |
| - Data sources, dynamic fetching, and per-source schedules | [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) |
| - Data quality rule catalogue and 15% safety gate | [`docs/DATA_QUALITY_RULES.md`](docs/DATA_QUALITY_RULES.md) |
| - Canonical cuisine vocabulary (130 cuisines in 15 groups) | [`docs/CUISINE_VOCABULARY.md`](docs/CUISINE_VOCABULARY.md) |
| - Secrets and non-secret configuration (`config/settings.toml`) | [`docs/SECRETS.md`](docs/SECRETS.md), [`.env.example`](.env.example) |
| - Deployment diagram, observability, API outline | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), sections 11, 12, 15 |
| - UI/UX design system and responsive/accessibility guidelines | [`docs/UI_UX.md`](docs/UI_UX.md) |
| **Implementation: source code** | `pipeline/`, `web/backend/`, `web/streamlit/`, `sql/`, `config/` |
| Coding standards and naming conventions | [`docs/CODE_STYLE.md`](docs/CODE_STYLE.md) |
| AI agent and contributor navigation guide | [`AGENTS.md`](AGENTS.md) |
| Version control, branching, collaboration | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Testing and validation plan | [`docs/CODE_STYLE.md`](docs/CODE_STYLE.md) section 9 (`docs/TESTING.md` deferred until post-refactoring) |
| Deployment and execution instructions | This file, section 7 (Docker Compose full stack + local Python runbook) |

## 3. Features

| # | Feature | Summary |
|---|---------|---------|
| 1 | Multi-criteria search and filtering | Country, city, locality, canonical cuisine, cost for two (original currency + batch-pinned USD), price tier, minimum rating |
| 2 | Interactive map | Restaurants as markers (`st.map` / `st.pydeck_chart`, or approved map component), details on selection, paired with a tabular view |
| 3 | NLP search | Free text (and stateless multi-turn follow-ups) is turned into validated `SearchParams` via a two-tier Hugging Face pipeline (`all-MiniLM-L6-v2` ONNX semantic hybrid always-on + optional `InferenceClient` LLM with 5s timeout and off-topic/location guardrails), then run as parameterized SQL |

Out of scope for now: owner accounts, B2B matching, in-app reviews, coordinate/locality imputation (see [`docs/SRS.md`](docs/SRS.md), section 9).

## 4. Data sources and incremental delivery

To deliver a clean working software increment first, **Increment 1** focuses end-to-end on the Zomato dataset (fetched programmatically via the Kaggle API on a `@weekly` change-checked schedule), while establishing the multi-source schema (`source_metadata`, `source_id`, `match_group_id`) for **Increment 2**.

| Source | Role | Cadence | Status |
| -------- | ------ | --------- | -------- |
| Zomato restaurant dataset (Kaggle API) | Baseline dataset (Increment 1) | `@weekly` (loads only on version/checksum change) | Decided ([`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)) |
| Additional restaurant source (Overture Maps Places, Foursquare OS Places, or OpenStreetMap) | Extra coverage, including Egypt (Increment 2) | Per-source (`@monthly` / extract-based) | **TBD** (Spike S1) |
| Geographic data (boundaries, localities) | District and locality context (Increment 2) | Manual / on provider update | **TBD** (Spike S1) |

Coverage note: the Zomato dataset (~9,551 rows) is concentrated in India and does not include Egypt; coverage is disclosed transparently in the UI (`docs/UI_UX.md`). Source terms are tracked in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) and `docs/ATTRIBUTION.md` (planned when Source 2 lands).

## 5. Architecture at a glance

```dsconfig
Sources (Kaggle API, etc.)
  -> Check version & checksum (skip if unchanged)
  -> Bronze (append-only raw files in Azure Blob / local fallback)
  -> Clean, standardize (canonical cuisines, pinned FX USD), validate
  -> 15% quarantine safety gate -> Silver (incremental MySQL upserts) + data_quality_issues
  -> SQL transformations -> Gold (search tables, views, POINT SRID 4326 spatial index)
  -> FastAPI backend (/api/*, /api/health, /api/pipeline/status)
  -> Streamlit web app (filters, map, NLP search via web/streamlit/api_client.py)
```

Apache Airflow orchestrates per-source scheduled runs using Docker-injected `AIRFLOW_CONN_*` environment connections. Secrets arrive strictly via OS environment variables (`.env` locally, Azure Key Vault references in production), while non-secret tunables live in `config/settings.toml` (`docs/SECRETS.md`). Streamlit holds no database credentials.

Details and diagrams: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 6. Tech stack

| Layer | Technology | Priority |
| ------- | ------------ | ---------- |
| Pipeline | Python 3.12+, Pandas, PyMySQL, SQL | Must |
| Database | MySQL 8.0 on Azure Database for MySQL Flexible Server | Must |
| Raw storage | Azure Blob Storage (local fallback in dev/CI) | Must |
| Orchestration | Apache Airflow 3.x (local Docker first; Azure Linux VM Should) | Must (DAG), Should (VM) |
| Backend | FastAPI | Must |
| Web presentation | Streamlit 1.67.x (Chrome, Edge, Firefox; PC & ~375 px mobile) | Must |
| NLP | Hugging Face `all-MiniLM-L6-v2` ONNX semantic hybrid (always-on, \$0) + `InferenceClient` LLM tier (5s timeout), off-topic guardrails, and multi-turn follow-up refinement | Must |
| Secrets & config | `.env` / GitHub Secrets / Azure Key Vault + `config/settings.toml` + `constants.py` | Must (env/TOML), Should (Key Vault) |
| Hosting | Azure App Service (FastAPI and Streamlit co-deployed) | Must |
| Monitoring and networking | JSON structured logs, `/api/health`, Azure Monitor / VNet | Must (logs/health), Could (Monitor/VNet) |

## 7. Getting started

### Option A: Docker Compose (Full Stack)

Run MySQL 8.0, FastAPI (with pre-baked Hugging Face ONNX NLP weights), Streamlit 1.67.x, and Apache Airflow 3.x together:

1. **Configure `.env`:** Copy [`.env.example`](.env.example) to `.env` and fill in `MYSQL_ROOT_PASSWORD`, `MYSQL_APP_USER` / `MYSQL_APP_PASSWORD`, `MYSQL_PIPELINE_USER` / `MYSQL_PIPELINE_PASSWORD`, `AIRFLOW_PG_PASSWORD`, `AIRFLOW_FERNET_KEY`, `AIRFLOW_JWT_SECRET`, and `KAGGLE_*` / `HF_API_KEY`.
2. **Build and start all services:**

   ```bash
   docker compose up --build -d
   ```

3. **Run the Medallion ETL pipeline into containerized MySQL:**

   ```bash
   docker compose --profile tools run --rm pipeline --source-csv data/zomato.csv --force
   ```

4. **Open the services:**
   - **Streamlit Web App:** `http://127.0.0.1:8501`
   - **FastAPI OpenAPI Docs:** `http://127.0.0.1:8000/docs` (`http://127.0.0.1:8000/api/health`)
   - **Apache Airflow 3.x UI:** `http://127.0.0.1:8080`
5. **Stop (or reset volumes):**

   ```bash
   docker compose down        # keep MySQL & Airflow volumes
   docker compose down -v     # wipe volumes for a clean re-init
   ```

### Option B: Local Python Development

The local Python workflow below runs end-to-end without Docker (including a local CSV fallback in the backend when MySQL is offline in `APP_ENV=local`).

- **Prerequisites:** Python 3.12+ (3.13 recommended), optional MySQL 8.0
- **1. Clone & install:**

  ```bash
  git clone https://github.com/nhahub/NHA-5-083.git
  cd NHA-5-083
  python -m venv .venv
  # Windows PowerShell: .\.venv\Scripts\python.exe -m pip install -r pipeline/requirements.txt -r web/backend/requirements.txt -r web/streamlit/requirements.txt
  # Linux/macOS:        ./.venv/bin/python -m pip install -r pipeline/requirements.txt -r web/backend/requirements.txt -r web/streamlit/requirements.txt
  ```

- **2. Configuration:** Copy [`.env.example`](.env.example) to `.env` (keep `APP_ENV=local` for local dev). Never commit `.env`. Non-secret runtime settings live in [`config/settings.toml`](config/settings.toml) and [`config/cuisine_map.csv`](config/cuisine_map.csv). Streamlit holds no database credentials and reads only `STREAMLIT_BACKEND_URL`.
- **3. Database setup (MySQL 8.0, optional locally in `APP_ENV=local`):** Execute the numbered scripts in [`sql/`](sql/001_create_tables.sql) in order:
  1. [`sql/000_reset.sql`](sql/000_reset.sql) (dev/demo reset only)
  2. [`sql/001_create_tables.sql`](sql/001_create_tables.sql)
  3. [`sql/002_create_gold_views.sql`](sql/002_create_gold_views.sql)
- **4. Run the ETL pipeline (validation dry-run or full MySQL run):**

  ```bash
  .\.venv\Scripts\python.exe -m pipeline.runner --source-csv data/zomato.csv --dry-run
  ```

- **5. Start the FastAPI backend & inspect OpenAPI `/docs`:**

  ```bash
  .\.venv\Scripts\python.exe -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000
  ```

  Interactive API docs: `http://127.0.0.1:8000/docs` · Liveness probe: `http://127.0.0.1:8000/api/health`
- **6. Start the Streamlit web app:**

  ```bash
  .\.venv\Scripts\python.exe -m streamlit run web/streamlit/app.py
  ```

- **7. Verify lint, types, and tests:**

  ```bash
  .\.venv\Scripts\python.exe -m ruff check pipeline web tests
  .\.venv\Scripts\python.exe -m ruff format --check pipeline web tests
  .\.venv\Scripts\python.exe -m mypy .
  .\.venv\Scripts\python.exe -m pytest -v
  ```

- **Deployed application URL:** TBD

## 8. Repository structure (target)

```dsconfig
/
├── README.md
├── AGENTS.md
├── CONTRIBUTING.md
├── pyproject.toml
├── .env.example
├── config/
│   ├── settings.toml          (committed non-secret runtime settings)
│   └── cuisine_map.csv        (canonical cuisine mapping table)
├── docs/
│   ├── PROJECT_PLAN.md
│   ├── LITERATURE_REVIEW.md
│   ├── SRS.md
│   ├── ARCHITECTURE.md
│   ├── DATA_SOURCES.md
│   ├── DATA_QUALITY_RULES.md
│   ├── CUISINE_VOCABULARY.md
│   ├── SECRETS.md
│   ├── UI_UX.md
│   └── CODE_STYLE.md
├── pipeline/
│   ├── dags/                  (Airflow DAG definitions — wiring only)
│   ├── ingestion/
│   ├── transform/
│   ├── quality/
│   ├── settings.py
│   └── constants.py
├── sql/                       (numbered schema and Gold view/index scripts)
├── web/
│   ├── backend/               (FastAPI: routers/, services/, repositories/, schemas/, settings.py, constants.py)
│   └── streamlit/             (Streamlit: app.py, api_client.py, settings.py, constants.py, pages/, components/, .streamlit/)
└── tests/                     (pytest suite, including test_architecture.py and test_streamlit_smoke.py)
```

## 9. Team

| Name | Role |
| ------ | ------ |
| Ziad Ahmed El Shamy | TBD |
| Ali Ahmed Ali Kassem | TBD |
| Yehia Nader Ali | TBD |
| Abdulrahman Salem | TBD |
| Ahmed Hany | TBD |
| Ziad Salah ElKady | TBD |

## 10. Data licensing and attribution

This project uses third-party open data. Each source has its own license and attribution rules (`docs/DATA_SOURCES.md`). Verify the terms from each provider before redistributing any data. Source names and licenses are surfaced in the UI (`docs/UI_UX.md`), and required notices will be compiled in `docs/ATTRIBUTION.md`.

## 11. License

TBD.
