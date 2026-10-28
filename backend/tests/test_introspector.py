"""Tests for schema introspection, metadata extraction, DDL formatting, and cache."""

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.db.introspector import (
    clear_all_schema_caches,
    get_cached_schema,
    introspect_database,
    invalidate_schema_cache,
)


@pytest.fixture
def sample_db_engine():
    """Create an in-memory SQLite database populated with relational test schema."""
    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE departments (
                    dept_id INTEGER PRIMARY KEY,
                    dept_name VARCHAR(50) NOT NULL
                );
                """
            )
        )
        conn.execute(
            sa.text(
                """
                CREATE TABLE employees (
                    emp_id INTEGER PRIMARY KEY,
                    full_name VARCHAR(100) NOT NULL,
                    salary DECIMAL(10, 2),
                    dept_id INTEGER,
                    FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
                );
                """
            )
        )
        conn.execute(
            sa.text(
                """
                CREATE INDEX idx_emp_salary ON employees(salary);
                """
            )
        )

        # Seed sample rows
        conn.execute(
            sa.text(
                """
                INSERT INTO departments (dept_id, dept_name) VALUES
                (1, 'Engineering'),
                (2, 'Marketing'),
                (3, 'Finance');
                """
            )
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO employees (emp_id, full_name, salary, dept_id) VALUES
                (101, 'Alice Smith', 95000.50, 1),
                (102, 'Bob Jones', 72000.00, 2),
                (103, 'Charlie Brown', 110000.00, 1),
                (104, 'Diana Prince', 88000.00, 3);
                """
            )
        )

    yield engine
    engine.dispose()


def test_schema_introspection(sample_db_engine):
    """Verify tables, columns, foreign keys, and sample rows are accurately extracted."""
    clear_all_schema_caches()

    schema = introspect_database(sample_db_engine, connection_id="test-conn-1")
    assert schema.dialect == "sqlite"
    assert "departments" in schema.tables
    assert "employees" in schema.tables

    # Verify departments metadata
    dept_table = schema.tables["departments"]
    col_names = [col.name for col in dept_table.columns]
    assert "dept_id" in col_names
    assert "dept_name" in col_names
    assert dept_table.primary_keys == ["dept_id"]
    assert len(dept_table.sample_rows) == 3

    # Verify employees metadata & foreign key
    emp_table = schema.tables["employees"]
    assert emp_table.primary_keys == ["emp_id"]
    assert len(emp_table.foreign_keys) == 1
    fk = emp_table.foreign_keys[0]
    assert fk.referred_table == "departments"
    assert fk.constrained_columns == ["dept_id"]
    assert fk.referred_columns == ["dept_id"]

    # Verify sample rows capped to 3
    assert len(emp_table.sample_rows) == 3
    first_row = emp_table.sample_rows[0]
    assert first_row["emp_id"] == 101
    assert first_row["full_name"] == "Alice Smith"


def test_compact_ddl_formatting(sample_db_engine):
    """Verify that to_compact_ddl outputs readable, token-efficient prompt context."""
    schema = introspect_database(sample_db_engine)
    ddl = schema.to_compact_ddl()

    assert "CREATE TABLE departments" in ddl
    assert "CREATE TABLE employees" in ddl
    assert "REFERENCES departments(dept_id)" in ddl
    assert "-- Sample Rows" in ddl
    assert "Alice Smith" in ddl


def test_schema_caching_and_invalidation(sample_db_engine):
    """Verify that schema is retrieved from cache and can be manually invalidated."""
    conn_id = "cache-test-conn"
    clear_all_schema_caches()

    # First introspection caches schema
    schema1 = introspect_database(sample_db_engine, connection_id=conn_id)
    cached = get_cached_schema(conn_id)
    assert cached is not None
    assert cached.dialect == schema1.dialect

    # Invalidate cache
    assert invalidate_schema_cache(conn_id) is True
    assert get_cached_schema(conn_id) is None
