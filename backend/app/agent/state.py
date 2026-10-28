"""Agent state definitions, structured output schemas, and attempt tracking models."""

from typing import Any, Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic v2 Structured Output Schemas (for ChatGroq .with_structured_output)
# ---------------------------------------------------------------------------

class TableSelectionOutput(BaseModel):
    """Schema pruning output to select only relevant database tables."""
    relevant_tables: List[str] = Field(
        description="List of table names required to construct the SQL query",
    )
    reasoning: str = Field(
        description="Concise rationale for why these specific tables were selected",
    )


class SQLGenerationOutput(BaseModel):
    """Structured LLM output for SQL query generation."""
    is_answerable: bool = Field(
        default=True,
        description="Set to False ONLY if the requested entities/tables are completely absent from the schema and cannot be answered.",
    )
    clarification_message: Optional[str] = Field(
        default=None,
        description="If is_answerable is False, explain politely which tables are missing and list the available tables in the schema.",
    )
    thought_process: str = Field(
        default="",
        description="Step-by-step reasoning explaining column choices, joins, aggregations, and filters",
    )
    sql_query: Optional[str] = Field(
        default=None,
        description="Clean, dialect-specific read-only SQL query without markdown code blocks, or None if is_answerable is False",
    )


class SelfHealingOutput(BaseModel):
    """Structured LLM output for reflection and self-healing error recovery."""
    error_diagnosis: str = Field(
        description="One-sentence diagnosis explaining why the previous SQL attempt failed",
    )
    fixed_sql_query: str = Field(
        description="The corrected read-only SQL query addressing the error",
    )


class ChartConfig(BaseModel):
    """Frontend visualization specification for dynamic rendering in Recharts."""
    chart_type: Literal["bar", "line", "area", "pie", "kpi", "none"] = Field(
        description="Best suited chart type for visualizing the query results",
    )
    title: str = Field(
        description="Clear, business-relevant title for the visualization",
    )
    x_axis_key: Optional[str] = Field(
        default=None,
        description="Column key to map to the X-axis or categorical dimension",
    )
    y_axis_keys: List[str] = Field(
        default_factory=list,
        description="One or more numeric column keys to map to the Y-axis metrics",
    )


class AnalyticsSynthesisOutput(BaseModel):
    """Structured response containing analytical insights and visualization config."""
    summary: str = Field(
        description="Concise markdown explanation highlighting key business takeaways from the data",
    )
    chart_config: ChartConfig = Field(
        description="Chart configuration specification for rendering",
    )


class AttemptRecord(BaseModel):
    """Historical trace record of an individual SQL generation attempt."""
    attempt: int = Field(description="Attempt sequence number (1, 2, ...)")
    sql: str = Field(description="Generated SQL query for this attempt")
    thought_process: Optional[str] = Field(default=None, description="Model thought process")
    error: Optional[str] = Field(default=None, description="Error message if validation or execution failed")
    diagnosis: Optional[str] = Field(default=None, description="Self-healing diagnosis if recovered")
    execution_time_ms: Optional[float] = Field(default=None, description="Query execution latency in milliseconds")


# ---------------------------------------------------------------------------
# LangGraph AgentState TypedDict
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """Cyclical graph state propagated across all workflow nodes."""
    question: str
    connection_id: str
    dialect: str
    relevant_schema: str
    is_answerable: Optional[bool]
    clarification_message: Optional[str]
    generated_sql: Optional[str]
    thought_process: Optional[str]
    validation_error: Optional[str]
    execution_error: Optional[str]
    healing_diagnosis: Optional[str]
    retry_count: int
    max_retries: int
    attempt_history: List[Dict[str, Any]]
    query_results: Optional[List[Dict[str, Any]]]
    column_names: Optional[List[str]]
    final_summary: Optional[str]
    chart_config: Optional[Dict[str, Any]]
    execution_time_ms: Optional[float]
    status: str
