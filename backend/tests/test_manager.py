"""Tests for ConnectionManager, pooling lifecycle, and read-only query execution."""

import pytest
import sqlalchemy as sa

from app.db.guardrails import SQLSecurityError
from app.db.manager import (
    ConnectionManager,
    DatabaseExecutionError,
    ExecutionResult,
    normalize_database_uri,
)


@pytest.fixture
def manager_with_sqlite():
    """Create a test ConnectionManager with a seeded SQLite database."""
    manager = ConnectionManager(max_cached_engines=5)
    conn_id = "test-manager-conn"
    uri = "sqlite:///:memory:"

    engine = manager.register_engine(conn_id, uri)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE products (
                    product_id INTEGER PRIMARY KEY,
                    product_name VARCHAR(50),
                    unit_price DECIMAL(10, 2),
                    units_in_stock INTEGER
                );
                """
            )
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO products (product_id, product_name, unit_price, units_in_stock) VALUES
                (1, 'Laptop', 1200.00, 15),
                (2, 'Mouse', 25.50, 150),
                (3, 'Keyboard', 75.00, 60);
                """
            )
        )

    yield manager, conn_id
    manager.close_all()


def test_test_connection():
    """Verify that test_connection returns connection latency and dialect."""
    manager = ConnectionManager()
    res = manager.test_connection("sqlite:///:memory:")
    assert res["success"] is True
    assert res["dialect"] == "sqlite"
    assert res["latency_ms"] >= 0


def test_execute_read_only_query_success(manager_with_sqlite):
    """Verify successful read-only query execution with structured ExecutionResult."""
    manager, conn_id = manager_with_sqlite
    query = "SELECT product_name, unit_price FROM products WHERE units_in_stock > 20 ORDER BY unit_price ASC"

    result: ExecutionResult = manager.execute_read_only_query(
        connection_id=conn_id,
        sql=query,
    )

    assert result.columns == ["product_name", "unit_price"]
    assert result.row_count == 2
    assert result.rows[0]["product_name"] == "Mouse"
    assert result.rows[1]["product_name"] == "Keyboard"
    assert result.execution_time_ms >= 0
    assert "LIMIT 500" in result.executed_sql


def test_execute_blocks_drop_table(manager_with_sqlite):
    """Verify that DROP TABLE is blocked by AST guardrails before execution."""
    manager, conn_id = manager_with_sqlite
    drop_sql = "DROP TABLE products"

    with pytest.raises(SQLSecurityError):
        manager.execute_read_only_query(connection_id=conn_id, sql=drop_sql)

    # Ensure table still exists and data is untouched
    verify_result = manager.execute_read_only_query(
        connection_id=conn_id,
        sql="SELECT COUNT(*) AS total FROM products",
    )
    assert verify_result.rows[0]["total"] == 3


def test_execute_captures_error_for_self_healing(manager_with_sqlite):
    """Verify that schema/column errors raise DatabaseExecutionError with clean diagnostics."""
    manager, conn_id = manager_with_sqlite
    # Deliberate typo in column name: 'price' instead of 'unit_price'
    failing_sql = "SELECT product_name, price FROM products"

    with pytest.raises(DatabaseExecutionError) as exc_info:
        manager.execute_read_only_query(connection_id=conn_id, sql=failing_sql)

    diagnostic = exc_info.value.get_diagnostic_message()
    assert "no such column: price" in diagnostic.lower()
    assert exc_info.value.dialect == "sqlite"


def test_normalize_database_uri_neon_and_drivers():
    """Verify that normalize_database_uri converts schemes and sanitizes Neon parameters."""
    # Neon Serverless Pooler with channel_binding=require
    neon_uri = (
        "postgresql://neondb_owner:npg_secret123@ep-cool-pooler.c-7.eu-central-1.aws.neon.tech/neondb"
        "?channel_binding=require&sslmode=require"
    )
    normalized = normalize_database_uri(neon_uri)
    assert normalized.startswith("postgresql+psycopg://")
    assert "channel_binding" not in normalized
    assert "sslmode=require" in normalized

    # postgres:// alias
    assert normalize_database_uri("postgres://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"

    # postgresql+psycopg2:// legacy alias
    assert normalize_database_uri("postgresql+psycopg2://user:pass@localhost:5432/db") == "postgresql+psycopg://user:pass@localhost:5432/db"

    # MySQL dialect normalization
    assert normalize_database_uri("mysql://user:pass@localhost:3306/db") == "mysql+pymysql://user:pass@localhost:3306/db"

    # SQLite intact
    assert normalize_database_uri("sqlite:///demo.db") == "sqlite:///demo.db"


def test_pooler_safe_configure_read_only_session():
    """Verify that _configure_read_only_session silently handles cloud pooler rejection of SET statements."""
    manager = ConnectionManager()
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.connect() as conn:
        # Calling with postgresql dialect on SQLite conn causes SET LOCAL to raise SQLite syntax error
        # Manager should catch and log debug rather than failing the execution
        manager._configure_read_only_session(conn, dialect_name="postgresql", timeout_seconds=5)
    engine.dispose()
