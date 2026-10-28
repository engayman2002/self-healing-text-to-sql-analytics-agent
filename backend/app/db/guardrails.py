"""AST SQL Security Guardrails and Read-Only Enforcement using sqlglot.

Enforces zero-trust database security policies at the AST level:
1. Rejects multi-statement queries.
2. Validates that the root AST node is strictly SELECT or UNION.
3. Recursively scans the entire AST tree to reject data modification expressions (INSERT, UPDATE, DELETE, DROP, etc.) inside CTEs or subqueries.
4. Enforces an automatic LIMIT (default 500) on the outermost query.
5. Transpiles SQL cleanly to the target database dialect.
"""

import re
from typing import List, Optional, Set, Tuple
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError

from app.core.config import get_settings


class GuardrailError(Exception):
    """Base exception for all database guardrail errors."""
    pass


class SQLSecurityError(GuardrailError):
    """Raised when a SQL query violates read-only or zero-trust security policies."""
    pass


class SQLSyntaxError(GuardrailError):
    """Raised when a SQL query has invalid syntax and cannot be parsed into an AST."""
    pass


# Dialect mapping from SQLAlchemy/user dialect names to sqlglot dialect names
DIALECT_MAPPING = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "psycopg2": "postgres",
    "mysql": "mysql",
    "pymysql": "mysql",
    "mariadb": "mysql",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "mssql": "tsql",
    "tsql": "tsql",
    "sqlserver": "tsql",
    "pyodbc": "tsql",
    "oracle": "oracle",
    "duckdb": "duckdb",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "redshift": "redshift",
}

# Disallowed AST expression types that could alter schema, data, or server configuration
DISALLOWED_AST_NODES: Tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Command,
    exp.Grant,
    exp.Revoke,
    exp.Merge,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Kill,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Copy,
    exp.LoadData,
    exp.Set,
    exp.Use,
    exp.Show,
    exp.Describe,
    exp.Into,
)


def normalize_dialect(dialect: Optional[str]) -> str:
    """Normalize common dialect identifiers to standard sqlglot dialect names."""
    if not dialect:
        return "postgres"
    clean = dialect.strip().lower().split("+")[0]
    return DIALECT_MAPPING.get(clean, clean)


def strip_markdown_sql(raw_sql: str) -> str:
    """Strip markdown code block fences (e.g. ```sql ... ```) and leading/trailing whitespace."""
    if not raw_sql:
        return ""

    cleaned = raw_sql.strip()

    # Match ```sql ... ``` or ``` ... ```
    match = re.search(r"```(?:sql)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if match:
        cleaned = match.group(1).strip()

    # Remove any trailing semicolons for uniform processing
    cleaned = re.sub(r";+\s*$", "", cleaned).strip()
    return cleaned


def is_read_only_ast(ast: exp.Expression) -> Tuple[bool, Optional[str]]:
    """Verify that an AST expression is strictly read-only.

    Checks:
    1. The root expression must be an exp.Select or exp.Union.
    2. No disallowed modification expressions (Insert, Update, Delete, Drop, Alter, etc.)
       exist anywhere in the expression tree (including CTEs and subqueries).

    Returns:
        (True, None) if safe.
        (False, error_reason) if a violation is detected.
    """
    # 1. Root statement check
    if not isinstance(ast, (exp.Select, exp.Union)):
        root_name = type(ast).__name__
        return (
            False,
            f"Non-read-only root statement detected: '{root_name}'. Only SELECT and UNION queries are permitted.",
        )

    # 2. Deep recursive check across entire AST tree for dangerous nodes
    for disallowed_cls in DISALLOWED_AST_NODES:
        found_nodes = list(ast.find_all(disallowed_cls))
        if found_nodes:
            op_name = disallowed_cls.__name__.upper()
            return (
                False,
                f"Disallowed destructive operation detected in query: '{op_name}'. "
                "All data-modifying statements, DDL, and administrative commands are blocked.",
            )

    return True, None


def apply_row_limit(ast: exp.Expression, max_rows: int) -> exp.Expression:
    """Ensure the outermost query enforces an upper bound on rows returned.

    - If no LIMIT clause exists, injects LIMIT max_rows.
    - If an existing LIMIT exceeds max_rows, caps it to max_rows.
    - If an existing LIMIT is within max_rows, preserves it.
    """
    limit_node = ast.args.get("limit")

    if limit_node is not None and limit_node.expression is not None:
        try:
            # Extract current limit integer value
            val = int(limit_node.expression.this)
            if val > max_rows:
                limit_node.set("expression", exp.Literal.number(max_rows))
            elif val <= 0:
                limit_node.set("expression", exp.Literal.number(max_rows))
        except (ValueError, TypeError, AttributeError):
            # If the limit is a complex expression or parameter, override with safe numeric literal
            limit_node.set("expression", exp.Literal.number(max_rows))
    else:
        # No limit present on outer query -> inject LIMIT clause
        ast = ast.limit(max_rows)

    return ast


def extract_referenced_tables(ast: exp.Expression) -> List[str]:
    """Extract unique table names referenced in the query AST."""
    tables: Set[str] = set()
    for table_node in ast.find_all(exp.Table):
        name = table_node.name
        if name and not name.startswith("__"):
            tables.add(name)
    return sorted(list(tables))


def validate_and_sanitize_sql(
    sql: str,
    dialect: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> str:
    """Parse, validate against security guardrails, apply row limiting, and transpile SQL.

    Args:
        sql: Raw SQL query text.
        dialect: Target database dialect name (e.g. 'postgres', 'mysql', 'sqlite', 'mssql').
        max_rows: Upper bound on rows to return (defaults to Settings.DEFAULT_ROW_LIMIT).

    Returns:
        The validated, row-limited, and transpiled SQL string ready for execution.

    Raises:
        SQLSyntaxError: If the SQL string has syntax errors and cannot be parsed.
        SQLSecurityError: If the SQL violates read-only AST guardrails or multi-statement rules.
    """
    cleaned_sql = strip_markdown_sql(sql)
    if not cleaned_sql:
        raise SQLSecurityError("SQL query is empty or contains only whitespace.")

    # Strip SQL line comments and block comments to check if query has actual statements
    no_comments = re.sub(r"--[^\n]*", "", cleaned_sql)
    no_comments = re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL).strip()
    if not no_comments:
        raise SQLSecurityError("SQL query contains only comments or whitespace.")

    settings = get_settings()
    target_dialect = normalize_dialect(dialect)
    row_limit = max_rows if max_rows is not None else settings.DEFAULT_ROW_LIMIT

    # 1. Multi-statement check
    try:
        parsed_statements = [
            stmt for stmt in sqlglot.parse(cleaned_sql, read=target_dialect) if stmt is not None
        ]
    except ParseError as exc:
        raise SQLSyntaxError(f"SQL syntax error parsing statement: {exc}") from exc
    except SqlglotError as exc:
        raise SQLSyntaxError(f"Failed to parse SQL statement: {exc}") from exc

    if len(parsed_statements) == 0:
        raise SQLSecurityError("No valid SQL statement found.")
    if len(parsed_statements) > 1:
        raise SQLSecurityError(
            f"Multi-statement execution rejected. Query contained {len(parsed_statements)} statements. "
            "Only a single read-only SELECT query may be executed at a time."
        )

    ast = parsed_statements[0]

    # 2. Strict read-only AST guardrail check
    is_safe, error_msg = is_read_only_ast(ast)
    if not is_safe:
        raise SQLSecurityError(error_msg or "SQL query violated read-only security policies.")

    # 3. Apply row limit
    ast = apply_row_limit(ast, max_rows=row_limit)

    # 4. Transpile cleanly to the target database dialect
    try:
        sanitized_sql = ast.sql(dialect=target_dialect)
        return sanitized_sql
    except Exception as exc:
        raise SQLSyntaxError(f"Failed to transpile validated SQL to dialect '{target_dialect}': {exc}") from exc
