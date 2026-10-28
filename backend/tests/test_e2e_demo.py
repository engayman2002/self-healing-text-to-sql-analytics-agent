"""End-to-End Integration and Smoke Tests for Seeded Demo Database and Analytics Pipeline."""

import json
from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient
import sqlalchemy as sa

from app.agent.nodes import set_llm_override
from app.agent.state import (
    AnalyticsSynthesisOutput,
    ChartConfig,
    SelfHealingOutput,
    SQLGenerationOutput,
)
from app.api.connections import connection_store
from app.core.config import get_settings
from app.db.manager import get_connection_manager
from app.db.seed_demo import (
    get_demo_db_path,
    get_demo_db_uri,
    register_demo_connection_if_needed,
    seed_demo_database,
)
from app.main import app
from tests.test_agent_graph import MockStructuredLLM


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Ensure LLM override is cleared before and after each test."""
    set_llm_override(None)
    yield
    set_llm_override(None)


def test_seed_demo_database_schema_and_counts():
    """Verify that seed_demo_database builds all 6 relational tables with analytical row counts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = Path(tmp_dir) / "test_demo_ecommerce.db"
        
        # 1. Seed the database
        created_path = seed_demo_database(custom_path=test_db_path, force_recreate=True)
        assert created_path.exists()
        assert created_path.stat().st_size > 0

        # 2. Inspect with SQLAlchemy
        engine = sa.create_engine(get_demo_db_uri(test_db_path))
        inspector = sa.inspect(engine)
        table_names = set(inspector.get_table_names())

        expected_tables = {
            "customers",
            "categories",
            "products",
            "orders",
            "order_items",
            "marketing_campaigns",
        }
        assert expected_tables.issubset(table_names), f"Missing tables: {expected_tables - table_names}"

        # 3. Verify Foreign Keys
        order_item_fks = inspector.get_foreign_keys("order_items")
        fk_referred_tables = {fk["referred_table"] for fk in order_item_fks}
        assert "orders" in fk_referred_tables
        assert "products" in fk_referred_tables

        product_fks = inspector.get_foreign_keys("products")
        assert any(fk["referred_table"] == "categories" for fk in product_fks)

        # 4. Verify Analytical-Grade Row Counts
        with engine.connect() as conn:
            cust_count = conn.execute(sa.text("SELECT COUNT(*) FROM customers")).scalar()
            cat_count = conn.execute(sa.text("SELECT COUNT(*) FROM categories")).scalar()
            prod_count = conn.execute(sa.text("SELECT COUNT(*) FROM products")).scalar()
            order_count = conn.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar()
            item_count = conn.execute(sa.text("SELECT COUNT(*) FROM order_items")).scalar()
            camp_count = conn.execute(sa.text("SELECT COUNT(*) FROM marketing_campaigns")).scalar()

            assert cust_count is not None and cust_count >= 40, f"Expected >=40 customers, got {cust_count}"
            assert cat_count == 5, f"Expected 5 categories, got {cat_count}"
            assert prod_count is not None and prod_count >= 20, f"Expected >=20 products, got {prod_count}"
            assert order_count is not None and order_count >= 150, f"Expected >=150 orders, got {order_count}"
            assert item_count is not None and item_count >= 150, f"Expected >=150 items, got {item_count}"
            assert camp_count is not None and camp_count >= 10, f"Expected >=10 campaigns, got {camp_count}"

        engine.dispose()


def test_app_startup_auto_registers_demo_connection():
    """Verify that FastAPI lifespan triggers auto-seeding and registers demo connection."""
    # Seed and register
    demo_id = register_demo_connection_if_needed()
    assert demo_id is not None
    assert "demo" in demo_id.lower()

    with TestClient(app) as client:
        # 1. Connection should be in the list
        list_res = client.get("/api/v1/connections")
        assert list_res.status_code == 200
        connections = list_res.json()
        demo_conn = next((c for c in connections if c["id"] == demo_id), None)
        assert demo_conn is not None
        assert demo_conn["dialect"] == "sqlite"
        assert demo_conn["table_count"] == 6

        # 2. Schema Explorer should introspect all 6 tables
        schema_res = client.get(f"/api/v1/connections/{demo_id}/schema")
        assert schema_res.status_code == 200
        schema = schema_res.json()
        assert len(schema["tables"]) == 6
        assert "orders" in schema["tables"]
        assert "marketing_campaigns" in schema["tables"]


def test_e2e_complex_analytical_query_stream():
    """Verify complex multi-table analytical query with bar chart synthesis on demo DB."""
    demo_id = register_demo_connection_if_needed()
    assert demo_id is not None

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Aggregate completed revenue and order count by category using 4-table join.",
                sql_query="""
                    SELECT 
                        c.category_name,
                        COUNT(DISTINCT o.order_id) AS order_count,
                        ROUND(SUM(oi.line_total), 2) AS total_revenue
                    FROM categories c
                    JOIN products p ON c.category_id = p.category_id
                    JOIN order_items oi ON p.product_id = oi.product_id
                    JOIN orders o ON oi.order_id = o.order_id
                    WHERE o.order_status = 'Completed'
                    GROUP BY c.category_name
                    ORDER BY total_revenue DESC
                """,
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Enterprise SaaS led revenue with high volume, followed by Professional Services.",
                chart_config=ChartConfig(
                    chart_type="bar",
                    title="Revenue by Category (Completed Orders)",
                    x_axis_key="category_name",
                    y_axis_keys=["total_revenue"],
                ),
            )
        ],
    })
    set_llm_override(mock_llm)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "connection_id": demo_id,
                "question": "What is the total revenue by product category for completed orders?",
                "max_retries": 3,
            },
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "X-Process-Time-Ms" in response.headers

        # Parse SSE events
        events = []
        for line in response.text.split("\n\n"):
            clean = line.strip()
            if clean.startswith("data: "):
                events.append(json.loads(clean[6:]))

        event_types = [e.get("event") for e in events]
        assert "status" in event_types
        assert "sql_attempt" in event_types
        assert "complete" in event_types

        complete_event = next(e for e in events if e.get("event") == "complete")
        assert complete_event["row_count"] > 0
        assert len(complete_event["data"]) > 0
        first_row = complete_event["data"][0]
        assert "category_name" in first_row
        assert "total_revenue" in first_row
        assert complete_event["chart_config"]["chart_type"] == "bar"


def test_e2e_self_healing_recovery_on_demo_db():
    """Verify deterministic self-healing when LLM hallucinates an invalid column name on demo DB."""
    demo_id = register_demo_connection_if_needed()
    assert demo_id is not None

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            # Attempt 1: Hallucinated column 'client_tier' which does not exist in 'customers'
            SQLGenerationOutput(
                thought_process="Fetch customer details with tier.",
                sql_query="SELECT customer_id, full_name, client_tier FROM customers LIMIT 5",
            ),
            # Attempt 2: Healed SQL using actual column 'segment'
            SQLGenerationOutput(
                thought_process="Fixed column name to segment.",
                sql_query="SELECT customer_id, full_name, segment FROM customers LIMIT 5",
            ),
        ],
        SelfHealingOutput: [
            SelfHealingOutput(
                error_diagnosis="Column 'client_tier' does not exist in customers table. The correct column is 'segment'.",
                fixed_sql_query="SELECT customer_id, full_name, segment FROM customers LIMIT 5",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Retrieved 5 customers successfully after healing schema reference.",
                chart_config=ChartConfig(chart_type="none", title="Customer Segments"),
            )
        ],
    })
    set_llm_override(mock_llm)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "connection_id": demo_id,
                "question": "Show customers and their segment",
                "max_retries": 3,
            },
        )

        assert response.status_code == 200
        events = []
        for line in response.text.split("\n\n"):
            clean = line.strip()
            if clean.startswith("data: "):
                events.append(json.loads(clean[6:]))

        event_types = [e.get("event") for e in events]
        assert "self_healing" in event_types
        assert "complete" in event_types

        healing_event = next(e for e in events if e.get("event") == "self_healing")
        assert "client_tier" in healing_event["diagnosis"]

        complete_event = next(e for e in events if e.get("event") == "complete")
        assert complete_event["attempts"] == 2
        assert complete_event["row_count"] == 5
        assert len(complete_event["healing_trace"]) == 2
        assert complete_event["healing_trace"][0]["error"] is not None
        assert complete_event["healing_trace"][1]["error"] is None


def test_graceful_missing_groq_api_key_diagnostics(monkeypatch):
    """Verify missing or placeholder GROQ_API_KEY yields user-friendly SSE error event."""
    demo_id = register_demo_connection_if_needed()
    assert demo_id is not None

    # Explicitly ensure no mock LLM override is active
    set_llm_override(None)

    # Set GROQ_API_KEY to empty/placeholder
    settings = get_settings()
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/stream",
            json={
                "connection_id": demo_id,
                "question": "Any question without configured LLM",
                "max_retries": 3,
            },
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        # Parse SSE payload
        events = []
        for line in response.text.split("\n\n"):
            clean = line.strip()
            if clean.startswith("data: "):
                events.append(json.loads(clean[6:]))

        assert len(events) >= 1
        error_event = events[0]
        assert error_event.get("event") == "error"
        assert "GROQ_API_KEY" in error_event.get("message", "")
        assert "backend/.env" in error_event.get("message", "")
