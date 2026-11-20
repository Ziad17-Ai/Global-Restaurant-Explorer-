# Global Restaurant Explorer Platform — Team Setup & Run Guide

This repository contains the end-to-end **Global Restaurant Explorer Platform**:

- **`zomato_restaurant_explorer.sql`** — MySQL 8.0 schema and baseline database dump (`zomato_restaurant_explorer`).
- **`global_restaurant_explorer_etl/`** — Python/Pandas Bronze → Silver → Gold ETL pipeline, data quality validation, quarantine handling, reporting, and unit/E2E tests.
- **`global_restaurant_explorer_airflow/`** — Apache Airflow 3.4.0 Docker stack, DAG (`global_restaurant_explorer_etl`), adapter modules, and test suite.

> **Security Note:** Populated `.env` files are intentionally excluded from this folder. Each team member creates their own local `.env` files from `.env.example` in Step 3 below and should never commit or re-upload `.env` files.

---

## Prerequisites

Make sure you have the following installed and running before starting:

| Tool | Requirement | Notes |
| --- | --- | --- |
| **MySQL Server** | 8.0+ | Running locally on port `3306` (with MySQL Workbench or `mysql` CLI) |
| **Docker Desktop** | Latest (Compose v2) | Running, with at least **4 GB RAM** allocated |
| **Python** | 3.11+ | Optional — only needed to run standalone ETL tests outside Docker |
| **Ports** | `3306` (MySQL), `8080` (Airflow UI) | Make sure port `8080` is not in use by another app |

---

## Step 1: Download and Keep the Folders Side by Side

Download the entire shared folder to your machine and keep the three items in the **same parent directory**:

```text
Zomato project/
├── README.md
├── zomato_restaurant_explorer.sql
├── global_restaurant_explorer_etl/
│   ├── data/zomato_cleaned.csv
│   ├── pipeline/
│   ├── sql/
│   ├── tests/
│   └── .env.example
└── global_restaurant_explorer_airflow/
    ├── dags/
    ├── include/
    ├── tests/
    ├── docker-compose.yaml
    ├── Dockerfile
    └── .env.example
```

> Do not move `global_restaurant_explorer_airflow/` and `global_restaurant_explorer_etl/` apart — `docker-compose.yaml` mounts `../global_restaurant_explorer_etl` automatically.

---

## Step 2: Initialize the MySQL 8.0 Database

1. Start your local MySQL 8.0 service.
2. Open **MySQL Workbench** (or the `mysql` CLI) and execute `zomato_restaurant_explorer.sql`.
3. Confirm the `zomato_restaurant_explorer` schema was created.

---

## Step 3: Create Both Local `.env` Files

### 3A. ETL `.env` (`global_restaurant_explorer_etl/.env`)
Copy `global_restaurant_explorer_etl/.env.example` to `global_restaurant_explorer_etl/.env` and set your local MySQL credentials:

```env
DB_HOST=localhost
DB_PORT=3306
DB_NAME=zomato_restaurant_explorer
DB_USER=root
DB_PASSWORD=your_local_mysql_password
STORAGE_BACKEND=local
```

### 3B. Airflow `.env` (`global_restaurant_explorer_airflow/.env`)
Copy `global_restaurant_explorer_airflow/.env.example` to `global_restaurant_explorer_airflow/.env` and fill in:

- `AIRFLOW_PG_PASSWORD` — password for Airflow's internal Postgres metadata DB.
- `AIRFLOW_ADMIN_USER` and `AIRFLOW_ADMIN_PASSWORD` — your Airflow web UI login.
- `AIRFLOW_FERNET_KEY` — 32-byte URL-safe base64 key.
- `AIRFLOW_JWT_SECRET` — random 64-character hex secret.

You can generate a valid Fernet key and JWT secret in one command:

```cmd
python -c "import secrets, base64; print('AIRFLOW_FERNET_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()); print('AIRFLOW_JWT_SECRET=' + secrets.token_hex(32))"
```

---

## Step 4: Build and Start Apache Airflow (Docker)

Open a terminal and `cd` into **`global_restaurant_explorer_airflow`**:

```cmd
cd "path\to\Zomato project\global_restaurant_explorer_airflow"
docker compose build
docker compose up -d
```

Wait 30–60 seconds for `airflow-init` to complete, then check container status:

```cmd
docker compose ps
```

Open the Airflow UI at **`http://localhost:8080`** and sign in with the `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` you set in Step 3B.

---

## Step 5: Register the Airflow → MySQL Connection

Inside Docker, `localhost` refers to the container itself — always use **`host.docker.internal`** to reach your local MySQL 8.0 server.

### Option A: Via CLI (from `global_restaurant_explorer_airflow`)
Replace `YOUR_MYSQL_USER` and `YOUR_MYSQL_PASSWORD` with your actual MySQL credentials (do **not** include `<` or `>` brackets):

```cmd
docker compose exec airflow-scheduler airflow connections add mysql_zomato_explorer --conn-type mysql --conn-host host.docker.internal --conn-port 3306 --conn-schema zomato_restaurant_explorer --conn-login YOUR_MYSQL_USER --conn-password "YOUR_MYSQL_PASSWORD"
```

### Option B: Via Airflow Web UI
1. Go to `http://localhost:8080` → **Admin → Connections** → **+ Add Connection**.
2. Fill in:
   - **Connection Id:** `mysql_zomato_explorer`
   - **Connection Type:** `MySQL`
   - **Host:** `host.docker.internal`
   - **Schema:** `zomato_restaurant_explorer`
   - **Port:** `3306`
   - **Login:** your MySQL username (e.g., `root`)
   - **Password:** your MySQL password
3. Click **Save**.

---

## Step 6: Verify Everything End to End

Run these four checks **one at a time** from `global_restaurant_explorer_airflow`:

### 1. Confirm zero DAG import errors
```cmd
docker compose exec airflow-dag-processor airflow dags list-import-errors
```
**Expected output:** `No data found`

### 2. Run the Airflow test suite
```cmd
docker compose exec airflow-scheduler pytest /opt/airflow/tests -v
```
**Expected output:** `17 passed`

### 3. Run a safe dry-run (no database writes)
- **Windows `cmd.exe`:**
  ```cmd
  docker compose exec airflow-scheduler airflow dags test global_restaurant_explorer_etl --conf "{\"dry_run\": true}"
  ```
- **macOS / Linux / Git Bash:**
  ```bash
  docker compose exec airflow-scheduler airflow dags test global_restaurant_explorer_etl --conf '{"dry_run": true}'
  ```
**Expected output:** All 8 tasks succeed (`state=success`).

### 4. Run the full live MySQL 8.0 pipeline
```cmd
docker compose exec airflow-scheduler airflow dags test global_restaurant_explorer_etl
```
**Expected output:**
- All **8/8 tasks** finish with `state=success`:
  1. `validate_runtime_config` (`db_connected=True`)
  2. `validate_source_and_schema` (`schema_verified=True`)
  3. `bronze_ingestion` (`9,550` rows)
  4. `validate_and_quarantine` (`9,550` accepted, `0` rejected)
  5. `load_silver_layer` (`15` countries, `141` cities, `9,453` locations, `6` rating tiers, `9,550` restaurants, `145` cuisines, `19,703` restaurant-cuisine links)
  6. `refresh_gold_views` (`8/8` Gold views refreshed and queried)
  7. `run_data_quality_checks` (`checks_passed=True`, `9,550` restaurants reconciled)
  8. `generate_pipeline_summary` (JSON and Markdown reports written to `global_restaurant_explorer_etl/data/reports/`)

---

## Step 7 (Optional): Run Standalone ETL Tests Outside Docker

From `global_restaurant_explorer_etl`:

- **Windows (`cmd.exe`):**
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate
  pip install -r requirements.txt
  python -m unittest discover -s tests -v
  ```
- **macOS / Linux:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  python3 -m unittest discover -s tests -v
  ```

**Expected output:** `Ran 9 tests ... OK`

---

## Stopping and Restarting Airflow

From `global_restaurant_explorer_airflow`:

```cmd
docker compose down
docker compose up -d
```

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `no configuration file provided: not found` | Running `docker compose` from the wrong folder | `cd` into `global_restaurant_explorer_airflow` first |
| `Access denied for user '...'@'localhost'` | Wrong MySQL username/password (e.g., Airflow login used instead of MySQL `root`) | Delete and re-add `mysql_zomato_explorer` with your actual MySQL credentials |
| `Can't connect to MySQL server on 'localhost'` | Airflow connection used `localhost` instead of `host.docker.internal` | Update `mysql_zomato_explorer` Host to `host.docker.internal` |
| `The syntax of the command is incorrect` (Windows) | Literal `<` or `>` characters left in `cmd.exe` command | Remove `<` and `>` when replacing placeholders |
| JSON parse error on `--conf` (Windows `cmd.exe`) | Single quotes used around JSON in `cmd.exe` | Use escaped double quotes: `--conf "{\"dry_run\": true}"` |
| Port `8080` already in use | Another local service is bound to `8080` | Stop that service or change the host port mapping in `docker-compose.yaml` |
