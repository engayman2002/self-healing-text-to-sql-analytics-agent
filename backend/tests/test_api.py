"""Integration tests for FastAPI REST endpoints and SSE streaming."""

import json
import pytest
from fastapi.testclient import TestClient
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.agent.nodes import set_llm_override
from app.agent.state import (
    AnalyticsSynthesisOutput,
    ChartConfig,
    SQLGenerationOutput,
)
from app.api.connections import connection_store
from app.db.manager import get_connection_manager
from app.main import app
from tests.test_agent_graph import MockStructuredLLM


@pytest.fixture
def client_with_seeded_db():
    """Create a FastAPI TestClient with a registered SQLite connection."""
    client = TestClient(app)

    # Clean existing store
    connection_store.clear()

    # Create memory database with a table
    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL);"))
        conn.execute(sa.text("INSERT INTO products VALUES (1, 'Widget', 19.99), (2, 'Gadget', 49.99);"))

    # Register in manager and connection store
    conn_id = "api_test_conn_1"
    manager = get_connection_manager()
    manager._engines[conn_id] = engine

    connection_store.add(
        conn_id=conn_id,
        name="Test Inventory DB",
        dialect="sqlite",
        encrypted_uri="dummy_encrypted_uri",
        masked_uri="sqlite:///:memory:",
        table_count=1,
    )

    yield client, conn_id, engine

    set_llm_override(None)
    connection_store.clear()
    manager.close_engine(conn_id)


def test_health_check(client_with_seeded_db):
    """Verify health endpoint returns status healthy."""
    client, _, _ = client_with_seeded_db
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_connection_test_endpoint(client_with_seeded_db):
    """Verify /connections/test verifies credentials and reports latency."""
    client, _, _ = client_with_seeded_db
    response = client.post(
        "/api/v1/connections/test",
        json={"uri": "sqlite:///:memory:"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["dialect"] == "sqlite"
    assert data["latency_ms"] >= 0


def test_list_connections_endpoint(client_with_seeded_db):
    """Verify GET /connections returns masked connection list."""
    client, conn_id, _ = client_with_seeded_db
    response = client.get("/api/v1/connections")
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 1
    target = next((item for item in items if item["id"] == conn_id), None)
    assert target is not None
    assert target["name"] == "Test Inventory DB"
    assert "dummy" not in target["masked_uri"]


def test_get_connection_schema(client_with_seeded_db):
    """Verify GET /connections/{id}/schema returns tables and columns."""
    client, conn_id, _ = client_with_seeded_db
    response = client.get(f"/api/v1/connections/{conn_id}/schema")
    assert response.status_code == 200
    schema = response.json()
    assert schema["dialect"] == "sqlite"
    assert "products" in schema["tables"]
    products_tbl = schema["tables"]["products"]
    col_names = [col["name"] for col in products_tbl["columns"]]
    assert "name" in col_names
    assert "price" in col_names


def test_chat_query_endpoint(client_with_seeded_db):
    """Verify non-streaming POST /chat/query returns structured analytical response."""
    client, conn_id, _ = client_with_seeded_db

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Query all products sorted by price.",
                sql_query="SELECT name, price FROM products ORDER BY price ASC",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Found 2 products. Widget is cheapest at $19.99.",
                chart_config=ChartConfig(
                    chart_type="bar",
                    title="Product Prices",
                    x_axis_key="name",
                    y_axis_keys=["price"],
                ),
            )
        ],
    })
    set_llm_override(mock_llm)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "connection_id": conn_id,
            "question": "Show all products and prices",
            "max_retries": 3,
        },
    )

    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True
    assert res["row_count"] == 2
    assert res["chart_config"]["chart_type"] == "bar"
    assert "Widget" in res["summary"]


def test_chat_stream_endpoint(client_with_seeded_db):
    """Verify SSE streaming POST /chat/stream yields properly formatted Server-Sent Events."""
    client, conn_id, _ = client_with_seeded_db

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Select all products.",
                sql_query="SELECT * FROM products",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Retrieved product catalog successfully.",
                chart_config=ChartConfig(
                    chart_type="bar",
                    title="Products",
                    x_axis_key="name",
                    y_axis_keys=["price"],
                ),
            )
        ],
    })
    set_llm_override(mock_llm)

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "connection_id": conn_id,
            "question": "Get all products",
            "max_retries": 3,
        },
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    # Parse SSE payload lines
    lines = response.text.split("\n\n")
    events = []
    for line in lines:
        clean = line.strip()
        if clean.startswith("data: "):
            json_str = clean[6:]
            events.append(json.loads(json_str))

    event_types = [e.get("event") for e in events]
    assert "status" in event_types
    assert "sql_attempt" in event_types
    assert "complete" in event_types

    complete_event = next(e for e in events if e.get("event") == "complete")
    assert complete_event["row_count"] == 2
    assert complete_event["sql"] is not None
    assert complete_event["chart_config"]["chart_type"] == "bar"


def test_delete_connection(client_with_seeded_db):
    """Verify DELETE /connections/{id} removes connection cleanly."""
    client, conn_id, _ = client_with_seeded_db
    del_res = client.delete(f"/api/v1/connections/{conn_id}")
    assert del_res.status_code == 204

    get_res = client.get(f"/api/v1/connections/{conn_id}/schema")
    assert get_res.status_code == 404
