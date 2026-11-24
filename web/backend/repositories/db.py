"""Per-request PyMySQL connection management and local fallback gating."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Protocol

import pymysql
from pymysql.cursors import DictCursor

from web.backend.exceptions import ServiceUnavailableError
from web.backend.settings import BackendSettings, settings

logger = logging.getLogger(__name__)


class DictCursorConnection(Protocol):
    """Protocol for a DB connection providing dictionary-row cursors."""

    def cursor(self) -> DictCursor:
        """Return a cursor yielding dict rows."""
        ...

    def close(self) -> None:
        """Close the database connection."""
        ...


def open_mysql_connection(app_settings: BackendSettings) -> DictCursorConnection:
    """Open a single short-lived PyMySQL connection with DictCursor."""
    ssl_params: dict[str, object] | None = (
        {"ssl_mode": "REQUIRED"} if app_settings.mysql_tls_enabled else None
    )
    conn: DictCursorConnection = pymysql.connect(
        host=app_settings.mysql_host,
        port=app_settings.mysql_port,
        user=app_settings.mysql_app_user,
        password=app_settings.mysql_app_password.get_secret_value(),
        database=app_settings.mysql_database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=app_settings.database_connect_timeout_seconds,
        read_timeout=app_settings.database_connect_timeout_seconds,
        write_timeout=app_settings.database_connect_timeout_seconds,
        autocommit=True,
        ssl=ssl_params,
    )
    return conn


def can_use_csv_fallback(app_settings: BackendSettings) -> bool:
    """Return True only in local environment when CSV fallback is explicitly enabled."""
    return (
        app_settings.app_env == "local"
        and app_settings.backend_allow_csv_fallback_in_local
    )


def get_db_connection() -> Generator[DictCursorConnection | None, None, None]:
    """Yield one PyMySQL connection per request, or None for local CSV fallback."""
    conn: DictCursorConnection | None = None
    try:
        conn = open_mysql_connection(settings)
    except (pymysql.MySQLError, OSError) as exc:
        if can_use_csv_fallback(settings):
            logger.warning(
                "MySQL unavailable in local mode; falling back to local CSV snapshot",
                extra={"details": type(exc).__name__},
            )
            yield None
            return
        logger.error(
            "MySQL connection failed in non-fallback environment",
            extra={"details": type(exc).__name__},
        )
        raise ServiceUnavailableError(
            "Database service is currently unavailable"
        ) from exc

    try:
        yield conn
    finally:
        if conn is not None:
            try:
                conn.close()
            except pymysql.MySQLError:
                logger.warning("Failed to close PyMySQL connection cleanly")
