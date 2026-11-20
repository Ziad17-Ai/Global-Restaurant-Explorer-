"""Environment-driven configuration for the Global Restaurant Explorer ETL pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class ETLConfig:
    db_dialect: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_pool_size: int
    db_connect_timeout: int
    sqlite_db_path: Path
    storage_backend: str
    bronze_local_path: Path
    quarantine_path: Path
    reports_path: Path
    logs_path: Path
    azure_connection_string: Optional[str]
    azure_account_url: Optional[str]
    azure_container: str
    project_root: Path

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None, project_root: Optional[Path] = None) -> "ETLConfig":
        root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        if env_file and Path(env_file).exists():
            load_dotenv(env_file, override=False)
        else:
            default_env = root / ".env"
            if default_env.exists():
                load_dotenv(default_env, override=False)

        def _resolve_path(env_key: str, default_rel: str) -> Path:
            raw = os.getenv(env_key, default_rel)
            p = Path(raw)
            return p if p.is_absolute() else (root / p)

        return cls(
            db_dialect=os.getenv("DB_DIALECT", "mysql").strip().lower(),
            db_host=os.getenv("DB_HOST", "localhost").strip(),
            db_port=int(os.getenv("DB_PORT", "3306")),
            db_name=os.getenv("DB_NAME", "zomato_restaurant_explorer").strip(),
            db_user=os.getenv("DB_USER", "root").strip(),
            db_password=os.getenv("DB_PASSWORD", ""),
            db_pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            db_connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "15")),
            sqlite_db_path=_resolve_path("SQLITE_DB_PATH", "data/zomato_test.sqlite"),
            storage_backend=os.getenv("STORAGE_BACKEND", "local").strip().lower(),
            bronze_local_path=_resolve_path("BRONZE_LOCAL_PATH", "data/bronze"),
            quarantine_path=_resolve_path("QUARANTINE_PATH", "data/quarantine"),
            reports_path=_resolve_path("REPORTS_PATH", "data/reports"),
            logs_path=_resolve_path("LOGS_PATH", "logs"),
            azure_connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING") or None,
            azure_account_url=os.getenv("AZURE_STORAGE_ACCOUNT_URL") or None,
            azure_container=os.getenv("AZURE_STORAGE_CONTAINER", "bronze-zomato").strip(),
            project_root=root,
        )

    def safe_summary(self) -> dict:
        """Return a log-safe configuration summary with secrets redacted."""
        return {
            "db_dialect": self.db_dialect,
            "db_host": self.db_host if self.db_dialect == "mysql" else None,
            "db_port": self.db_port if self.db_dialect == "mysql" else None,
            "db_name": self.db_name if self.db_dialect == "mysql" else str(self.sqlite_db_path),
            "db_user": self.db_user if self.db_dialect == "mysql" else None,
            "storage_backend": self.storage_backend,
            "bronze_local_path": str(self.bronze_local_path),
            "quarantine_path": str(self.quarantine_path),
            "reports_path": str(self.reports_path),
            "azure_configured": bool(self.azure_connection_string or self.azure_account_url),
        }
