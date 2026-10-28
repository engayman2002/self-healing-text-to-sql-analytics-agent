import asyncio
from datetime import date, datetime, time
from decimal import Decimal
import json
import logging
import math
from typing import Any, AsyncGenerator, Dict, List, Optional
import uuid

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agent.nodes import (
    analytics_synthesizer_node,
    ast_validator_node,
    is_groq_configured,
    schema_pruner_node,
    self_healer_node,
    sql_executor_node,
    sql_generator_node,
)
from app.agent.state import AgentState
from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strict RFC-8259 JSON Sanitizer for SSE Streaming Payloads
# ---------------------------------------------------------------------------

def sanitize_for_json(obj: Any) -> Any:
    """Recursively convert custom types and sanitize NaN/Infinity to None for strict RFC-8259 compliance."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, Decimal):
        if obj.is_nan() or obj.is_infinite():
            return None
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"
    if isinstance(obj, BaseModel):
        return sanitize_for_json(obj.model_dump())
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(item) for item in obj]
    if isinstance(obj, Exception):
        return str(obj)
    return str(obj)


def safe_json_dumps(payload: Any) -> str:
    """Serialize dictionary payload to strictly compliant RFC-8259 JSON without NaN/Infinity crashing browsers."""
    sanitized = sanitize_for_json(payload)
    return json.dumps(sanitized, allow_nan=False)


# ---------------------------------------------------------------------------
# Conditional Edge Routers
# ---------------------------------------------------------------------------

def route_after_sql_generation(state: AgentState) -> str:
    """Route after SQL generation: if unanswerable, skip execution and go directly to analytics synthesizer."""
    if state.get("is_answerable") is False:
        return "analytics_synthesizer"
    return "ast_validator"


def route_after_ast_validation(state: AgentState) -> str:
    """Route after AST validation: proceed to execution if valid; heal if invalid and budget remains."""
    if state.get("validation_error") is None:
        return "sql_executor"

    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if retry_count < max_retries:
        return "self_healer"

    # Retries exhausted
    return END


def route_after_sql_execution(state: AgentState) -> str:
    """Route after DB execution: synthesize if succeeded; heal if failed and budget remains."""
    if state.get("execution_error") is None:
        return "analytics_synthesizer"

    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if retry_count < max_retries:
        return "self_healer"

    # Retries exhausted
    return END


# ---------------------------------------------------------------------------
# State Graph Construction
# ---------------------------------------------------------------------------

def build_sql_agent_graph():
    """Construct and compile the cyclical self-healing LangGraph workflow."""
    workflow = StateGraph(AgentState)

    # 1. Register Graph Nodes
    workflow.add_node("schema_pruner", schema_pruner_node)
    workflow.add_node("sql_generator", sql_generator_node)
    workflow.add_node("ast_validator", ast_validator_node)
    workflow.add_node("sql_executor", sql_executor_node)
    workflow.add_node("self_healer", self_healer_node)
    workflow.add_node("analytics_synthesizer", analytics_synthesizer_node)

    # 2. Add Linear Edges
    workflow.add_edge(START, "schema_pruner")
    workflow.add_edge("schema_pruner", "sql_generator")

    # 3. Add Conditional Routing Edges
    workflow.add_conditional_edges(
        "sql_generator",
        route_after_sql_generation,
        {
            "ast_validator": "ast_validator",
            "analytics_synthesizer": "analytics_synthesizer",
        },
    )

    workflow.add_conditional_edges(
        "ast_validator",
        route_after_ast_validation,
        {
            "sql_executor": "sql_executor",
            "self_healer": "self_healer",
            END: END,
        },
    )

    workflow.add_conditional_edges(
        "sql_executor",
        route_after_sql_execution,
        {
            "analytics_synthesizer": "analytics_synthesizer",
            "self_healer": "self_healer",
            END: END,
        },
    )

    # 4. Self-Healing Cycle: Must return to AST validation before re-execution
    workflow.add_edge("self_healer", "ast_validator")

    # 5. Terminal Edge
    workflow.add_edge("analytics_synthesizer", END)

    return workflow.compile()


# Compiled singleton graph instance
sql_agent_graph = build_sql_agent_graph()


# ---------------------------------------------------------------------------
# SSE Streaming Event Generator
# ---------------------------------------------------------------------------

async def stream_agent_events(
    connection_id: str,
    question: str,
    max_retries: Optional[int] = None,
    engine: Optional[Any] = None,
) -> AsyncGenerator[str, None]:
    """Execute the compiled self-healing agent and yield Server-Sent Events (SSE).

    Event types emitted:
    1. 'status': Real-time step progression updates.
    2. 'sql_attempt': Emitted on each SQL generation/healed attempt.
    3. 'self_healing': Emitted when an error is caught and diagnosed.
    4. 'complete': Emitted on final successful synthesis with data and chart config.
    5. 'error': Emitted if max retries are exhausted or a fatal exception occurs.
    """
    settings = get_settings()
    configured_max_retries = max_retries if max_retries is not None else settings.MAX_RETRIES

    initial_state: AgentState = {
        "question": question,
        "connection_id": connection_id,
        "dialect": "postgres",
        "relevant_schema": "",
        "is_answerable": None,
        "clarification_message": None,
        "generated_sql": None,
        "thought_process": None,
        "validation_error": None,
        "execution_error": None,
        "healing_diagnosis": None,
        "retry_count": 0,
        "max_retries": configured_max_retries,
        "attempt_history": [],
        "query_results": None,
        "column_names": None,
        "final_summary": None,
        "chart_config": None,
        "execution_time_ms": None,
        "status": "initializing",
    }

    # Pass optional engine if supplied (e.g. in-memory sqlite test runs)
    if engine is not None:
        initial_state["engine"] = engine  # type: ignore

    # Verify LLM configuration before initiating pipeline
    if not is_groq_configured():
        yield f"data: {safe_json_dumps({
            'event': 'error',
            'message': 'GROQ_API_KEY is not configured or contains placeholder in backend/.env. Please configure a valid Groq Cloud API key (https://console.groq.com) to enable AI inference.',
            'attempts': 0,
            'healing_trace': [],
        })}\n\n"
        return

    # Send initial status
    yield f"data: {safe_json_dumps({'event': 'status', 'step': 'schema_selection', 'message': 'Introspecting database schema...'})}\n\n"

    last_seen_state: Dict[str, Any] = dict(initial_state)
    emitted_attempts = set()

    try:
        # Stream updates node-by-node
        for chunk in sql_agent_graph.stream(initial_state, stream_mode="updates"):
            for node_name, updates in chunk.items():
                last_seen_state.update(updates)

                if node_name == "schema_pruner":
                    dialect = last_seen_state.get("dialect", "relational")
                    yield f"data: {safe_json_dumps({'event': 'status', 'step': 'schema_selection', 'message': f'Extracted schema metadata for {dialect} database.'})}\n\n"

                elif node_name == "sql_generator":
                    if last_seen_state.get("is_answerable") is False:
                        clarification = (
                            last_seen_state.get("clarification_message")
                            or "The requested tables/entities are absent from the database schema."
                        )
                        yield f"data: {safe_json_dumps({'event': 'status', 'step': 'sql_generation', 'message': f'Schema Clarification: {clarification}'})}\n\n"
                    else:
                        attempt_num = 1
                        sql = last_seen_state.get("generated_sql")
                        thought = last_seen_state.get("thought_process")
                        emitted_attempts.add(attempt_num)
                        yield f"data: {safe_json_dumps({'event': 'status', 'step': 'sql_generation', 'message': 'Synthesized initial SQL query.'})}\n\n"
                        yield f"data: {safe_json_dumps({'event': 'sql_attempt', 'attempt': attempt_num, 'sql': sql, 'thought_process': thought})}\n\n"

                elif node_name == "ast_validator":
                    val_err = last_seen_state.get("validation_error")
                    if val_err:
                        yield f"data: {safe_json_dumps({'event': 'status', 'step': 'ast_validation', 'message': f'AST Guardrail blocked statement: {val_err}'})}\n\n"
                    else:
                        yield f"data: {safe_json_dumps({'event': 'status', 'step': 'ast_validation', 'message': 'SQL query verified by zero-trust AST guardrails.'})}\n\n"

                elif node_name == "sql_executor":
                    exec_err = last_seen_state.get("execution_error")
                    if exec_err:
                        yield f"data: {safe_json_dumps({'event': 'status', 'step': 'execution', 'message': f'Execution error: {exec_err}'})}\n\n"
                    else:
                        latency = last_seen_state.get("execution_time_ms", 0)
                        row_cnt = len(last_seen_state.get("query_results") or [])
                        yield f"data: {safe_json_dumps({'event': 'status', 'step': 'execution', 'message': f'Query executed successfully in {latency}ms ({row_cnt} rows).'})}\n\n"

                elif node_name == "self_healer":
                    attempt_num = last_seen_state.get("retry_count", 1) + 1
                    err_msg = (
                        last_seen_state.get("validation_error")
                        or last_seen_state.get("execution_error")
                        or "Query error"
                    )
                    diag = last_seen_state.get("healing_diagnosis") or "Analyzing error traceback..."
                    healed_sql = last_seen_state.get("generated_sql")

                    # Emit self_healing diagnosis event
                    yield f"data: {safe_json_dumps({'event': 'self_healing', 'attempt': attempt_num - 1, 'error': err_msg, 'diagnosis': diag})}\n\n"
                    # Emit new healed sql attempt event
                    yield f"data: {safe_json_dumps({'event': 'sql_attempt', 'attempt': attempt_num, 'sql': healed_sql, 'thought_process': diag})}\n\n"

                elif node_name == "analytics_synthesizer":
                    yield f"data: {safe_json_dumps({'event': 'status', 'step': 'analytics_synthesis', 'message': 'Synthesizing business insights and chart visualization...'})}\n\n"

        # Check final outcome
        if last_seen_state.get("query_results") is not None and last_seen_state.get("final_summary") is not None:
            # Successful completion
            results = last_seen_state.get("query_results") or []
            yield f"data: {safe_json_dumps({\
                'event': 'complete',\
                'sql': last_seen_state.get('generated_sql'),\
                'data': results,\
                'columns': last_seen_state.get('column_names') or [],\
                'row_count': len(results),\
                'attempts': last_seen_state.get('retry_count', 0) + 1,\
                'healing_trace': last_seen_state.get('attempt_history') or [],\
                'summary': last_seen_state.get('final_summary'),\
                'chart_config': last_seen_state.get('chart_config'),\
                'execution_time_ms': last_seen_state.get('execution_time_ms', 0),\
            })}\n\n"
        else:
            # Terminated with exhausted retries or unresolved error
            final_err = (
                last_seen_state.get("execution_error")
                or last_seen_state.get("validation_error")
                or "Self-healing attempts exhausted without reaching a valid query."
            )
            yield f"data: {safe_json_dumps({\
                'event': 'error',\
                'message': final_err,\
                'attempts': last_seen_state.get('retry_count', 0),\
                'healing_trace': last_seen_state.get('attempt_history') or [],\
            })}\n\n"

    except (asyncio.CancelledError, GeneratorExit):
        logger.info("SSE client disconnected from stream for connection '%s'. Exiting generator cleanly.", connection_id)
        return
    except Exception as exc:
        logger.error("Unhandled fatal exception in agent streaming: %s", exc, exc_info=True)
        yield f"data: {safe_json_dumps({\
            'event': 'error',\
            'message': f'Fatal agent execution error: {exc}',\
            'attempts': last_seen_state.get('retry_count', 0),\
            'healing_trace': last_seen_state.get('attempt_history') or [],\
        })}\n\n"


# ---------------------------------------------------------------------------
# Programmatic Non-Streaming Invocation Helper
# ---------------------------------------------------------------------------

async def run_agent_workflow(
    connection_id: str,
    question: str,
    max_retries: Optional[int] = None,
    engine: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute agent workflow non-streaming and return full accumulated state dict."""
    settings = get_settings()
    configured_max_retries = max_retries if max_retries is not None else settings.MAX_RETRIES

    initial_state: AgentState = {
        "question": question,
        "connection_id": connection_id,
        "dialect": "postgres",
        "relevant_schema": "",
        "is_answerable": None,
        "clarification_message": None,
        "generated_sql": None,
        "thought_process": None,
        "validation_error": None,
        "execution_error": None,
        "healing_diagnosis": None,
        "retry_count": 0,
        "max_retries": configured_max_retries,
        "attempt_history": [],
        "query_results": None,
        "column_names": None,
        "final_summary": None,
        "chart_config": None,
        "execution_time_ms": None,
        "status": "initializing",
    }

    if engine is not None:
        initial_state["engine"] = engine  # type: ignore

    if not is_groq_configured():
        initial_state["execution_error"] = (
            "GROQ_API_KEY is not configured or contains placeholder in backend/.env. "
            "Please configure a valid Groq Cloud API key to enable AI inference."
        )
        initial_state["status"] = "failed"
        return initial_state

    final_state = sql_agent_graph.invoke(initial_state)
    return final_state
