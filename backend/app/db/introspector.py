"""Smart Schema Introspection, Metadata Extraction, and In-Memory Caching.

Extracts table structures, column types, primary keys, foreign keys, and safe sample rows
using SQLAlchemy 2.0 inspect(). Formats compact DDL representations for LLM prompt context
and caches schemas in memory with a configurable TTL.
"""

from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
import logging
import math
import threading
import time as time_mod
from typing import Any, Dict, List, Optional, Tuple
import uuid

from pydantic import BaseModel, Field
import sqlalchemy as sa
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic v2 Models for Schema Representation
# ---------------------------------------------------------------------------

class ColumnInfo(BaseModel):
    """Metadata for a single database column."""
    name: str = Field(description="Column identifier")
    type: str = Field(description="Normalized SQL data type representation")
    nullable: bool = Field(default=True, description="Whether column accepts NULL values")
    primary_key: bool = Field(default=False, description="Whether column is part of primary key")
    default: Optional[str] = Field(default=None, description="Default column value or expression")


class ForeignKeyInfo(BaseModel):
    """Foreign key relationship metadata between tables."""
    constrained_columns: List[str] = Field(description="Columns in the child table")
    referred_table: str = Field(description="Target referenced parent table")
    referred_columns: List[str] = Field(description="Target referenced columns in parent table")


class IndexInfo(BaseModel):
    """Index metadata for performance and uniqueness context."""
    name: Optional[str] = Field(default=None, description="Index name")
    columns: List[str] = Field(default_factory=list, description="Indexed column names")
    unique: bool = Field(default=False, description="Whether index enforces uniqueness")


class TableMetadata(BaseModel):
    """Complete metadata and sample records for a database table."""
    name: str = Field(description="Table name")
    columns: List[ColumnInfo] = Field(default_factory=list, description="Table column definitions")
    primary_keys: List[str] = Field(default_factory=list, description="Primary key column names")
    foreign_keys: List[ForeignKeyInfo] = Field(default_factory=list, description="Foreign key relations")
    indexes: List[IndexInfo] = Field(default_factory=list, description="Table indexes")
    sample_rows: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Up to 3 sample records for concrete context",
    )
    row_count_approx: Optional[int] = Field(
        default=None,
        description="Approximate or exact total row count if available",
    )


class DatabaseSchema(BaseModel):
    """Complete catalog of tables, relations, and sample records for an active connection."""
    dialect: str = Field(description="Detected database dialect (e.g. postgresql, mysql, sqlite)")
    tables: Dict[str, TableMetadata] = Field(
        default_factory=dict,
        description="Mapping of table name to TableMetadata",
    )
    introspected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 UTC timestamp of introspection",
    )

    def get_table_names(self) -> List[str]:
        """Return sorted list of table names in the schema."""
        return sorted(list(self.tables.keys()))

    def to_compact_ddl(self, table_names: Optional[List[str]] = None) -> str:
        """Format a token-efficient, high-signal DDL + sample rows string for LLM prompts.

        Args:
            table_names: Optional subset of table names to format. If None, includes all tables.

        Returns:
            Compact SQL-like DDL schema with foreign key notes and sample rows.
        """
        target_tables = (
            [self.tables[t] for t in table_names if t in self.tables]
            if table_names
            else list(self.tables.values())
        )

        if not target_tables:
            return "-- No relevant tables found in database schema."

        blocks: List[str] = []
        for table in target_tables:
            col_lines: List[str] = []
            for col in table.columns:
                constraints = []
                if col.primary_key:
                    constraints.append("PRIMARY KEY")
                elif not col.nullable:
                    constraints.append("NOT NULL")
                if col.default:
                    constraints.append(f"DEFAULT {col.default}")

                constraint_str = (" " + " ".join(constraints)) if constraints else ""
                col_lines.append(f"  {col.name} {col.type}{constraint_str}")

            ddl = f"CREATE TABLE {table.name} (\n" + ",\n".join(col_lines) + "\n);"

            # Add foreign keys if present
            fk_notes: List[str] = []
            for fk in table.foreign_keys:
                child_cols = ", ".join(fk.constrained_columns)
                parent_cols = ", ".join(fk.referred_columns)
                fk_notes.append(
                    f"-- Foreign Key: ({child_cols}) REFERENCES {fk.referred_table}({parent_cols})"
                )

            # Add sample rows
            sample_notes: List[str] = []
            if table.sample_rows:
                sample_notes.append(f"-- Sample Rows ({len(table.sample_rows)} records):")
                for row in table.sample_rows:
                    clean_row = {k: v for k, v in row.items()}
                    sample_notes.append(f"-- {json.dumps(clean_row, default=str)}")
            else:
                sample_notes.append("-- (Table is empty)")

            full_block = ddl
            if fk_notes:
                full_block += "\n" + "\n".join(fk_notes)
            if sample_notes:
                full_block += "\n" + "\n".join(sample_notes)

            blocks.append(full_block)

        return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# In-Memory Thread-Safe Schema Cache
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: Dict[str, Tuple[DatabaseSchema, float]] = {}
_CACHE_LOCK = threading.Lock()


def get_cached_schema(connection_id: str) -> Optional[DatabaseSchema]:
    """Retrieve schema from in-memory cache if not expired."""
    if not connection_id:
        return None

    with _CACHE_LOCK:
        entry = _SCHEMA_CACHE.get(connection_id)
        if entry is None:
            return None

        schema, expire_time = entry
        if time_mod.time() > expire_time:
            # Entry has expired
            del _SCHEMA_CACHE[connection_id]
            return None

        return schema


def set_cached_schema(
    connection_id: str,
    schema: DatabaseSchema,
    ttl_seconds: Optional[int] = None,
) -> None:
    """Store schema in memory cache with specified or default TTL."""
    if not connection_id:
        return

    ttl = ttl_seconds if ttl_seconds is not None else get_settings().SCHEMA_CACHE_TTL_SECONDS
    expire_time = time_mod.time() + ttl

    with _CACHE_LOCK:
        _SCHEMA_CACHE[connection_id] = (schema, expire_time)


def invalidate_schema_cache(connection_id: str) -> bool:
    """Evict a connection's cached schema (e.g. on manual 'Refresh Schema' click)."""
    with _CACHE_LOCK:
        return _SCHEMA_CACHE.pop(connection_id, None) is not None


def clear_all_schema_caches() -> None:
    """Evict all cached schemas from memory."""
    with _CACHE_LOCK:
        _SCHEMA_CACHE.clear()


# ---------------------------------------------------------------------------
# Data Serialization Utilities
# ---------------------------------------------------------------------------

def serialize_cell(val: Any) -> Any:
    """Convert arbitrary database cell values to JSON-serializable primitives."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, Decimal):
        if val.is_nan() or val.is_infinite():
            return None
        return int(val) if val % 1 == 0 else float(val)
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, bytes):
        return f"<bytes len={len(val)}>"
    if isinstance(val, (list, tuple)):
        return [serialize_cell(item) for item in val]
    if isinstance(val, dict):
        return {str(k): serialize_cell(v) for k, v in val.items()}
    return str(val)


# ---------------------------------------------------------------------------
# Core Schema Introspector
# ---------------------------------------------------------------------------

class SchemaIntrospector:
    """Introspects relational database schemas using SQLAlchemy 2.0 inspect()."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.dialect_name = engine.dialect.name.lower()
        self.preparer = engine.dialect.identifier_preparer

    def _quote_identifier(self, identifier: str) -> str:
        """Safely quote a table or column identifier for the active dialect."""
        return self.preparer.quote(identifier)

    def extract_sample_rows(self, table_name: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Fetch up to `limit` sample rows using a safe read-only query.

        Converts all cell values to JSON-serializable types.
        """
        quoted_table = self._quote_identifier(table_name)
        # Use dialect-appropriate query limit
        query_sql = f"SELECT * FROM {quoted_table} LIMIT :sample_limit"

        try:
            with self.engine.connect() as conn:
                # Enforce read-only execution option and timeout
                conn = conn.execution_options(timeout=5)
                cursor = conn.execute(text(query_sql), {"sample_limit": limit})
                column_keys = list(cursor.keys())
                raw_rows = cursor.fetchall()

                samples: List[Dict[str, Any]] = []
                for row in raw_rows:
                    row_dict = {
                        column_keys[idx]: serialize_cell(val)
                        for idx, val in enumerate(row)
                    }
                    samples.append(row_dict)

                return samples
        except Exception as exc:
            logger.warning(
                "Could not extract sample rows for table '%s': %s",
                table_name,
                exc,
            )
            return []

    def introspect(self) -> DatabaseSchema:
        """Perform comprehensive schema introspection across all tables."""
        inspector = inspect(self.engine)
        table_names = inspector.get_table_names()

        # Exclude common system tables across dialects
        system_tables = {
            "sqlite_sequence", "sqlite_stat1", "sqlite_stat4",
            "spatial_ref_sys", "alembic_version",
        }
        filtered_tables = [t for t in table_names if t.lower() not in system_tables]

        tables_meta: Dict[str, TableMetadata] = {}

        for table_name in filtered_tables:
            try:
                # 1. Primary keys
                pk_constraint = inspector.get_pk_constraint(table_name) or {}
                pk_cols = set(pk_constraint.get("constrained_columns") or [])

                # 2. Columns
                raw_columns = inspector.get_columns(table_name)
                columns: List[ColumnInfo] = []
                for col in raw_columns:
                    col_name = col.get("name", "")
                    col_type_str = str(col.get("type", "UNKNOWN"))
                    is_nullable = bool(col.get("nullable", True))
                    default_val = col.get("default")
                    default_str = str(default_val) if default_val is not None else None

                    columns.append(
                        ColumnInfo(
                            name=col_name,
                            type=col_type_str,
                            nullable=is_nullable,
                            primary_key=col_name in pk_cols,
                            default=default_str,
                        )
                    )

                # 3. Foreign keys
                raw_fks = inspector.get_foreign_keys(table_name) or []
                foreign_keys: List[ForeignKeyInfo] = []
                for fk in raw_fks:
                    c_cols = fk.get("constrained_columns") or []
                    ref_table = fk.get("referred_table") or ""
                    ref_cols = fk.get("referred_columns") or []
                    if ref_table and c_cols:
                        foreign_keys.append(
                            ForeignKeyInfo(
                                constrained_columns=c_cols,
                                referred_table=ref_table,
                                referred_columns=ref_cols,
                            )
                        )

                # 4. Indexes
                raw_indexes = inspector.get_indexes(table_name) or []
                indexes: List[IndexInfo] = []
                for idx in raw_indexes:
                    indexes.append(
                        IndexInfo(
                            name=idx.get("name"),
                            columns=idx.get("column_names") or [],
                            unique=bool(idx.get("unique", False)),
                        )
                    )

                # 5. Sample rows
                sample_rows = self.extract_sample_rows(table_name, limit=3)

                tables_meta[table_name] = TableMetadata(
                    name=table_name,
                    columns=columns,
                    primary_keys=list(pk_cols),
                    foreign_keys=foreign_keys,
                    indexes=indexes,
                    sample_rows=sample_rows,
                )
            except Exception as exc:
                logger.error(
                    "Error introspecting table '%s': %s",
                    table_name,
                    exc,
                    exc_info=True,
                )
                # Continue with remaining tables instead of abandoning entire schema
                continue

        return DatabaseSchema(
            dialect=self.dialect_name,
            tables=tables_meta,
        )


def introspect_database(
    engine: Engine,
    connection_id: Optional[str] = None,
    force_refresh: bool = False,
) -> DatabaseSchema:
    """Introspect a database with transparent in-memory TTL caching.

    Args:
        engine: Active SQLAlchemy Engine instance.
        connection_id: Optional connection identifier for cache lookup/storage.
        force_refresh: If True, bypasses cache and re-introspects immediately.

    Returns:
        DatabaseSchema instance with complete table metadata and sample rows.
    """
    if connection_id and not force_refresh:
        cached = get_cached_schema(connection_id)
        if cached is not None:
            logger.info("Returning cached schema for connection '%s'", connection_id)
            return cached

    introspector = SchemaIntrospector(engine)
    schema = introspector.introspect()

    if connection_id:
        set_cached_schema(connection_id, schema)

    return schema
