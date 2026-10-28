"""Unit tests for LangGraph state machine, self-healing loops, and AST guardrail recovery."""

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool
from langchain_core.runnables import RunnableLambda

from app.agent.graph import run_agent_workflow
from app.agent.nodes import set_llm_override
from app.agent.state import (
    AnalyticsSynthesisOutput,
    ChartConfig,
    SelfHealingOutput,
    SQLGenerationOutput,
    TableSelectionOutput,
)
from app.db.introspector import introspect_database
from app.db.manager import get_connection_manager


class MockStructuredLLM:
    """Mock LLM that returns pre-configured structured outputs based on requested schema class."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.call_counts = {k: 0 for k in responses}

    def with_structured_output(self, schema_cls):
        def _invoke(inputs):
            res_list = self.responses.get(schema_cls, [])
            if not res_list:
                raise ValueError(f"No mock response configured for {schema_cls}")
            idx = self.call_counts[schema_cls]
            self.call_counts[schema_cls] = idx + 1
            if idx < len(res_list):
                return res_list[idx]
            return res_list[-1]

        return RunnableLambda(_invoke)


@pytest.fixture
def analytics_test_db():
    """Create a populated in-memory SQLite database for testing."""
    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"))
        conn.execute(
            sa.text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    total DECIMAL(10, 2) NOT NULL,
                    FOREIGN KEY (customer_id) REFERENCES customers(id)
                );
                """
            )
        )
        conn.execute(sa.text("INSERT INTO customers VALUES (1, 'Acme Corp'), (2, 'Globex Inc');"))
        conn.execute(
            sa.text(
                """
                INSERT INTO orders VALUES
                (101, 1, 500.00),
                (102, 1, 1500.00),
                (103, 2, 750.00);
                """
            )
        )

    conn_id = "test_analytics_db"
    manager = get_connection_manager()
    manager.register_engine(conn_id, "sqlite:///:memory:")
    # Seed the engine directly into manager
    manager._engines[conn_id] = engine

    # Prime cache
    introspect_database(engine, connection_id=conn_id, force_refresh=True)

    yield engine, conn_id

    set_llm_override(None)
    manager.close_engine(conn_id)
    engine.dispose()


@pytest.mark.asyncio
async def test_first_try_success(analytics_test_db):
    """Test Case 1: Agent generates a valid SQL query on Attempt 1 and completes successfully."""
    engine, conn_id = analytics_test_db

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Join customers and orders on customer_id, group by name and sum total.",
                sql_query="SELECT c.name, SUM(o.total) AS total_spent FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Acme Corp spent $2,000 and Globex spent $750.",
                chart_config=ChartConfig(
                    chart_type="bar",
                    title="Customer Total Spend",
                    x_axis_key="name",
                    y_axis_keys=["total_spent"],
                ),
            )
        ],
    })
    set_llm_override(mock_llm)

    result = await run_agent_workflow(
        connection_id=conn_id,
        question="Show total spend per customer",
        engine=engine,
    )

    assert result["retry_count"] == 0
    assert result["validation_error"] is None
    assert result["execution_error"] is None
    assert len(result["query_results"]) == 2
    assert result["query_results"][0]["name"] == "Acme Corp"
    assert result["query_results"][0]["total_spent"] == 2000.0
    assert result["chart_config"]["chart_type"] == "bar"
    assert result["status"] == "complete"


@pytest.mark.asyncio
async def test_self_healing_recovery_loop(analytics_test_db):
    """Test Case 2: Agent generates a broken column query on Attempt 1, heals on Attempt 2, and succeeds."""
    engine, conn_id = analytics_test_db

    # Attempt 1: has hallucinated column 'cust_id' instead of 'customer_id'
    # Attempt 2: self-healer corrects to 'customer_id'
    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Joining orders on cust_id.",
                sql_query="SELECT c.name, SUM(o.total) AS total_spent FROM customers c JOIN orders o ON c.id = o.cust_id GROUP BY c.name",
            )
        ],
        SelfHealingOutput: [
            SelfHealingOutput(
                error_diagnosis="Column 'cust_id' does not exist in orders; the correct column is 'customer_id'.",
                fixed_sql_query="SELECT c.name, SUM(o.total) AS total_spent FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Self-healed query executed successfully. Acme Corp is top spender.",
                chart_config=ChartConfig(
                    chart_type="bar",
                    title="Top Spenders",
                    x_axis_key="name",
                    y_axis_keys=["total_spent"],
                ),
            )
        ],
    })
    set_llm_override(mock_llm)

    result = await run_agent_workflow(
        connection_id=conn_id,
        question="Show total spend per customer",
        max_retries=3,
        engine=engine,
    )

    # Verified self-healing occurred exactly once
    assert result["retry_count"] == 1
    assert result["validation_error"] is None
    assert result["execution_error"] is None
    assert result["healing_diagnosis"] is not None
    assert "customer_id" in result["healing_diagnosis"]
    assert len(result["query_results"]) == 2
    assert len(result["attempt_history"]) >= 2
    # Check attempt history recorded the failure
    assert result["attempt_history"][0]["error"] is not None
    assert "no such column: o.cust_id" in result["attempt_history"][0]["error"].lower()


@pytest.mark.asyncio
async def test_ast_guardrail_self_healing(analytics_test_db):
    """Test Case 3: Attempt 1 produces a forbidden DROP statement, blocked by AST guardrail, healed on Attempt 2."""
    engine, conn_id = analytics_test_db

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Destructive attempt.",
                sql_query="DROP TABLE customers",
            )
        ],
        SelfHealingOutput: [
            SelfHealingOutput(
                error_diagnosis="DROP TABLE is blocked by AST read-only guardrails. Replaced with safe SELECT query.",
                fixed_sql_query="SELECT * FROM customers",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Retrieved customers successfully.",
                chart_config=ChartConfig(
                    chart_type="none",
                    title="Customer List",
                    x_axis_key="id",
                    y_axis_keys=[],
                ),
            )
        ],
    })
    set_llm_override(mock_llm)

    result = await run_agent_workflow(
        connection_id=conn_id,
        question="List all customers",
        max_retries=3,
        engine=engine,
    )

    assert result["retry_count"] == 1
    assert result["validation_error"] is None
    assert result["status"] == "complete"
    assert len(result["query_results"]) == 2
    # Verify table was never dropped!
    with engine.connect() as conn:
        res = conn.execute(sa.text("SELECT COUNT(*) FROM customers")).scalar()
        assert res == 2


@pytest.mark.asyncio
async def test_max_retries_exhausted_terminates_gracefully(analytics_test_db):
    """Test Case 4: Persistent errors exhaust retry budget and terminate cleanly without infinite loop."""
    engine, conn_id = analytics_test_db

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Bad query.",
                sql_query="SELECT nonexistent_column FROM orders",
            )
        ],
        SelfHealingOutput: [
            SelfHealingOutput(
                error_diagnosis="Still invalid query.",
                fixed_sql_query="SELECT still_nonexistent FROM orders",
            )
        ],
    })
    set_llm_override(mock_llm)

    result = await run_agent_workflow(
        connection_id=conn_id,
        question="Get something broken",
        max_retries=2,
        engine=engine,
    )

    # Capped at max_retries without running forever
    assert result["retry_count"] >= 2
    assert result["query_results"] is None
    assert result["execution_error"] is not None


@pytest.mark.asyncio
async def test_unanswerable_missing_table_question_bypasses_sql(analytics_test_db):
    """Test Bug 2: Missing table questions set is_answerable=False and return polite clarification without running SQL."""
    engine, conn_id = analytics_test_db

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                is_answerable=False,
                clarification_message="The database schema contains 'customers' and 'orders', but does not have an 'employees' table.",
                thought_process="Requested entity 'employees' is not present in schema.",
                sql_query=None,
            )
        ],
    })
    set_llm_override(mock_llm)

    result = await run_agent_workflow(
        connection_id=conn_id,
        question="Count all employees",
        max_retries=3,
        engine=engine,
    )

    assert result["is_answerable"] is False
    assert result["status"] == "complete"
    assert result["generated_sql"] is None
    assert result["query_results"] == []
    assert "employees" in result["final_summary"]
    assert result["chart_config"]["chart_type"] == "none"


@pytest.mark.asyncio
async def test_groq_tool_use_failed_handled_cleanly(analytics_test_db):
    """Test Bug 2: When Groq raises 400 tool_use_failed with failed_generation, it is caught as unanswerable."""
    engine, conn_id = analytics_test_db

    class FailingGroqLLM:
        def with_structured_output(self, schema_cls):
            def _invoke(inputs):
                if schema_cls == SQLGenerationOutput:
                    raise Exception(
                        "Error code: 400 - {'error': {'message': 'Tool choice is required, but model did not call a tool', "
                        "'code': 'tool_use_failed', 'failed_generation': 'I am unable to answer because there is no employees table in the schema.'}}"
                    )
                raise ValueError("Unexpected schema")
            return RunnableLambda(_invoke)

    set_llm_override(FailingGroqLLM())

    result = await run_agent_workflow(
        connection_id=conn_id,
        question="How many employees work at the company?",
        max_retries=3,
        engine=engine,
    )

    assert result["is_answerable"] is False
    assert result["status"] == "complete"
    assert result["generated_sql"] is None
    assert result["query_results"] == []
    assert "no employees table" in result["final_summary"].lower()
    assert result["chart_config"]["chart_type"] == "none"
