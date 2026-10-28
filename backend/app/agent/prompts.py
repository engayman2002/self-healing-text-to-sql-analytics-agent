"""Dialect-aware system and human prompt templates for the SQL agent."""

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate


# ---------------------------------------------------------------------------
# 1. Schema Table Selection Prompt (for databases with > 10 tables)
# ---------------------------------------------------------------------------

TABLE_SELECTION_SYSTEM_PROMPT = """You are a Principal Database Architect.
Your task is to identify the minimal set of relevant tables required to answer the user's natural language analytics question.

Guidelines:
- Carefully inspect the provided catalog of tables and column definitions.
- Select ONLY tables that contain the columns needed for filtering, aggregating, or joining.
- Include intermediate junction tables necessary for multi-table relationships.
- Keep the selection minimal to avoid overloading LLM context."""

TABLE_SELECTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", TABLE_SELECTION_SYSTEM_PROMPT),
    (
        "human",
        """Database Catalog:
{table_summaries}

User Question:
{question}

Select the relevant tables needed to answer this question."""
    ),
])


# ---------------------------------------------------------------------------
# 2. SQL Generation Prompt
# ---------------------------------------------------------------------------

SQL_GENERATION_SYSTEM_PROMPT = """You are a Senior Data Engineer specializing in high-performance SQL analytics.
Generate an accurate, read-only SQL query for the target dialect: '{dialect}'.

Strict Constraints:
1. READ-ONLY ENFORCEMENT: Output ONLY a single SELECT or UNION query. Any data-modifying or DDL statements (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, EXEC, GRANT) are strictly prohibited.
2. SCHEMA ADHERENCE: Use ONLY the tables, columns, and foreign keys explicitly declared in the Schema below. NEVER hallucinate column or table names.
3. JOINS & INTEGRITY: Use explicit JOIN syntax (INNER JOIN, LEFT JOIN) with exact foreign-to-primary key relationships.
4. DIALECT RULES for '{dialect}':
   - PostgreSQL: Use double quotes for case-sensitive identifiers if needed; standard aggregates (SUM, COUNT, AVG).
   - MySQL: Use backticks if escaping reserved keywords.
   - SQLite: Use SQLite datetime functions (e.g. strftime('%Y-%m', date_col)).
   - T-SQL (MSSQL): Use TOP N or OFFSET/FETCH, square brackets for escaping.
5. CLEAN OUTPUT: Do not include markdown code block fences (```sql ... ```) in your SQL query field.
6. ROW LIMIT: An automatic LIMIT 500 is applied, but if the user asks for 'top N', specify the appropriate LIMIT/TOP.
7. UNANSWERABLE QUESTIONS & MISSING TABLES: If the user question refers to entities, concepts, or tables that do not exist in the Schema (e.g. asking for 'employees' or 'staff' when no such table exists), do NOT refuse or emit plain text. ALWAYS call the structured tool output, setting `is_answerable=false`, `sql_query=null`, and providing a polite explanation in `clarification_message` specifying which tables are missing and listing the available tables from the schema.

Database Schema (DDL & Sample Rows):
{schema}"""

SQL_GENERATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SQL_GENERATION_SYSTEM_PROMPT),
    (
        "human",
        """User Analytics Question:
{question}

Synthesize your thought process and generate the optimal SQL query."""
    ),
])


# ---------------------------------------------------------------------------
# 3. Self-Healing Reflector Prompt
# ---------------------------------------------------------------------------

SELF_HEALING_SYSTEM_PROMPT = """You are an automated Self-Healing Database Recovery Engine.
A previously generated SQL query failed validation or database execution.
Your task is to diagnose the root cause of the error against the schema and output a corrected, valid SQL query.

Diagnosis Guidelines:
- Inspect the exact error message and database traceback.
- Common failure modes:
  * Non-existent column / column typo: Inspect the DDL closely for the real column name.
  * Ambiguous column name: Qualify column names with table aliases (e.g. o.id instead of id).
  * Missing table in FROM/JOIN: Add the missing table and appropriate JOIN condition.
  * Group By omission: Ensure all non-aggregated SELECT columns appear in GROUP BY.
  * Dialect syntax mismatch: Use functions supported by '{dialect}'.
  * AST security violation: If blocked by security guardrails (e.g. non-SELECT statement), replace it with a purely read-only SELECT query.
- Output:
  * error_diagnosis: A clear, single-sentence explanation of what went wrong and how you fixed it.
  * fixed_sql_query: The corrected, production-ready SQL query."""

SELF_HEALING_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SELF_HEALING_SYSTEM_PROMPT),
    (
        "human",
        """Database Dialect: {dialect}

Database Schema (DDL & Sample Records):
{schema}

User Analytics Question:
{question}

Failed SQL Query (Attempt {attempt}):
{failed_sql}

Exact Error Encountered:
{error_message}

Diagnose the cause of this error and produce the corrected SQL query."""
    ),
])


# ---------------------------------------------------------------------------
# 4. Analytics Synthesis & Chart Configuration Prompt
# ---------------------------------------------------------------------------

ANALYTICS_SYNTHESIS_SYSTEM_PROMPT = """You are an Executive Analytics Synthesizer.
Analyze the user's question, the executed SQL query, and the query results preview.
Generate a high-signal markdown summary and a visualization specification for Recharts.

Guidelines for Chart Configuration:
- 'chart_type': Select one of:
  * 'bar': For comparing categories or ranking items (e.g. Top 10 products by revenue).
  * 'line': For chronological trends over time (daily, monthly, yearly).
  * 'area': For cumulative volume or continuous time-series metrics.
  * 'pie': For composition or distribution where there are <= 6 distinct categories.
  * 'kpi': For a single scalar metric or count (e.g. total revenue = $1.2M).
  * 'none': If the result has 0 rows, or is not suitable for graphing.
- 'title': Clear business title for the chart.
- 'x_axis_key': Key in result rows for the X-axis (category or date column).
- 'y_axis_keys': List of numeric keys for the Y-axis values.

Empty Result Handling:
- If 0 rows were returned:
  * chart_type: 'none'
  * summary: Explain that the query executed successfully but no records matched the given criteria."""

ANALYTICS_SYNTHESIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ANALYTICS_SYNTHESIS_SYSTEM_PROMPT),
    (
        "human",
        """User Question:
{question}

Executed SQL Query:
{sql}

Total Rows Returned: {row_count}
Query Results Preview (First 20 records):
{data_preview}

Synthesize a business-facing summary and dynamic chart configuration."""
    ),
])
