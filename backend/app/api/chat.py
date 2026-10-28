"""Chat and live SSE streaming analytics endpoints."""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.agent.graph import run_agent_workflow, stream_agent_events
from app.api.connections import connection_store
from app.db.manager import get_connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat & Streaming Analytics"])


# ---------------------------------------------------------------------------
# Request and Response Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Payload to trigger the Self-Healing Text-to-SQL Analytics Agent."""
    connection_id: str = Field(min_length=1, max_length=100, description="Target database connection identifier")
    question: str = Field(min_length=1, max_length=4000, description="Natural language analytics question to ask the database")
    max_retries: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum bounded self-healing recovery attempts",
    )

    @field_validator("question")
    @classmethod
    def validate_question_not_whitespace(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Question cannot be empty or contain only whitespace.")
        if len(clean) > 4000:
            raise ValueError("Question exceeds maximum allowed length of 4000 characters.")
        return clean

    @field_validator("connection_id")
    @classmethod
    def validate_connection_id_not_whitespace(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Connection ID cannot be empty or contain only whitespace.")
        return clean


class ChatQueryResponse(BaseModel):
    """Structured response for non-streaming programmatic query endpoint."""
    success: bool
    sql: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    columns: Optional[List[str]] = None
    row_count: int = 0
    attempts: int = 1
    healing_trace: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Optional[str] = None
    chart_config: Optional[Dict[str, Any]] = None
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper: Validate and Prepare Engine
# ---------------------------------------------------------------------------

def ensure_connection_active(connection_id: str) -> None:
    """Verify connection exists and ensure engine pool is initialized."""
    manager = get_connection_manager()
    if manager.get_engine(connection_id) is not None:
        return

    record = connection_store.get(connection_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found. Please register the database connection first.",
        )

    # Re-initialize engine from encrypted credentials
    manager.get_or_create_engine_from_encrypted(
        connection_id=connection_id,
        encrypted_uri=record["encrypted_uri"],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/stream")
def stream_chat_endpoint(payload: ChatRequest):
    """Execute Self-Healing SQL Agent and stream real-time steps and results via SSE."""
    ensure_connection_active(payload.connection_id)

    event_generator = stream_agent_events(
        connection_id=payload.connection_id,
        question=payload.question,
        max_retries=payload.max_retries,
    )

    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )


@router.post("/query", response_model=ChatQueryResponse)
async def query_chat_endpoint(payload: ChatRequest):
    """Execute Self-Healing SQL Agent non-streaming for programmatic consumption and testing."""
    ensure_connection_active(payload.connection_id)

    final_state = await run_agent_workflow(
        connection_id=payload.connection_id,
        question=payload.question,
        max_retries=payload.max_retries,
    )

    results = final_state.get("query_results")
    if results is not None and final_state.get("final_summary") is not None:
        return ChatQueryResponse(
            success=True,
            sql=final_state.get("generated_sql"),
            data=results,
            columns=final_state.get("column_names") or [],
            row_count=len(results),
            attempts=final_state.get("retry_count", 0) + 1,
            healing_trace=final_state.get("attempt_history") or [],
            summary=final_state.get("final_summary"),
            chart_config=final_state.get("chart_config"),
            execution_time_ms=final_state.get("execution_time_ms"),
        )

    error_msg = (
        final_state.get("execution_error")
        or final_state.get("validation_error")
        or "Self-healing attempts exhausted without producing a valid query."
    )
    return ChatQueryResponse(
        success=False,
        sql=final_state.get("generated_sql"),
        attempts=final_state.get("retry_count", 0),
        healing_trace=final_state.get("attempt_history") or [],
        error=error_msg,
    )
