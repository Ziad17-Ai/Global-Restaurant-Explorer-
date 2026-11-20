# Apache Airflow Setup & Deployment Guide — Global Restaurant Explorer ETL

This guide covers installing, configuring, verifying, and running the **Apache Airflow 3.4.0 (Python 3.11)** orchestration layer for [`global_restaurant_explorer_etl`](https://github.com/Ali-Kassem-AK/global_restaurant_explorer_etl).

---

## 1. Prerequisites & Supported OS / Runtime

- **Selected Airflow Runtime:** **Apache Airflow 3.4.0** on **Python 3.11** (matching the ETL project's verified Python 3.11 runtime and official [Airflow 3.4.0 constraints](https://raw.githubusercontent.com/apache/airflow/constraints-3.4.0/constraints-3.11.txt)).
- **Supported Operating Systems:**
  - **Linux (Ubuntu 22.04/24.04, Debian, RHEL):** Native Docker Engine + Docker Compose v2, or isolated Python 3.11 virtual environment.
  - **Windows 10/11:** **Docker Desktop with WSL2 backend** (Linux containers) or **WSL2 Ubuntu** (native Windows is **not** a supported Airflow runtime).
  - **macOS:** Docker Desktop with Linux containers.
- **Prerequisites:**
  - Existing checkout of `global_restaurant_explorer_etl/` (with `pipeline/`, `sql/`, and `data/zomato_cleaned.csv`).
  - Target MySQL 8.0+ instance initialized with `zomato_restaurant_explorer.sql` (do **not** re-run `zomato_restaurant_explorer.sql` against a populated database—it begins with `DROP DATABASE IF EXISTS`).
  - Docker & Docker Compose v2 (recommended), OR Python 3.11 + `pip`/`venv` on Linux/WSL2.

---

## 2. Installing & Starting the Airflow Environment

### Option A: Docker Compose (Recommended for Windows/WSL2, macOS & Linux)

1. Extract `global_restaurant_explorer_airflow_bundle.zip` next to your `global_restaurant_explorer_etl/` directory:
   ```bash
   unzip global_restaurant_explorer_airflow_bundle.zip
   cd global_restaurant_explorer_airflow
   ```
2. Create your local `.env` from `.env.example` (never commit `.env`):
   ```bash
   cp .env.example .env
   ```
3. On Linux/WSL2, set `AIRFLOW_UID`, generate a Fernet key and JWT secret, and verify `ETL_PROJECT_HOST_PATH` points to your `global_restaurant_explorer_etl` directory:
   ```bash
   echo "AIRFLOW_UID=$(id -u)" >> .env
   python3 -c "from cryptography.fernet import Fernet; print('AIRFLOW_FERNET_KEY=' + Fernet.generate_key().decode())"
   ```
4. Build the custom Airflow 3.4.0 image and initialize the Airflow metadata database:
   ```bash
   docker compose build
   docker compose up airflow-init
   ```
5. Start the Airflow services (`airflow-postgres`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`, `airflow-triggerer`):
   ```bash
   docker compose up -d
   ```
   The Airflow UI/API is bound strictly to `http://127.0.0.1:8080` (localhost only).

### Option B: Native Linux / WSL2 Virtual Environment (Without Docker)

Keep Airflow in its own virtual environment separate from the ETL project's `.venv`:
```bash
python3.11 -m venv ~/airflow_venv
source ~/airflow_venv/bin/activate
pip install --upgrade pip
pip install "apache-airflow==3.4.0" -r requirements-airflow.txt \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.4.0/constraints-3.11.txt"

export AIRFLOW_HOME=~/airflow
export ETL_PROJECT_ROOT=/path/to/global_restaurant_explorer_etl
export PYTHONPATH="${ETL_PROJECT_ROOT}:$(pwd)/include:${PYTHONPATH}"
mkdir -p "${AIRFLOW_HOME}/dags"
cp dags/global_restaurant_explorer_etl_dag.py "${AIRFLOW_HOME}/dags/"
airflow db migrate
```

---

## 3. Where to Place the DAG File

- **Docker Compose:** Already placed in `dags/global_restaurant_explorer_etl_dag.py` and mounted read-only to `/opt/airflow/dags`.
- **Native Linux/WSL2:** Copy `dags/global_restaurant_explorer_etl_dag.py` into `$AIRFLOW_HOME/dags/` and keep `include/airflow_etl_adapter.py` on `PYTHONPATH` (or in `$AIRFLOW_HOME/include/`).

---

## 4. How Airflow Accesses ETL Source Code, SQL Files & Data

- The bundle does **not** duplicate `.venv`, `.env`, `.pytest_cache`, old logs, or the 2.6 MB `zomato_restaurant_explorer.sql` dump.
- Instead, `docker-compose.yaml` mounts your existing `global_restaurant_explorer_etl` directory into `/opt/airflow/etl_project`, sets `ETL_PROJECT_ROOT=/opt/airflow/etl_project`, and adds `/opt/airflow/etl_project:/opt/airflow/include` to `PYTHONPATH`.
- All tasks resolve `data/zomato_cleaned.csv`, `sql/migrations/*.sql`, and `pipeline.etl.*` deterministically relative to `ETL_PROJECT_ROOT`.

---

## 5. Required Airflow Providers & Python Packages

Installed automatically by `Dockerfile` via `requirements-airflow.txt` using the official Airflow 3.4.0 / Python 3.11 constraints file:
- `apache-airflow==3.4.0` (base image `apache/airflow:3.4.0-python3.11`)
- `apache-airflow-providers-mysql`
- `pandas>=2.1.0,<3.0.0`, `SQLAlchemy>=2.0.0,<3.0.0`, `PyMySQL>=1.1.0,<2.0.0`, `python-dotenv>=1.0.0,<2.0.0`
- `azure-storage-blob>=12.19.0,<13.0.0`, `azure-identity>=1.15.0,<2.0.0`

---

## 6. Configuring the MySQL Airflow Connection

Create an Airflow Connection named `mysql_zomato_explorer` mapping directly to the variable names in the ETL project's `.env.example` (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`):

```bash
docker compose exec airflow-scheduler airflow connections add mysql_zomato_explorer \
  --conn-type mysql \
  --conn-host host.docker.internal \
  --conn-port 3306 \
  --conn-schema zomato_restaurant_explorer \
  --conn-login <DB_USER> \
  --conn-password <DB_PASSWORD>
```

*(On Linux hosts where MySQL runs on the host machine, use the host's LAN IP or Docker bridge gateway IP instead of `host.docker.internal`, or attach both containers to a shared Docker network.)*

---

## 7. Dataset Paths & Non-Secret Environment Variables

Configure these non-secret settings in `.env` (or pass them per run via DAG Trigger Params in the Airflow UI):
- `ETL_SOURCE_CSV`: Default `data/zomato_cleaned.csv` (resolved relative to `ETL_PROJECT_ROOT`).
- `AIRFLOW_ETL_SCHEDULE`: Blank by default (manual-only). Set to `@daily` or a cron expression when ready for scheduled runs.
- `STORAGE_BACKEND`: `local` (default) or `azure`.
- `BRONZE_LOCAL_PATH`, `QUARANTINE_PATH`, `REPORTS_PATH`, `LOGS_PATH`: Defaults match `.env.example`.

---

## 8. Starting Scheduler & API Server Services

- **Docker Compose:** `docker compose up -d` starts `airflow-apiserver` (port `127.0.0.1:8080`), `airflow-scheduler`, `airflow-dag-processor`, and `airflow-triggerer`.
- **Native Linux/WSL2:** Run `airflow api-server --port 8080`, `airflow scheduler`, `airflow dag-processor`, and `airflow triggerer` in separate terminals (or via `systemd` units).

---

## 9. Verifying DAG Discovery & Import Health

```bash
# Confirm zero DAG import errors
docker compose exec airflow-dag-processor airflow dags list-import-errors

# Confirm global_restaurant_explorer_etl is registered
docker compose exec airflow-scheduler airflow dags list | grep global_restaurant_explorer_etl

# Inspect task dependency graph
docker compose exec airflow-scheduler airflow tasks list global_restaurant_explorer_etl --tree
```

Open `http://127.0.0.1:8080` in your browser, locate `global_restaurant_explorer_etl`, and confirm all 8 tasks appear cleanly.

---

## 10. Triggering a Manual Run & Running CLI Tests

- **Dry-Run Validation (no DB or Bronze writes):**
  ```bash
  docker compose exec airflow-scheduler airflow dags trigger global_restaurant_explorer_etl \
    --conf '{"dry_run": true}'
  ```
- **Full End-to-End Manual Run:**
  ```bash
  docker compose exec airflow-scheduler airflow dags unpause global_restaurant_explorer_etl
  docker compose exec airflow-scheduler airflow dags trigger global_restaurant_explorer_etl
  ```
- **Local Single-Process CLI Execution Test:**
  ```bash
  docker compose exec airflow-scheduler airflow dags test global_restaurant_explorer_etl
  ```
- **Run Included Airflow Unit & DAG Tests:**
  ```bash
  docker compose exec airflow-scheduler pytest /opt/airflow/tests -v
  # Or using stdlib unittest:
  python3 -m unittest discover -s tests -v
  ```

---

## 11. Inspecting Task Logs & Troubleshooting

- **Airflow UI:** Click a DAG run → Grid/Graph view → select any task → **Logs** tab.
- **Container Logs:**
  ```bash
  docker compose logs -f airflow-scheduler airflow-dag-processor airflow-apiserver
  ```
- **Common Issues:**
  - *`Could not locate ETL project root`*: Verify `ETL_PROJECT_HOST_PATH` in `.env` points to the folder containing `pipeline/etl/`.
  - *`Core database schema incomplete`*: Initialize the MySQL database once using `zomato_restaurant_explorer.sql`.
  - *`countries.country_name` MySQL strict-mode error*: If loading a brand-new `country_code` not seeded in `zomato_restaurant_explorer.sql`, pre-seed `countries` or update `pipeline/etl/load_silver.py::_load_countries`.

---

## 12. Stopping Local Services Safely

```bash
# Stop containers while preserving Postgres metadata and logs volumes
docker compose down

# Stop AND remove local dev volumes (destructive to local Airflow metadata only)
docker compose down -v
```

---

## 13. Moving the Tested DAG to an Azure Linux VM Later

*(Note: Azure deployment has NOT been executed or tested here; these steps are for future deployment once local MySQL/Docker testing passes.)*

1. Provision an Ubuntu 22.04/24.04 Linux VM with Docker Engine and Docker Compose v2 (keep port `8080` closed in the NSG; access UI only via SSH tunnel `ssh -L 8080:127.0.0.1:8080 user@vm` or a TLS reverse proxy with authentication).
2. Clone `global_restaurant_explorer_etl` and unpack `global_restaurant_explorer_airflow_bundle.zip` onto the VM.
3. Configure a production PostgreSQL metadata database (or managed Azure Database for PostgreSQL) and strong `AIRFLOW_FERNET_KEY` / `AIRFLOW_JWT_SECRET` via VM secrets/Key Vault.
4. Point `mysql_zomato_explorer` Airflow Connection to your target MySQL instance (TLS enabled).
5. If switching Bronze storage to Azure Blob Storage, set `STORAGE_BACKEND=azure`, `AZURE_STORAGE_CONTAINER=bronze-zomato`, and configure either a VM Managed Identity (`AZURE_STORAGE_ACCOUNT_URL`) or a Key Vault-backed `AZURE_STORAGE_CONNECTION_STRING`.
6. Enable scheduling by setting `AIRFLOW_ETL_SCHEDULE=@daily` (or your preferred cron) and unpausing `global_restaurant_explorer_etl`.
