"""Database connection management, testing, and schema explorer endpoints."""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from sqlalchemy.engine import make_url

from app.core.security import (
    decrypt_connection_uri,
    encrypt_connection_uri,
    mask_connection_uri,
)
from app.db.introspector import (
    DatabaseSchema,
    get_cached_schema,
    introspect_database,
    invalidate_schema_cache,
)
from app.db.manager import get_connection_manager, normalize_database_uri

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connections", tags=["Connections"])


# ---------------------------------------------------------------------------
# Request and Response Schemas
# ---------------------------------------------------------------------------

class ConnectionTestRequest(BaseModel):
    """Payload to test database connectivity before saving."""
    uri: Optional[str] = Field(default=None, description="Direct connection URI string")
    dialect: Optional[str] = Field(default=None, description="Dialect: postgresql, mysql, sqlite, mssql")
    host: Optional[str] = Field(default=None, description="Host server address")
    port: Optional[int] = Field(default=None, description="Port number")
    username: Optional[str] = Field(default=None, description="Database user")
    password: Optional[str] = Field(default=None, description="Database password")
    database: Optional[str] = Field(default=None, description="Database name")
    ssl: bool = Field(default=False, description="Enable SSL connection")


class ConnectionCreateRequest(BaseModel):
    """Payload to register and store an encrypted database connection."""
    name: Optional[str] = Field(default=None, description="Friendly display label for this connection")
    uri: Optional[str] = Field(default=None, description="Direct connection URI string")
    dialect: Optional[str] = Field(default=None, description="Dialect: postgresql, mysql, sqlite, mssql")
    host: Optional[str] = Field(default=None, description="Host server address")
    port: Optional[int] = Field(default=None, description="Port number")
    username: Optional[str] = Field(default=None, description="Database user")
    password: Optional[str] = Field(default=None, description="Database password")
    database: Optional[str] = Field(default=None, description="Database name")
    ssl: bool = Field(default=False, description="Enable SSL connection")


class ConnectionResponse(BaseModel):
    """Sanitized public metadata for a saved connection (never exposes credentials)."""
    id: str
    name: str
    dialect: str
    masked_uri: str
    table_count: int
    created_at: str


class ConnectionTestResponse(BaseModel):
    """Response payload for connectivity test."""
    success: bool
    dialect: str
    latency_ms: float
    masked_uri: str
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Thread-Safe In-Memory Metadata Store
# ---------------------------------------------------------------------------

class ConnectionStore:
    """Stores connection metadata with credentials encrypted at rest."""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def add(
        self,
        conn_id: str,
        name: str,
        dialect: str,
        encrypted_uri: str,
        masked_uri: str,
        table_count: int = 0,
    ) -> Dict[str, Any]:
        record = {
            "id": conn_id,
            "name": name,
            "dialect": dialect,
            "encrypted_uri": encrypted_uri,
            "masked_uri": masked_uri,
            "table_count": table_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._store[conn_id] = record
        return record

    def get(self, conn_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._store.get(conn_id)

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._store.values())

    def update_table_count(self, conn_id: str, count: int) -> None:
        with self._lock:
            if conn_id in self._store:
                self._store[conn_id]["table_count"] = count

    def remove(self, conn_id: str) -> bool:
        with self._lock:
            return self._store.pop(conn_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


connection_store = ConnectionStore()


# ---------------------------------------------------------------------------
# Helper: Construct URI from Form Inputs
# ---------------------------------------------------------------------------

def resolve_uri(
    uri: Optional[str],
    dialect: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    ssl: bool = False,
) -> str:
    """Build a complete connection URI from either direct URI or individual form parameters."""
    if uri and uri.strip():
        clean_uri = uri.strip()
        try:
            make_url(clean_uri)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid database connection URI syntax: {exc}",
            )
        return normalize_database_uri(clean_uri)

    clean_dialect = (dialect or "postgresql").lower().strip()
    user = username or ""
    pwd = password or ""
    db = database or ""
    h = host or "localhost"

    if clean_dialect in ("postgres", "postgresql"):
        p = port or 5432
        ssl_arg = "?sslmode=require" if ssl else ""
        return normalize_database_uri(f"postgresql://{user}:{pwd}@{h}:{p}/{db}{ssl_arg}")

    if clean_dialect in ("mysql", "mariadb"):
        p = port or 3306
        ssl_arg = "?ssl=true" if ssl else ""
        return normalize_database_uri(f"mysql+pymysql://{user}:{pwd}@{h}:{p}/{db}{ssl_arg}")

    if clean_dialect == "sqlite":
        db_path = db or ":memory:"
        return f"sqlite:///{db_path}"

    if clean_dialect in ("mssql", "tsql"):
        p = port or 1433
        return f"mssql+pyodbc://{user}:{pwd}@{h}:{p}/{db}?driver=ODBC+Driver+17+for+SQL+Server"

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported or missing database dialect: '{clean_dialect}'.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/test", response_model=ConnectionTestResponse)
def test_connection_endpoint(payload: ConnectionTestRequest):
    """Test raw database credentials and verify round-trip latency without saving."""
    uri = resolve_uri(
        uri=payload.uri,
        dialect=payload.dialect,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        database=payload.database,
        ssl=payload.ssl,
    )

    manager = get_connection_manager()
    result = manager.test_connection(uri)
    return ConnectionTestResponse(
        success=result["success"],
        dialect=result["dialect"],
        latency_ms=result["latency_ms"],
        masked_uri=result["masked_uri"],
        error=result.get("error"),
    )


@router.post("", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
def create_connection_endpoint(payload: ConnectionCreateRequest):
    """Encrypt credentials via Fernet, initialize pool, warm up schema cache, and return ID."""
    raw_uri = resolve_uri(
        uri=payload.uri,
        dialect=payload.dialect,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        database=payload.database,
        ssl=payload.ssl,
    )

    manager = get_connection_manager()

    # 1. Test connectivity before saving
    test_res = manager.test_connection(raw_uri)
    if not test_res["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to connect to database: {test_res.get('error', 'Unknown error')}",
        )

    # 2. Encrypt credentials at rest
    encrypted_uri = encrypt_connection_uri(raw_uri)
    masked_uri = mask_connection_uri(raw_uri)
    conn_id = f"conn_{uuid.uuid4().hex[:12]}"
    conn_name = payload.name or f"{test_res['dialect'].capitalize()} Connection"

    # 3. Register engine pool
    engine = manager.register_engine(conn_id, raw_uri)

    # 4. Warm up schema introspection
    table_count = 0
    try:
        schema = introspect_database(engine, connection_id=conn_id, force_refresh=True)
        table_count = len(schema.tables)
    except Exception as exc:
        logger.warning("Initial schema introspection warning for '%s': %s", conn_id, exc)

    # 5. Save metadata
    record = connection_store.add(
        conn_id=conn_id,
        name=conn_name,
        dialect=test_res["dialect"],
        encrypted_uri=encrypted_uri,
        masked_uri=masked_uri,
        table_count=table_count,
    )

    return ConnectionResponse(
        id=record["id"],
        name=record["name"],
        dialect=record["dialect"],
        masked_uri=record["masked_uri"],
        table_count=record["table_count"],
        created_at=record["created_at"],
    )


@router.get("", response_model=List[ConnectionResponse])
def list_connections_endpoint():
    """List all registered database connections with credentials masked."""
    records = connection_store.list_all()
    return [
        ConnectionResponse(
            id=r["id"],
            name=r["name"],
            dialect=r["dialect"],
            masked_uri=r["masked_uri"],
            table_count=r["table_count"],
            created_at=r["created_at"],
        )
        for r in records
    ]


@router.get("/{connection_id}/schema", response_model=DatabaseSchema)
def get_connection_schema_endpoint(connection_id: str):
    """Retrieve structured schema (tables, columns, types, PKs, FKs, sample rows) for UI explorer."""
    record = connection_store.get(connection_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found.",
        )

    # Check cache first
    cached = get_cached_schema(connection_id)
    if cached is not None:
        return cached

    # Retrieve or reconstruct engine and introspect
    manager = get_connection_manager()
    engine = manager.get_or_create_engine_from_encrypted(
        connection_id=connection_id,
        encrypted_uri=record["encrypted_uri"],
    )

    schema = introspect_database(engine, connection_id=connection_id)
    connection_store.update_table_count(connection_id, len(schema.tables))
    return schema


@router.post("/{connection_id}/refresh", response_model=DatabaseSchema)
def refresh_connection_schema_endpoint(connection_id: str):
    """Force schema re-introspection and update cached metadata."""
    record = connection_store.get(connection_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found.",
        )

    invalidate_schema_cache(connection_id)
    manager = get_connection_manager()
    engine = manager.get_or_create_engine_from_encrypted(
        connection_id=connection_id,
        encrypted_uri=record["encrypted_uri"],
    )

    schema = introspect_database(engine, connection_id=connection_id, force_refresh=True)
    connection_store.update_table_count(connection_id, len(schema.tables))
    return schema


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection_endpoint(connection_id: str):
    """Dispose active connection pool and remove connection metadata."""
    record = connection_store.get(connection_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found.",
        )

    invalidate_schema_cache(connection_id)
    manager = get_connection_manager()
    manager.close_engine(connection_id)
    connection_store.remove(connection_id)
    return None
