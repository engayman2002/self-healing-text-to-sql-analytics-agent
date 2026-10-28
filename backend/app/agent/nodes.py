"""LangGraph nodes executing the Self-Healing SQL workflow."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional
from langchain_groq import ChatGroq

from app.agent.prompts import (
    ANALYTICS_SYNTHESIS_PROMPT,
    SELF_HEALING_PROMPT,
    SQL_GENERATION_PROMPT,
    TABLE_SELECTION_PROMPT,
)
from app.agent.state import (
    AgentState,
    AnalyticsSynthesisOutput,
    ChartConfig,
    SelfHealingOutput,
    SQLGenerationOutput,
    TableSelectionOutput,
)
from app.core.config import get_settings
from app.db.guardrails import (
    GuardrailError,
    SQLSecurityError,
    SQLSyntaxError,
    strip_markdown_sql,
    validate_and_sanitize_sql,
)
from app.db.introspector import (
    DatabaseSchema,
    get_cached_schema,
    introspect_database,
)
from app.db.manager import (
    ConnectionManager,
    DatabaseExecutionError,
    get_connection_manager,
)

logger = logging.getLogger(__name__)

# Optional override for unit testing without live Groq API keys
_LLM_OVERRIDE: Optional[Any] = None


def set_llm_override(llm: Optional[Any]) -> None:
    """Set a mock/custom LLM for unit tests."""
    global _LLM_OVERRIDE
    _LLM_OVERRIDE = llm


def is_groq_configured() -> bool:
    """Check if a valid, non-placeholder Groq API key is present or mock LLM is active."""
    if _LLM_OVERRIDE is not None:
        return True
    settings = get_settings()
    key = (settings.GROQ_API_KEY or "").strip()
    if not key or "your_" in key.lower() or key == "gsk_your_groq_api_key_here":
        return False
    return True


def get_llm(custom_llm: Optional[Any] = None) -> Any:
    """Instantiate ChatGroq or return configured mock/override."""
    if custom_llm is not None:
        return custom_llm
    if _LLM_OVERRIDE is not None:
        return _LLM_OVERRIDE

    settings = get_settings()
    return ChatGroq(
        model=settings.GROQ_MODEL,
        api_key=settings.GROQ_API_KEY,
        temperature=0.0,
    )


# ---------------------------------------------------------------------------
# Node 1: Schema Pruner Node
# ---------------------------------------------------------------------------

def schema_pruner_node(state: AgentState) -> Dict[str, Any]:
    """Inspects database schema and prunes table list if catalog exceeds 10 tables."""
    conn_id = state["connection_id"]
    conn_manager = get_connection_manager()

    # Resolve schema from engine
    engine = state.get("engine") or conn_manager.get_engine(conn_id)
    if engine is not None:
        schema = introspect_database(engine, connection_id=conn_id)
    else:
        cached = get_cached_schema(conn_id)
        if cached is None:
            raise ValueError(f"No active engine or cached schema found for connection '{conn_id}'.")
        schema = cached

    table_names = schema.get_table_names()

    # If <= 10 tables, bypass LLM call and pass all tables directly
    if len(table_names) <= 10:
        compact_ddl = schema.to_compact_ddl()
        return {
            "relevant_schema": compact_ddl,
            "dialect": schema.dialect,
            "status": "schema_selected",
        }

    # If > 10 tables, invoke LLM to select relevant tables
    table_summaries = []
    for t_name in table_names:
        tbl = schema.tables[t_name]
        col_list = ", ".join([f"{c.name} ({c.type})" for c in tbl.columns])
        table_summaries.append(f"Table: {t_name}\n  Columns: {col_list}")
    summaries_text = "\n\n".join(table_summaries)

    try:
        llm = get_llm().with_structured_output(TableSelectionOutput)
        chain = TABLE_SELECTION_PROMPT | llm
        selection_result: TableSelectionOutput = chain.invoke({
            "table_summaries": summaries_text,
            "question": state["question"],
        })
        relevant_tables = [t for t in selection_result.relevant_tables if t in schema.tables]
    except Exception as exc:
        logger.warning("Table selection LLM call failed (%s); falling back to all tables.", exc)
        relevant_tables = table_names

    # Fallback to all tables if LLM selected zero valid tables
    if not relevant_tables:
        relevant_tables = table_names

    compact_ddl = schema.to_compact_ddl(table_names=relevant_tables)
    return {
        "relevant_schema": compact_ddl,
        "dialect": schema.dialect,
        "status": "schema_selected",
    }


# ---------------------------------------------------------------------------
# Node 2: SQL Generator Node
# ---------------------------------------------------------------------------

def sql_generator_node(state: AgentState) -> Dict[str, Any]:
    """Generates initial SQL query based on pruned schema and user question."""
    try:
        llm = get_llm().with_structured_output(SQLGenerationOutput)
        chain = SQL_GENERATION_PROMPT | llm
        generation_output: SQLGenerationOutput = chain.invoke({
            "dialect": state["dialect"],
            "schema": state["relevant_schema"],
            "question": state["question"],
        })

        if not generation_output.is_answerable:
            clarification = generation_output.clarification_message or (
                "The requested tables or entities are not available in the provided database schema."
            )
            return {
                "is_answerable": False,
                "clarification_message": clarification,
                "generated_sql": None,
                "thought_process": generation_output.thought_process or clarification,
                "validation_error": None,
                "execution_error": None,
                "status": "unanswerable",
            }

        cleaned_sql = strip_markdown_sql(generation_output.sql_query or "")
        thought = generation_output.thought_process
        return {
            "is_answerable": True,
            "clarification_message": None,
            "generated_sql": cleaned_sql,
            "thought_process": thought,
            "validation_error": None,
            "execution_error": None,
            "status": "sql_generated",
        }
    except Exception as exc:
        err_str = str(exc)
        # Check if Groq failed with tool_use_failed and returned failed_generation
        failed_gen = None
        if "tool_use_failed" in err_str or "failed_generation" in err_str:
            import re
            m = re.search(r"['\"]failed_generation['\"]\s*:\s*['\"](.*?)['\"](?:\s*,\s*['\"]|\s*})", err_str, re.DOTALL)
            if m:
                failed_gen = m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
            elif hasattr(exc, "body") and isinstance(exc.body, dict):
                failed_gen = exc.body.get("error", {}).get("failed_generation")

        if failed_gen or "tool_use_failed" in err_str:
            clarification = failed_gen or "The requested entities or tables are absent from the database schema."
            logger.info("Groq tool_use_failed captured as polite schema clarification: %s", clarification)
            return {
                "is_answerable": False,
                "clarification_message": clarification,
                "generated_sql": None,
                "thought_process": clarification,
                "validation_error": None,
                "execution_error": None,
                "status": "unanswerable",
            }

        logger.warning("SQL generation LLM call failed: %s", exc)
        cleaned_sql = "-- Model generation error: unable to generate valid SQL"
        thought = f"LLM generation failed: {exc}"

        return {
            "is_answerable": True,
            "clarification_message": None,
            "generated_sql": cleaned_sql,
            "thought_process": thought,
            "validation_error": None,
            "execution_error": None,
            "status": "sql_generated",
        }


# ---------------------------------------------------------------------------
# Node 3: AST Validator Node
# ---------------------------------------------------------------------------

def ast_validator_node(state: AgentState) -> Dict[str, Any]:
    """Validates generated SQL against AST read-only guardrails and caps row limits."""
    raw_sql = state.get("generated_sql") or ""
    settings = get_settings()

    try:
        sanitized_sql = validate_and_sanitize_sql(
            sql=raw_sql,
            dialect=state["dialect"],
            max_rows=settings.DEFAULT_ROW_LIMIT,
        )
        # Passed AST validation
        return {
            "generated_sql": sanitized_sql,
            "validation_error": None,
            "status": "ast_validated",
        }
    except (SQLSecurityError, SQLSyntaxError, GuardrailError) as exc:
        err_msg = str(exc)
        logger.warning("AST guardrail violation on attempt %d: %s", state["retry_count"] + 1, err_msg)

        new_retry_count = state["retry_count"] + 1
        history = list(state.get("attempt_history") or [])
        history.append({
            "attempt": new_retry_count,
            "sql": raw_sql,
            "thought_process": state.get("thought_process"),
            "error": err_msg,
            "stage": "ast_validation",
        })

        return {
            "validation_error": err_msg,
            "retry_count": new_retry_count,
            "attempt_history": history,
            "status": "ast_validation_failed",
        }


# ---------------------------------------------------------------------------
# Node 4: SQL Executor Node
# ---------------------------------------------------------------------------

def sql_executor_node(state: AgentState) -> Dict[str, Any]:
    """Executes validated SQL against the database engine with statement timeouts."""
    conn_manager = get_connection_manager()
    sql_to_run = state["generated_sql"]
    conn_id = state["connection_id"]
    engine = state.get("engine")

    try:
        result = conn_manager.execute_read_only_query(
            connection_id=conn_id,
            sql=sql_to_run,
            engine=engine,
        )

        history = list(state.get("attempt_history") or [])
        history.append({
            "attempt": state["retry_count"] + 1,
            "sql": result.executed_sql,
            "thought_process": state.get("thought_process"),
            "error": None,
            "execution_time_ms": result.execution_time_ms,
            "row_count": result.row_count,
            "stage": "db_execution",
        })

        return {
            "query_results": result.rows,
            "column_names": result.columns,
            "execution_time_ms": result.execution_time_ms,
            "execution_error": None,
            "attempt_history": history,
            "status": "executed",
        }

    except DatabaseExecutionError as exc:
        diagnostic = exc.get_diagnostic_message()
        logger.warning("Database execution error on attempt %d: %s", state["retry_count"] + 1, diagnostic)

        new_retry_count = state["retry_count"] + 1
        history = list(state.get("attempt_history") or [])
        history.append({
            "attempt": new_retry_count,
            "sql": exc.failed_sql or sql_to_run,
            "thought_process": state.get("thought_process"),
            "error": diagnostic,
            "stage": "db_execution",
        })

        return {
            "execution_error": diagnostic,
            "retry_count": new_retry_count,
            "attempt_history": history,
            "status": "execution_failed",
        }
    except Exception as exc:
        err_msg = str(exc)
        logger.error("Unexpected execution failure on attempt %d: %s", state["retry_count"] + 1, err_msg)

        new_retry_count = state["retry_count"] + 1
        history = list(state.get("attempt_history") or [])
        history.append({
            "attempt": new_retry_count,
            "sql": sql_to_run,
            "thought_process": state.get("thought_process"),
            "error": err_msg,
            "stage": "db_execution",
        })

        return {
            "execution_error": err_msg,
            "retry_count": new_retry_count,
            "attempt_history": history,
            "status": "execution_failed",
        }


# ---------------------------------------------------------------------------
# Node 5: Self-Healer Node (The Core Recovery Engine)
# ---------------------------------------------------------------------------

def self_healer_node(state: AgentState) -> Dict[str, Any]:
    """Reflects on the schema and exact error traceback to produce corrected SQL."""
    error_message = state.get("validation_error") or state.get("execution_error") or "Unknown execution error"
    failed_sql = state.get("generated_sql") or ""

    try:
        llm = get_llm().with_structured_output(SelfHealingOutput)
        chain = SELF_HEALING_PROMPT | llm

        healing_result: SelfHealingOutput = chain.invoke({
            "dialect": state["dialect"],
            "schema": state["relevant_schema"],
            "question": state["question"],
            "failed_sql": failed_sql,
            "error_message": error_message,
            "attempt": state["retry_count"],
        })
        fixed_sql = strip_markdown_sql(healing_result.fixed_sql_query)
        diagnosis = healing_result.error_diagnosis
    except Exception as exc:
        logger.warning("Self-healer LLM call failed: %s", exc)
        fixed_sql = failed_sql
        diagnosis = f"Model reflection failed: {exc}"

    # Attach diagnosis to the most recent attempt in history
    history = list(state.get("attempt_history") or [])
    if history:
        history[-1]["diagnosis"] = diagnosis

    # CRITICAL: Explicitly clear validation_error and execution_error to avoid infinite loops!
    return {
        "generated_sql": fixed_sql,
        "healing_diagnosis": diagnosis,
        "validation_error": None,
        "execution_error": None,
        "attempt_history": history,
        "status": "self_healed",
    }


# ---------------------------------------------------------------------------
# Node 6: Analytics Synthesizer Node
# ---------------------------------------------------------------------------

def analytics_synthesizer_node(state: AgentState) -> Dict[str, Any]:
    """Synthesizes high-level business findings and builds dynamic chart configuration."""
    # Check for unanswerable / missing-table clarification
    if state.get("is_answerable") is False:
        clarification = state.get("clarification_message") or (
            "The requested entities or tables are not available in the database schema."
        )
        return {
            "final_summary": clarification,
            "chart_config": {
                "chart_type": "none",
                "title": "Schema Clarification",
                "x_axis_key": None,
                "y_axis_keys": [],
            },
            "query_results": [],
            "column_names": [],
            "status": "complete",
        }

    results = state.get("query_results") or []
    row_count = len(results)

    # Empty result set handling
    if row_count == 0:
        return {
            "final_summary": (
                "The query executed successfully, but returned **0 rows** matching your criteria. "
                "Consider broadening your filters or checking date ranges."
            ),
            "chart_config": {
                "chart_type": "none",
                "title": "No Matching Records",
                "x_axis_key": None,
                "y_axis_keys": [],
            },
            "status": "complete",
        }

    # Prepare preview of first 20 records for synthesis prompt
    preview_rows = results[:20]
    preview_json = json.dumps(preview_rows, default=str)

    try:
        llm = get_llm().with_structured_output(AnalyticsSynthesisOutput)
        chain = ANALYTICS_SYNTHESIS_PROMPT | llm

        synthesis: AnalyticsSynthesisOutput = chain.invoke({
            "question": state["question"],
            "sql": state.get("generated_sql") or "",
            "row_count": row_count,
            "data_preview": preview_json,
        })
        final_summary = synthesis.summary
        chart_config = synthesis.chart_config.model_dump()
    except Exception as exc:
        logger.warning("Analytics synthesis LLM call failed (%s); providing automated fallback summary.", exc)
        final_summary = f"Query executed successfully and returned {row_count} rows."
        first_row = results[0] if results else {}
        num_cols = [k for k, v in first_row.items() if isinstance(v, (int, float))]
        str_cols = [k for k, v in first_row.items() if isinstance(v, str)]
        chart_config = {
            "chart_type": "bar" if num_cols and str_cols else "none",
            "title": "Query Results",
            "x_axis_key": str_cols[0] if str_cols else None,
            "y_axis_keys": [num_cols[0]] if num_cols else [],
        }

    return {
        "final_summary": final_summary,
        "chart_config": chart_config,
        "status": "complete",
    }
