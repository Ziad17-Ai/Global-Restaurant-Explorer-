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

- **Deployed application URLs (Azure Container Apps — `polandcentral`):**
  - **Streamlit Web App:** `https://ca-eatosphere-streamlit.politeriver-19c81647.polandcentral.azurecontainerapps.io`
  - **FastAPI Backend & OpenAPI `/docs`:** `https://ca-eatosphere-backend.politeriver-19c81647.polandcentral.azurecontainerapps.io/docs`

## 8. Azure Production Deployment Guide (From Scratch)

This platform runs on **Microsoft Azure** within the **\$100 Azure for Students** credit using **Azure Container Apps (Consumption)**, **Azure Database for MySQL Flexible Server (`Standard_B1ms`)**, **Azure Blob Storage (`Standard_LRS`)**, **Azure Key Vault (RBAC)**, and **Azure Container Registry (`Basic`)**, with **GitHub Actions OIDC** building and pushing `linux/amd64` images to ACR.

### 8.1 Prerequisites & Region Selection

- [Azure CLI (`az`)](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) + `containerapp` extension (`az extension add --name containerapp --upgrade -y`)
- [GitHub CLI (`gh`)](https://cli.github.com/) (for setting OIDC secrets)
- Python 3.12+ virtual environment with `pymysql` (for one-time TLS schema initialization)
- Check your subscription's allowed regions (`az policy assignment list`) — on Azure for Students, **`polandcentral`** supports all required services (`Standard_B1ms` MySQL, Container Apps Workload Profiles, ACR, Key Vault, Storage).

### 8.2 Step 1 — Provision Layer 1 Foundation (`polandcentral`)

```powershell
$RG = "rg-eatosphere-prod"
$LOC = "polandcentral"
$ACR = "acreatosphere2611"
$ST = "steatosphere2611"
$KV = "kv-eatosphere-2611"
$ID = "id-eatosphere-prod"

az group create --name $RG --location $LOC
az acr create --name $ACR --resource-group $RG --sku Basic --admin-enabled false --location $LOC
az storage account create --name $ST --resource-group $RG --location $LOC --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false
$ST_KEY = az storage account keys list --resource-group $RG --account-name $ST --query "[0].value" -o tsv
az storage container create --name bronze --account-name $ST --account-key $ST_KEY

az keyvault create --name $KV --resource-group $RG --location $LOC --enable-rbac-authorization true
$USER_ID = az ad signed-in-user show --query id -o tsv
$KV_ID = az keyvault show --name $KV --resource-group $RG --query id -o tsv
az role assignment create --assignee $USER_ID --role "Key Vault Secrets Officer" --scope $KV_ID

$ID_PRINCIPAL = az identity create --name $ID --resource-group $RG --location $LOC --query principalId -o tsv
$ACR_ID = az acr show --name $ACR --resource-group $RG --query id -o tsv
az role assignment create --assignee-object-id $ID_PRINCIPAL --assignee-principal-type ServicePrincipal --role AcrPull --scope $ACR_ID
az role assignment create --assignee-object-id $ID_PRINCIPAL --assignee-principal-type ServicePrincipal --role AcrPush --scope $ACR_ID
az role assignment create --assignee-object-id $ID_PRINCIPAL --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope $KV_ID
```

Populate the 7 secrets in Key Vault (never commit or echo secret values):
`mysql-admin-password`, `mysql-pipeline-password`, `mysql-app-password`, `azure-storage-connection-string`, `kaggle-username`, `kaggle-key`, and `hf-api-key`.

### 8.3 Step 2 — Build & Push Container Images via GitHub Actions OIDC

1. Add federated identity credentials on `id-eatosphere-prod` for your GitHub repository (`main` and feature branches), matching GitHub's OIDC subject format (`repo:<owner>@<owner_id>/<repo>@<repo_id>:ref:refs/heads/<branch>`).
2. Set GitHub Actions repository secrets (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`).
3. Push to trigger [`.github/workflows/build-push-acr.yml`](.github/workflows/build-push-acr.yml), which builds and pushes `backend`, `streamlit`, and `pipeline` (`linux/amd64`, tagged `:<sha>` and `:latest`) to `acreatosphere2611.azurecr.io`.

### 8.4 Step 3 — Provision & Initialize Azure Database for MySQL Flexible Server

1. Create `mysql-eatosphere-2611` (`Standard_B1ms`, `20 GB`, MySQL `8.0.21`, `--public-access 0.0.0.0` for Azure services) and temporarily allow your deployer IP (`AllowDeployerIP`).
2. Connect over verified TLS (`ssl.create_default_context()`):
   - As `eatoadmin`, execute [`sql/001_create_tables.sql`](sql/001_create_tables.sql), then create least-privilege `explorer_pipeline`@`%` (write + DDL/views) and `explorer_app`@`%` (`SELECT` only).
   - As `explorer_pipeline`, execute [`sql/002_create_gold_views.sql`](sql/002_create_gold_views.sql) (uses `SQL SECURITY INVOKER` so no `SUPER` privilege is required).
3. Delete `AllowDeployerIP` once initialization is complete.

### 8.5 Step 4 — Container Apps Environment (`WorkloadProfiles`) & Scheduled ETL Job

> **Important:** Create the Container Apps Environment with `--environment-mode WorkloadProfiles` so Scheduled Jobs and Key Vault secret references are supported (the CLI's Express mode blocks both).

```powershell
az containerapp env create --name cae-eatosphere-prod --resource-group $RG --location $LOC --environment-mode WorkloadProfiles
```

Deploy `job-eatosphere-etl` (`pipeline:latest`, `--trigger-type Schedule --cron-expression "0 3 * * 0"` for `@weekly`, `0.5` vCPU / `1.0Gi` RAM, `APP_ENV=production`, `STORAGE_BACKEND=azure`, `MYSQL_TLS_ENABLED=TRUE`, Key Vault refs for `mysql-pipeline-password`, `azure-storage-connection-string`, `kaggle-username`, `kaggle-key`), then trigger the initial seed:

```powershell
az containerapp job start --name job-eatosphere-etl --resource-group $RG
```

### 8.6 Step 5 — Deploy FastAPI Backend & Streamlit Frontend

1. Deploy `ca-eatosphere-backend` (`backend:latest`, external ingress port `8000`, `0.5` vCPU / `1.0Gi` RAM, `minReplicas=0`, `maxReplicas=2`, `APP_ENV=production`, `MYSQL_TLS_ENABLED=TRUE`, `BACKEND_ALLOW_CSV_FALLBACK_IN_LOCAL=false`, Key Vault refs `mysql-app-password` and `hf-api-key`).
2. Deploy `ca-eatosphere-streamlit` (`streamlit:latest`, external ingress port `8501`, `0.5` vCPU / `1.0Gi` RAM, `minReplicas=0`, `maxReplicas=1`, **zero** DB credentials or Key Vault secrets, only `STREAMLIT_BACKEND_URL=https://<backend-fqdn>` and `STREAMLIT_API_TIMEOUT_SECONDS=30`).
3. Update `BACKEND_CORS_ORIGINS=https://<streamlit-fqdn>` on `ca-eatosphere-backend`.

### 8.7 Estimated Monthly Cost & Teardown

| Azure Service | Tier / Sizing | Est. Monthly Cost |
| --- | --- | --- |
| Azure Database for MySQL Flexible Server | Burstable `Standard_B1ms`, 20 GB | `~$0–$13` (Student free tier / Burstable) |
| Azure Container Registry | `Basic` | `~$5` |
| Azure Container Apps (`backend`, `streamlit`, `job-eatosphere-etl`) | Consumption (`minReplicas=0`, `@weekly` job) | `~$0–$3` (within 180k vCPU-s free grant) |
| Azure Storage Account + Key Vault | `Standard_LRS` (`bronze`) + Standard RBAC | `< $0.20` |
| **Total** | | **~\$5–\$21/month** (well within \$100 credit) |

To tear down all cloud resources when finished:

```powershell
az group delete --name rg-eatosphere-prod --yes --no-wait
```

## 9. Repository structure (target)

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

## 10. Team

| Name | Role |
| ------ | ------ |
| Ziad Ahmed El Shamy | TBD |
| Ali Ahmed Ali Kassem | TBD |
| Yehia Nader Ali | TBD |
| Abdulrahman Salem | TBD |
| Ahmed Hany | TBD |
| Ziad Salah ElKady | TBD |

## 11. Data licensing and attribution

This project uses third-party open data. Each source has its own license and attribution rules (`docs/DATA_SOURCES.md`). Verify the terms from each provider before redistributing any data. Source names and licenses are surfaced in the UI (`docs/UI_UX.md`), and required notices will be compiled in `docs/ATTRIBUTION.md`.

## 12. License

TBD.
