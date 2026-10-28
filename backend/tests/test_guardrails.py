"""Tests for AST SQL security guardrails, read-only enforcement, and row limiting."""

import pytest
from app.db.guardrails import (
    SQLSecurityError,
    SQLSyntaxError,
    strip_markdown_sql,
    validate_and_sanitize_sql,
)


def test_strip_markdown_sql():
    """Verify that markdown backtick code blocks are cleanly stripped."""
    raw = "```sql\nSELECT * FROM customers WHERE id = 1;\n```"
    assert strip_markdown_sql(raw) == "SELECT * FROM customers WHERE id = 1"

    plain = "SELECT id, name FROM users"
    assert strip_markdown_sql(plain) == "SELECT id, name FROM users"


def test_valid_select_query():
    """Verify that a standard SELECT query is accepted and transpiled cleanly."""
    sql = "SELECT id, name FROM customers WHERE active = true"
    sanitized = validate_and_sanitize_sql(sql, dialect="postgres", max_rows=500)
    assert "SELECT" in sanitized
    assert "customers" in sanitized
    assert "LIMIT 500" in sanitized


def test_valid_union_query():
    """Verify that a UNION query is accepted and capped with LIMIT."""
    sql = "SELECT id FROM orders UNION SELECT id FROM invoices"
    sanitized = validate_and_sanitize_sql(sql, dialect="postgres", max_rows=500)
    assert "UNION" in sanitized
    assert "LIMIT 500" in sanitized


def test_row_limit_injection():
    """Verify that an automatic LIMIT 500 is injected if query has no LIMIT clause."""
    sql = "SELECT * FROM large_table"
    sanitized = validate_and_sanitize_sql(sql, dialect="postgres", max_rows=500)
    assert sanitized.endswith("LIMIT 500")


def test_row_limit_capped():
    """Verify that a LIMIT greater than max_rows is capped down to max_rows."""
    sql = "SELECT * FROM large_table LIMIT 10000"
    sanitized = validate_and_sanitize_sql(sql, dialect="postgres", max_rows=500)
    assert "LIMIT 500" in sanitized
    assert "10000" not in sanitized


def test_row_limit_preserved_when_under_cap():
    """Verify that an existing LIMIT smaller than max_rows is preserved."""
    sql = "SELECT * FROM large_table LIMIT 25"
    sanitized = validate_and_sanitize_sql(sql, dialect="postgres", max_rows=500)
    assert "LIMIT 25" in sanitized


@pytest.mark.parametrize(
    "destructive_query",
    [
        "DROP TABLE users",
        "DROP DATABASE analytics",
        "DELETE FROM users WHERE id = 1",
        "TRUNCATE TABLE logs",
        "UPDATE users SET role = 'admin' WHERE id = 5",
        "INSERT INTO accounts (id, balance) VALUES (1, 1000)",
        "ALTER TABLE users ADD COLUMN is_admin BOOLEAN",
        "CREATE TABLE secret_backdoor (id INT)",
        "GRANT ALL PRIVILEGES ON DATABASE analytics TO evil_user",
        "REVOKE SELECT ON users FROM analyst",
    ],
)
def test_destructive_sql_blocked(destructive_query: str):
    """Verify that all DDL, DML, and privilege operations are immediately blocked."""
    with pytest.raises(SQLSecurityError) as exc_info:
        validate_and_sanitize_sql(destructive_query, dialect="postgres")
    assert "Only SELECT and UNION" in str(exc_info.value) or "Disallowed" in str(exc_info.value)


def test_nested_cte_mutation_blocked():
    """Verify that data-modifying CTEs (e.g. DELETE in WITH clause) are blocked."""
    cte_exploit = "WITH deleted AS (DELETE FROM users RETURNING *) SELECT * FROM deleted"
    with pytest.raises(SQLSecurityError) as exc_info:
        validate_and_sanitize_sql(cte_exploit, dialect="postgres")
    assert "Disallowed destructive operation detected in query: 'DELETE'" in str(exc_info.value)


def test_multi_statement_injection_blocked():
    """Verify that multi-statement queries (e.g. piggybacked DROP) are rejected."""
    multi_sql = "SELECT 1; DROP TABLE users;"
    with pytest.raises(SQLSecurityError) as exc_info:
        validate_and_sanitize_sql(multi_sql, dialect="postgres")
    assert "Multi-statement execution rejected" in str(exc_info.value)


def test_syntax_error_handling():
    """Verify that malformed SQL syntax raises SQLSyntaxError."""
    malformed_sql = "SELECT FROM WHERE"
    with pytest.raises(SQLSyntaxError):
        validate_and_sanitize_sql(malformed_sql, dialect="postgres")
