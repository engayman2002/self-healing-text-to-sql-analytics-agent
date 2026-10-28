"""Dynamic Connection Manager and Safe Read-Only SQL Execution Engine.

Features:
- Dynamic connection pool lifecycle per connection_id with LRU caching.
- Multi-dialect support: PostgreSQL, MySQL, SQLite, and MSSQL.
- Database-level read-only session configuration and statement timeouts.
- AST guardrail integration before execution.
- Precise latency measurement and driver error extraction for self-healing loops.
"""

from collections import OrderedDict
from datetime import datetime, timezone
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

from pydantic import BaseModel, Field
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

from app.core.config import get_settings
from app.core.security import decrypt_connection_uri, mask_connection_uri
from app.db.guardrails import (
    GuardrailError,
    SQLSecurityError,
    SQLSyntaxError,
    normalize_dialect,
    validate_and_sanitize_sql,
)
from app.db.introspector import serialize_cell

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Driver Compatibility & Cloud Pooler URI Normalizer
# ---------------------------------------------------------------------------

def normalize_database_uri(uri: str) -> str:
    """Normalize database URI for driver compatibility (psycopg v3, pg8000, pymysql) and cloud poolers (Neon)."""
    if not uri:
        return uri

    normalized = uri.strip()

    # 1. PostgreSQL driver normalization
    # Python 3.14 on Windows has native binary wheels for psycopg v3 (psycopg[binary] >= 3.2.0)
    if normalized.startswith("postgres://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgres://"):]
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql://"):]
    elif normalized.startswith("postgresql+psycopg2://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql+psycopg2://"):]

    # 2. MySQL driver normalization
    if normalized.startswith("mysql://"):
        normalized = "mysql+pymysql://" + normalized[len("mysql://"):]

    # 3. Cloud Postgres / Neon connection string sanitizer
    # Neon console URIs often append ?sslmode=require&channel_binding=require
    # Strip channel_binding=require as it causes SCRAM channel binding failures on certain platforms/drivers
    if "channel_binding=" in normalized:
        parsed = urllib.parse.urlsplit(normalized)
        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_params = [(k, v) for k, v in query_params if k.lower() != "channel_binding"]
        new_query = urllib.parse.urlencode(filtered_params)
        normalized = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

    return normalized


# ---------------------------------------------------------------------------
# Execution Models & Exceptions
# ---------------------------------------------------------------------------

class ExecutionResult(BaseModel):
    """Structured result set from a safe read-only SQL execution."""
    columns: List[str] = Field(description="Names of columns returned")
    rows: List[Dict[str, Any]] = Field(description="List of row dictionaries with serializable values")
    row_count: int = Field(description="Total number of rows returned")
    execution_time_ms: float = Field(description="Execution latency in milliseconds")
    executed_sql: str = Field(description="The sanitized, transpiled, and limited SQL executed")


class DatabaseExecutionError(Exception):
    """Exception raised when database query execution fails."""

    def __init__(
        self,
        message: str,
        failed_sql: str,
        dialect: str,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.failed_sql = failed_sql
        self.dialect = dialect
        self.original_error = original_error

    def get_diagnostic_message(self) -> str:
        """Extract a clean, high-signal error message suitable for LLM self-healing reflection."""
        if self.original_error is not None:
            # Check for underlying DBAPI driver error
            if isinstance(self.original_error, DBAPIError) and self.original_error.orig:
                driver_msg = str(self.original_error.orig).strip()
                # Remove Python exception class prefixes like (sqlite3.OperationalError)
                driver_msg = re.sub(r"^\([^)]+\)\s*", "", driver_msg)
                return driver_msg
            return str(self.original_error).strip()
        return self.message


# ---------------------------------------------------------------------------
# Database Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Manages dynamic SQLAlchemy engine pools and safe read-only query execution."""

    def __init__(self, max_cached_engines: int = 20):
        self._engines: OrderedDict[str, Engine] = OrderedDict()
        self._lock = threading.Lock()
        self._max_cached_engines = max_cached_engines

    def _create_engine_for_uri(self, uri: str) -> Engine:
        """Create a properly tuned SQLAlchemy engine based on connection dialect."""
        settings = get_settings()
        norm_uri = normalize_database_uri(uri)
        url = make_url(norm_uri)
        backend = url.get_backend_name().lower()

        if backend == "sqlite":
            is_memory = ":memory:" in norm_uri or norm_uri.endswith("/:memory:")
            if is_memory:
                return create_engine(
                    norm_uri,
                    connect_args={"check_same_thread": False},
                    poolclass=StaticPool,
                    echo=False,
                )
            return create_engine(
                norm_uri,
                connect_args={"check_same_thread": False, "timeout": settings.DATABASE_TIMEOUT_SECONDS},
                pool_pre_ping=True,
                echo=False,
            )

        # PostgreSQL, MySQL, MSSQL connection pooling
        return create_engine(
            norm_uri,
            poolclass=QueuePool,
            pool_size=settings.SQL_POOL_SIZE,
            max_overflow=settings.SQL_MAX_OVERFLOW,
            pool_timeout=settings.SQL_POOL_TIMEOUT,
            pool_pre_ping=True,
            pool_recycle=1800,  # Recycle dropped connections after 30 mins
            echo=False,
        )

    def register_engine(self, connection_id: str, uri: str) -> Engine:
        """Register or retrieve an active engine for connection_id.

        Maintains an LRU cache of engines to prevent connection resource leaks.
        """
        with self._lock:
            if connection_id in self._engines:
                # Move to end (most recently used)
                self._engines.move_to_end(connection_id)
                return self._engines[connection_id]

            # Evict oldest engine if capacity exceeded
            if len(self._engines) >= self._max_cached_engines:
                oldest_id, oldest_engine = self._engines.popitem(last=False)
                try:
                    oldest_engine.dispose()
                    logger.info("Evicted and disposed idle engine for connection '%s'", oldest_id)
                except Exception as exc:
                    logger.warning("Error disposing engine for '%s': %s", oldest_id, exc)

            engine = self._create_engine_for_uri(uri)
            self._engines[connection_id] = engine
            logger.info("Created and registered engine for connection '%s' (%s)", connection_id, mask_connection_uri(uri))
            return engine

    def get_engine(self, connection_id: str) -> Optional[Engine]:
        """Get an existing engine by connection_id without creating a new one."""
        with self._lock:
            engine = self._engines.get(connection_id)
            if engine is not None:
                self._engines.move_to_end(connection_id)
            return engine

    def get_or_create_engine_from_encrypted(
        self,
        connection_id: str,
        encrypted_uri: str,
    ) -> Engine:
        """Retrieve existing engine or decrypt URI and create engine if missing."""
        engine = self.get_engine(connection_id)
        if engine is not None:
            return engine

        raw_uri = decrypt_connection_uri(encrypted_uri)
        return self.register_engine(connection_id, raw_uri)

    def close_engine(self, connection_id: str) -> bool:
        """Dispose of connection pool and remove engine from cache."""
        with self._lock:
            engine = self._engines.pop(connection_id, None)
            if engine is not None:
                try:
                    engine.dispose()
                    logger.info("Disposed engine pool for connection '%s'", connection_id)
                    return True
                except Exception as exc:
                    logger.error("Error disposing engine for '%s': %s", connection_id, exc)
            return False

    def close_all(self) -> None:
        """Dispose of all active connection pools (called on shutdown)."""
        with self._lock:
            for conn_id, engine in list(self._engines.items()):
                try:
                    engine.dispose()
                except Exception as exc:
                    logger.error("Error disposing engine for '%s': %s", conn_id, exc)
            self._engines.clear()
            logger.info("All database engines have been cleanly disposed.")

    def test_connection(self, uri: str, timeout_seconds: int = 5) -> Dict[str, Any]:
        """Validate connection credentials and measure round-trip latency.

        Uses NullPool so no idle persistent connections are created.
        """
        norm_uri = normalize_database_uri(uri)
        start_time = time.perf_counter()
        masked_uri = mask_connection_uri(norm_uri)
        url = make_url(norm_uri)
        dialect_name = url.get_backend_name().lower()

        test_engine: Optional[Engine] = None
        try:
            if dialect_name == "sqlite":
                test_engine = create_engine(
                    norm_uri,
                    connect_args={"check_same_thread": False, "timeout": timeout_seconds},
                    poolclass=NullPool,
                )
            else:
                test_engine = create_engine(
                    norm_uri,
                    poolclass=NullPool,
                    connect_args={"connect_timeout": timeout_seconds} if dialect_name in ("postgresql", "mysql") else {},
                )

            with test_engine.connect() as conn:
                conn = conn.execution_options(timeout=timeout_seconds)
                result = conn.execute(text("SELECT 1"))
                result.fetchall()

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "success": True,
                "latency_ms": latency_ms,
                "dialect": dialect_name,
                "masked_uri": masked_uri,
            }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            error_msg = str(exc).strip()
            if hasattr(exc, "orig") and getattr(exc, "orig"):
                error_msg = str(getattr(exc, "orig")).strip()
            logger.warning("Connection test failed for '%s': %s", masked_uri, error_msg)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "dialect": dialect_name,
                "masked_uri": masked_uri,
                "error": error_msg,
            }
        finally:
            if test_engine is not None:
                try:
                    test_engine.dispose()
                except Exception:
                    pass

    def _configure_read_only_session(
        self,
        conn: sa.Connection,
        dialect_name: str,
        timeout_seconds: int,
    ) -> None:
        """Apply session-level read-only constraints and hard timeouts per dialect (safe for poolers)."""
        timeout_ms = int(timeout_seconds * 1000)

        if dialect_name in ("postgresql", "postgres"):
            try:
                conn.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
            except Exception as exc:
                logger.debug("Cloud pooler skipped statement_timeout: %s", exc)
            try:
                conn.execute(text("SET TRANSACTION READ ONLY"))
            except Exception as exc:
                logger.debug("Cloud pooler skipped transaction read only: %s", exc)
        elif dialect_name in ("mysql", "mariadb"):
            try:
                conn.execute(text(f"SET SESSION max_execution_time = {timeout_ms}"))
                conn.execute(text("SET TRANSACTION READ ONLY"))
            except Exception as exc:
                logger.debug("MySQL pooler skipped session options: %s", exc)
        elif dialect_name == "sqlite":
            conn.execute(text("PRAGMA query_only = ON"))
            conn.execute(text(f"PRAGMA busy_timeout = {timeout_ms}"))
        elif dialect_name in ("mssql", "tsql"):
            try:
                conn.execute(text(f"SET LOCK_TIMEOUT {timeout_ms}"))
            except Exception as exc:
                logger.debug("MSSQL skipped lock timeout: %s", exc)

    def execute_read_only_query(
        self,
        connection_id: str,
        sql: str,
        engine: Optional[Engine] = None,
        timeout_seconds: Optional[int] = None,
        max_rows: Optional[int] = None,
    ) -> ExecutionResult:
        """Execute a validated, read-only SQL query with statement timeouts.

        1. Validates query against AST guardrails and applies automatic row limiting.
        2. Configures dialect-specific read-only session options.
        3. Executes query and transforms results into serializable dicts.
        4. Re-raises rich DatabaseExecutionError on any SQL error for self-healing reflection.

        Args:
            connection_id: Identifier of the connection.
            sql: Raw SQL query text.
            engine: Optional active Engine. If None, retrieves from cache.
            timeout_seconds: Hard statement timeout (defaults to Settings.DATABASE_TIMEOUT_SECONDS).
            max_rows: Row limit cap (defaults to Settings.DEFAULT_ROW_LIMIT).

        Returns:
            ExecutionResult containing columns, rows, count, latency, and executed SQL.

        Raises:
            SQLSecurityError: If AST guardrail detects disallowed statements.
            SQLSyntaxError: If query syntax cannot be parsed.
            DatabaseExecutionError: If query fails against the live database.
        """
        settings = get_settings()
        target_engine = engine or self.get_engine(connection_id)
        if target_engine is None:
            raise DatabaseExecutionError(
                message=f"No active database engine found for connection '{connection_id}'.",
                failed_sql=sql,
                dialect="unknown",
            )

        dialect_name = target_engine.dialect.name.lower()
        timeout = timeout_seconds if timeout_seconds is not None else settings.DATABASE_TIMEOUT_SECONDS
        row_limit = max_rows if max_rows is not None else settings.DEFAULT_ROW_LIMIT

        # 1. AST Validation and Row Limiting
        sanitized_sql = validate_and_sanitize_sql(
            sql=sql,
            dialect=dialect_name,
            max_rows=row_limit,
        )

        start_time = time.perf_counter()

        try:
            with target_engine.connect() as conn:
                # Apply read-only mode and statement timeout
                self._configure_read_only_session(conn, dialect_name, timeout)

                # Execute with execution timeout option
                cursor = conn.execution_options(timeout=timeout).execute(text(sanitized_sql))
                columns = list(cursor.keys())
                raw_rows = cursor.fetchall()

                # Serialize cells safely
                serialized_rows: List[Dict[str, Any]] = []
                for row in raw_rows:
                    row_dict = {
                        columns[idx]: serialize_cell(val)
                        for idx, val in enumerate(row)
                    }
                    serialized_rows.append(row_dict)

                execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

                return ExecutionResult(
                    columns=columns,
                    rows=serialized_rows,
                    row_count=len(serialized_rows),
                    execution_time_ms=execution_time_ms,
                    executed_sql=sanitized_sql,
                )

        except (SQLSecurityError, SQLSyntaxError):
            raise
        except SQLAlchemyError as exc:
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.warning(
                "SQL execution failed on connection '%s' after %.2fms: %s",
                connection_id,
                execution_time_ms,
                exc,
            )
            raise DatabaseExecutionError(
                message=f"Database execution error: {exc}",
                failed_sql=sanitized_sql,
                dialect=dialect_name,
                original_error=exc,
            ) from exc
        except Exception as exc:
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                "Unexpected failure executing query on connection '%s': %s",
                connection_id,
                exc,
                exc_info=True,
            )
            raise DatabaseExecutionError(
                message=f"Unexpected query execution error: {exc}",
                failed_sql=sanitized_sql,
                dialect=dialect_name,
                original_error=exc,
            ) from exc


# ---------------------------------------------------------------------------
# Global Singleton Accessor
# ---------------------------------------------------------------------------

_GLOBAL_CONNECTION_MANAGER: Optional[ConnectionManager] = None
_GLOBAL_MANAGER_LOCK = threading.Lock()


def get_connection_manager() -> ConnectionManager:
    """Retrieve the application-wide ConnectionManager singleton."""
    global _GLOBAL_CONNECTION_MANAGER
    if _GLOBAL_CONNECTION_MANAGER is None:
        with _GLOBAL_MANAGER_LOCK:
            if _GLOBAL_CONNECTION_MANAGER is None:
                _GLOBAL_CONNECTION_MANAGER = ConnectionManager()
    return _GLOBAL_CONNECTION_MANAGER
