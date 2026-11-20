"""
Dual-dialect database manager supporting:
- MySQL 8.0+ (production: SQLAlchemy + PyMySQL with connection pooling & transactions)
- SQLite 3 (isolated local/CI testing without requiring a running mysqld daemon)

Enforces strict non-destructive safety rules and schema preflight verification.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pipeline.etl.config import ETLConfig

REQUIRED_CORE_TABLES = [
    "stg_zomato_cleaned",
    "countries",
    "cities",
    "locations",
    "rating_tiers",
    "restaurants",
    "cuisines",
    "restaurant_cuisines",
]


class DatabaseConnection:
    """Thin uniform query/transaction wrapper over either SQLAlchemy(MySQL) or SQLite."""

    def __init__(self, dialect: str, raw_conn: Any) -> None:
        self.dialect = dialect
        self._conn = raw_conn

    def _adapt_sql(self, sql: str) -> str:
        if self.dialect == "sqlite":
            return sql.replace("%s", "?")
        return sql

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        adapted = self._adapt_sql(sql)
        if self.dialect == "sqlite":
            return self._conn.execute(adapted, params or ())
        from sqlalchemy import text  # type: ignore
        if params:
            # Convert positional %s params to named :p0, :p1 for SQLAlchemy text()
            named_sql = adapted
            bind_params = {}
            for idx, val in enumerate(params):
                named_sql = named_sql.replace("%s", f":p{idx}", 1)
                bind_params[f"p{idx}"] = val
            return self._conn.execute(text(named_sql), bind_params)
        return self._conn.execute(text(adapted))

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        row_list = list(rows)
        if not row_list:
            return 0
        adapted = self._adapt_sql(sql)
        if self.dialect == "sqlite":
            cur = self._conn.executemany(adapted, row_list)
            return cur.rowcount
        # Use underlying DBAPI cursor for high-speed batch execution in MySQL
        dbapi_conn = self._conn.connection
        cur = dbapi_conn.cursor()
        try:
            cur.executemany(adapted, row_list)
            return cur.rowcount
        finally:
            cur.close()

    def fetchall(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple[Any, ...]]:
        res = self.execute(sql, params)
        return [tuple(r) for r in res.fetchall()]

    def fetchone(self, sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Tuple[Any, ...]]:
        res = self.execute(sql, params)
        row = res.fetchone()
        return tuple(row) if row is not None else None


class DatabaseManager:
    """Manages connections, transactions, schema preflight checks, and additive migrations."""

    def __init__(self, config: ETLConfig) -> None:
        self.config = config
        self.dialect = config.db_dialect
        self._engine = None

        if self.dialect == "mysql":
            self._init_mysql_engine()
        elif self.dialect == "sqlite":
            self.config.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            raise ValueError(f"Unsupported DB_DIALECT: '{self.dialect}' (expected 'mysql' or 'sqlite')")

    def _init_mysql_engine(self) -> None:
        try:
            from sqlalchemy import create_engine  # type: ignore
            import pymysql  # noqa: F401  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "MySQL dialect requires SQLAlchemy and PyMySQL. "
                "Install dependencies via `pip install -r requirements.txt`."
            ) from exc

        from urllib.parse import quote_plus

        user = quote_plus(self.config.db_user)
        password = quote_plus(self.config.db_password)
        url = (
            f"mysql+pymysql://{user}:{password}@{self.config.db_host}:"
            f"{self.config.db_port}/{self.config.db_name}?charset=utf8mb4"
        )
        self._engine = create_engine(
            url,
            pool_size=self.config.db_pool_size,
            pool_pre_ping=True,
            connect_args={"connect_timeout": self.config.db_connect_timeout},
            future=True,
        )

    @contextmanager
    def transaction(self):
        if self.dialect == "sqlite":
            conn = sqlite3.connect(str(self.config.sqlite_db_path))
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.create_function("SHA256", 1, lambda s: hashlib.sha256(str(s).encode("utf-8")).hexdigest())
            try:
                yield DatabaseConnection("sqlite", conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            with self._engine.begin() as sa_conn:
                yield DatabaseConnection("mysql", sa_conn)

    def test_connection(self) -> bool:
        with self.transaction() as conn:
            row = conn.fetchone("SELECT 1")
            return row == (1,)

    def list_tables(self) -> List[str]:
        with self.transaction() as conn:
            if self.dialect == "sqlite":
                rows = conn.fetchall("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
            else:
                rows = conn.fetchall(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                    (self.config.db_name,),
                )
            return sorted(r[0] for r in rows)

    def preflight_verify_core_schema(self) -> List[str]:
        """Verify all 8 existing core tables exist; returns list of any missing tables."""
        existing = set(self.list_tables())
        return [t for t in REQUIRED_CORE_TABLES if t not in existing]

    def apply_etl_metadata_migration(self) -> None:
        """Apply additive Migration 001 safely without touching existing core tables."""
        if self.dialect == "mysql":
            migration_file = self.config.project_root / "sql" / "migrations" / "001_create_etl_metadata.sql"
            sql_script = migration_file.read_text(encoding="utf-8")
            with self.transaction() as conn:
                for stmt in _split_sql_statements(sql_script):
                    conn.execute(stmt)
        else:
            with self.transaction() as conn:
                for stmt in _sqlite_metadata_ddl():
                    conn.execute(stmt)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()


def _split_sql_statements(sql_script: str) -> List[str]:
    stmts = []
    buf = []
    for line in sql_script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmts.append("\n".join(buf).rstrip(";").strip())
            buf = []
    if buf:
        rem = "\n".join(buf).strip()
        if rem:
            stmts.append(rem)
    return stmts


def _sqlite_metadata_ddl() -> List[str]:
    return [
        """CREATE TABLE IF NOT EXISTS etl_schema_migrations (
            migration_version TEXT PRIMARY KEY,
            migration_name    TEXT NOT NULL,
            applied_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS etl_ingestion_batches (
            batch_id              TEXT PRIMARY KEY,
            source_name           TEXT NOT NULL,
            source_file_name      TEXT NOT NULL,
            source_file_path      TEXT NOT NULL,
            source_file_hash      TEXT NOT NULL,
            source_file_size      INTEGER NOT NULL,
            source_row_count      INTEGER NOT NULL DEFAULT 0,
            accepted_row_count    INTEGER NOT NULL DEFAULT 0,
            rejected_row_count    INTEGER NOT NULL DEFAULT 0,
            ingestion_started_at  TEXT NOT NULL,
            ingestion_finished_at TEXT NULL,
            ingestion_status      TEXT NOT NULL CHECK (ingestion_status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL_SUCCESS', 'SKIPPED')),
            storage_backend       TEXT NOT NULL DEFAULT 'local',
            bronze_uri            TEXT NULL,
            error_message         TEXT NULL,
            created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS etl_pipeline_runs (
            run_id            TEXT PRIMARY KEY,
            batch_id          TEXT NOT NULL REFERENCES etl_ingestion_batches(batch_id) ON DELETE CASCADE,
            stage             TEXT NOT NULL CHECK (stage IN ('EXTRACT', 'BRONZE', 'VALIDATE', 'TRANSFORM', 'SILVER_LOAD', 'GOLD_REFRESH', 'FULL_PIPELINE')),
            started_at        TEXT NOT NULL,
            finished_at       TEXT NULL,
            extracted_count   INTEGER NOT NULL DEFAULT 0,
            transformed_count INTEGER NOT NULL DEFAULT 0,
            accepted_count    INTEGER NOT NULL DEFAULT 0,
            rejected_count    INTEGER NOT NULL DEFAULT 0,
            inserted_count    INTEGER NOT NULL DEFAULT 0,
            updated_count     INTEGER NOT NULL DEFAULT 0,
            unchanged_count   INTEGER NOT NULL DEFAULT 0,
            dq_issue_count    INTEGER NOT NULL DEFAULT 0,
            status            TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL_SUCCESS', 'SKIPPED')),
            error_message     TEXT NULL,
            created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS etl_data_quality_issues (
            issue_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id          TEXT NOT NULL REFERENCES etl_ingestion_batches(batch_id) ON DELETE CASCADE,
            restaurant_id     INTEGER NULL,
            source_row_number INTEGER NOT NULL,
            column_name       TEXT NOT NULL,
            issue_type        TEXT NOT NULL,
            severity          TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
            original_value    TEXT NULL,
            issue_description TEXT NOT NULL,
            detected_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS etl_quarantine_records (
            quarantine_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id          TEXT NOT NULL REFERENCES etl_ingestion_batches(batch_id) ON DELETE CASCADE,
            source_row_number INTEGER NOT NULL,
            restaurant_id     INTEGER NULL,
            raw_record        TEXT NOT NULL,
            rejection_reason  TEXT NOT NULL,
            quarantine_status TEXT NOT NULL DEFAULT 'OPEN' CHECK (quarantine_status IN ('OPEN', 'REVIEWED', 'RESOLVED', 'DISCARDED')),
            created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "INSERT OR IGNORE INTO etl_schema_migrations (migration_version, migration_name) VALUES ('001', 'create_etl_metadata')",
    ]
