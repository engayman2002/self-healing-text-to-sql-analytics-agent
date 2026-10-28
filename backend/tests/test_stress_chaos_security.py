"""Intensive Stress, Chaos, Red-Team Security Fuzzing, and Edge-Case Serialization Test Suite.

Covers:
1. High-concurrency stress testing (25 concurrent SSE streams + 15 schema requests via httpx).
2. Red-Team adversarial SQL fuzzing (30+ attack vectors: comments, stacked queries, SELECT INTO, ATTACH/PRAGMA, CTE mutations).
3. Toxic data & strict RFC-8259 serialization torture (NaN, Infinity, Decimals, Dates, UUIDs, Unicode, Div-by-zero).
4. Mid-stream client disconnect & connection pool resource leak verification.
5. Malformed API input boundary fuzzing (empty/oversized questions, invalid UUIDs, out-of-range retries, corrupt URIs).
"""

import asyncio
from datetime import date, datetime, time
from decimal import Decimal
import json
import math
from pathlib import Path
import pytest
import uuid
import httpx
from httpx import ASGITransport
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.agent.graph import safe_json_dumps, stream_agent_events
from app.agent.nodes import set_llm_override
from app.agent.state import (
    AnalyticsSynthesisOutput,
    ChartConfig,
    SQLGenerationOutput,
)
from app.api.connections import connection_store
from app.db.guardrails import (
    SQLSecurityError,
    SQLSyntaxError,
    validate_and_sanitize_sql,
)
from app.db.introspector import serialize_cell
from app.db.manager import get_connection_manager
from app.db.seed_demo import register_demo_connection_if_needed, seed_demo_database
from app.main import app
from tests.test_agent_graph import MockStructuredLLM


@pytest.fixture(autouse=True)
def clean_llm():
    """Ensure LLM override is cleared before and after each test."""
    set_llm_override(None)
    yield
    set_llm_override(None)


# ===========================================================================
# 1. High-Concurrency Stress Test (25 Concurrent Streams + 15 Schema Invocations)
# ===========================================================================

@pytest.mark.asyncio
async def test_high_concurrency_stress_25_streams_and_15_schemas():
    """Fire 25 simultaneous SSE chat requests and 15 simultaneous schema requests concurrently.

    Verifies:
    - 100% of requests succeed with HTTP 200.
    - No SQLite 'check_same_thread' exceptions.
    - No QueuePool / connection pool starvation or timeouts.
    - All checked-out connections return to 0 after completion.
    """
    demo_id = register_demo_connection_if_needed()
    assert demo_id is not None

    # Setup deterministic mock LLM for concurrency test
    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Count total customers.",
                sql_query="SELECT COUNT(*) AS total_customers FROM customers",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Total customers count retrieved.",
                chart_config=ChartConfig(
                    chart_type="kpi",
                    title="Customer Count",
                    x_axis_key=None,
                    y_axis_keys=["total_customers"],
                ),
            )
        ],
    })
    set_llm_override(mock_llm)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Task 1: 25 Concurrent SSE stream requests
        async def send_stream_request(i: int):
            resp = await client.post(
                "/api/v1/chat/stream",
                json={
                    "connection_id": demo_id,
                    "question": f"Concurrent analytics question {i}",
                    "max_retries": 3,
                },
                timeout=30.0,
            )
            assert resp.status_code == 200, f"Request {i} failed: {resp.text}"
            assert "text/event-stream" in resp.headers["content-type"]
            text_body = resp.text
            assert "event: complete" in text_body or '"event": "complete"' in text_body
            return resp.status_code

        # Task 2: 15 Concurrent Schema introspection requests
        async def send_schema_request(j: int):
            resp = await client.get(
                f"/api/v1/connections/{demo_id}/schema",
                timeout=30.0,
            )
            assert resp.status_code == 200, f"Schema request {j} failed: {resp.text}"
            data = resp.json()
            assert len(data["tables"]) == 6
            return resp.status_code

        stream_tasks = [send_stream_request(i) for i in range(25)]
        schema_tasks = [send_schema_request(j) for j in range(15)]

        # Fire all 40 requests simultaneously
        results = await asyncio.gather(*stream_tasks, *schema_tasks)
        assert len(results) == 40
        assert all(code == 200 for code in results)

    # Verify no leaked checked-out connections in engine manager
    manager = get_connection_manager()
    engine = manager.get_engine(demo_id)
    if engine is not None and hasattr(engine.pool, "checkedout"):
        assert engine.pool.checkedout() == 0, f"Leaked {engine.pool.checkedout()} connections!"


# ===========================================================================
# 2. Red-Team Adversarial SQL Fuzzing (30 Malicious / Exploit Payloads)
# ===========================================================================

ADVERSARIAL_PAYLOADS = [
    # Comment Obfuscation & Stacked Injection
    "/* comment */ DROP TABLE customers; -- SELECT 1",
    "SELECT * FROM customers; DELETE FROM orders;",
    "SELECT * FROM customers; DROP DATABASE demo;",
    "SELECT 1; UPDATE customers SET segment = 'Enterprise';",
    "SELECT * FROM customers; TRUNCATE TABLE order_items;",
    # Table Creation & File System Exports
    "SELECT * INTO hacked_table FROM customers",
    "SELECT full_name, email INTO new_users FROM customers",
    "SELECT * FROM customers INTO OUTFILE '/tmp/evil.txt'",
    "SELECT * FROM customers INTO DUMPFILE '/tmp/evil.bin'",
    # SQLite Specific File & Configuration Exploits
    "ATTACH DATABASE 'evil.db' AS evil",
    "PRAGMA writable_schema = ON",
    "PRAGMA foreign_keys = OFF",
    "DETACH DATABASE evil",
    # Nested Data-Modifying CTEs inside Subqueries
    "WITH cte AS (DELETE FROM customers RETURNING *) SELECT * FROM cte",
    "WITH cte AS (INSERT INTO customers (full_name) VALUES ('hacked')) SELECT * FROM cte",
    "WITH cte AS (UPDATE customers SET segment = 'Enterprise') SELECT * FROM cte",
    "SELECT * FROM (WITH cte AS (DELETE FROM orders) SELECT 1)",
    "SELECT * FROM (WITH cte AS (UPDATE orders SET total_amount = 0) SELECT 1)",
    # Dialect Administrative & Privilege Commands
    "SET time_zone = 'UTC'",
    "SHOW TABLES",
    "DESCRIBE customers",
    "COPY customers TO '/tmp/data'",
    "LOAD DATA INFILE 'file' INTO TABLE customers",
    "CREATE TABLE evil_table (id INT)",
    "ALTER TABLE customers ADD COLUMN evil TEXT",
    "TRUNCATE TABLE orders",
    "GRANT ALL PRIVILEGES ON DATABASE db TO attacker",
    "REVOKE ALL ON customers FROM analyst",
    "KILL 1234",
    "MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN DELETE",
    # Empty, Whitespace, Comment-Only, and Binary Garbage
    "",
    "   \n\t   ",
    "-- just a comment",
    "/* block comment only */",
    "-- comment 1\n-- comment 2\n",
    "\x00\x01\x02\xff garbage binary data",
]


@pytest.mark.parametrize("payload", ADVERSARIAL_PAYLOADS)
def test_red_team_adversarial_sql_fuzzing(payload: str):
    """Verify that all 30+ adversarial exploit payloads are blocked by zero-trust AST guardrails."""
    with pytest.raises((SQLSecurityError, SQLSyntaxError)):
        validate_and_sanitize_sql(payload, dialect="sqlite", max_rows=500)


def test_huge_limit_tampering_capped():
    """Verify that tampered huge limit (e.g. LIMIT 999999999) is strictly capped to 500."""
    tampered_sql = "SELECT * FROM orders LIMIT 999999999"
    sanitized = validate_and_sanitize_sql(tampered_sql, dialect="sqlite", max_rows=500)
    assert "LIMIT 500" in sanitized
    assert "999999999" not in sanitized


def test_negative_limit_tampering_capped():
    """Verify that tampered negative limit is overridden with safe max_rows limit."""
    tampered_sql = "SELECT * FROM orders LIMIT -5"
    sanitized = validate_and_sanitize_sql(tampered_sql, dialect="sqlite", max_rows=500)
    assert "LIMIT 500" in sanitized


# ===========================================================================
# 3. Toxic Data & Edge-Case Serialization Torture
# ===========================================================================

def test_toxic_floats_nan_and_infinity_serialized_to_null():
    """Verify that float NaN, Inf, and -Inf are converted to null in safe_json_dumps without browser crashes."""
    toxic_payload = {
        "event": "complete",
        "data": [
            {"name": "Item A", "margin": float("nan"), "ratio": float("inf")},
            {"name": "Item B", "margin": float("-inf"), "ratio": 1.25},
        ],
    }

    # Must not raise ValueError(allow_nan=False)
    json_str = safe_json_dumps(toxic_payload)
    assert "NaN" not in json_str
    assert "Infinity" not in json_str
    assert "-Infinity" not in json_str

    # Must parse successfully with strict parser that rejects raw NaN/Infinity
    def reject_constants(c):
        raise ValueError(f"Unsafe constant detected in JSON: {c}")

    parsed = json.loads(json_str, parse_constant=reject_constants)
    assert parsed["data"][0]["margin"] is None
    assert parsed["data"][0]["ratio"] is None
    assert parsed["data"][1]["margin"] is None
    assert parsed["data"][1]["ratio"] == 1.25


def test_toxic_types_serialization_comprehensive():
    """Verify rich serialization of Decimals, Dates, UUIDs, bytes, and Unicode Arabic text."""
    test_uid = uuid.uuid4()
    toxic_dict = {
        "decimal_normal": Decimal("12345.67"),
        "decimal_nan": Decimal("NaN"),
        "decimal_inf": Decimal("Infinity"),
        "dt": datetime(2024, 6, 15, 14, 30, 45),
        "d": date(2024, 6, 15),
        "t": time(14, 30, 45),
        "uid": test_uid,
        "raw_bytes": b"\xde\xad\xbe\xef",
        "arabic": "عميل مميز - شركة التقنية المتقدمة",
        "none_val": None,
    }

    json_str = safe_json_dumps(toxic_dict)
    parsed = json.loads(json_str)

    assert parsed["decimal_normal"] == 12345.67
    assert parsed["decimal_nan"] is None
    assert parsed["decimal_inf"] is None
    assert "2024-06-15" in parsed["dt"]
    assert parsed["d"] == "2024-06-15"
    assert parsed["uid"] == str(test_uid)
    assert "<bytes len=4>" in parsed["raw_bytes"]
    assert "عميل مميز" in parsed["arabic"]
    assert parsed["none_val"] is None


def test_division_by_zero_sql_execution():
    """Verify division by zero in SQL (e.g. 1.0 / 0.0) is handled cleanly without crashing."""
    demo_id = register_demo_connection_if_needed()
    manager = get_connection_manager()

    # SQLite returns NULL for division by zero (1.0 / 0.0)
    res = manager.execute_read_only_query(
        connection_id=demo_id,
        sql="SELECT 1.0 / 0.0 AS zero_div_result",
    )
    assert res.row_count == 1
    cell_val = res.rows[0]["zero_div_result"]
    assert cell_val is None or math.isinf(cell_val)

    # Ensure safe_json_dumps serializes without error
    json_out = safe_json_dumps(res.rows)
    assert "zero_div_result" in json_out


def test_sum_on_empty_filtered_table_returns_null_safely():
    """Verify aggregation on 0 matching rows (e.g. SUM WHERE 1=0 returning [None]) serializes cleanly."""
    demo_id = register_demo_connection_if_needed()
    manager = get_connection_manager()

    res = manager.execute_read_only_query(
        connection_id=demo_id,
        sql="SELECT SUM(total_amount) AS total, AVG(total_amount) AS avg_amt FROM orders WHERE 1=0",
    )
    assert res.row_count == 1
    assert res.rows[0]["total"] is None
    assert res.rows[0]["avg_amt"] is None

    json_out = safe_json_dumps(res.rows)
    parsed = json.loads(json_out)
    assert parsed[0]["total"] is None
    assert parsed[0]["avg_amt"] is None


# ===========================================================================
# 4. Mid-Stream Client Disconnect & Connection Pool Leak Test
# ===========================================================================

@pytest.mark.asyncio
async def test_mid_stream_client_disconnect_no_leaks():
    """Simulate client disconnecting immediately after the first SSE event.

    Verifies:
    - Generator terminates cleanly with asyncio.CancelledError / GeneratorExit.
    - No unhandled exception occurs in the server.
    - Checked-out connection count remains 0.
    """
    demo_id = register_demo_connection_if_needed()

    mock_llm = MockStructuredLLM({
        SQLGenerationOutput: [
            SQLGenerationOutput(
                thought_process="Count orders.",
                sql_query="SELECT COUNT(*) FROM orders",
            )
        ],
        AnalyticsSynthesisOutput: [
            AnalyticsSynthesisOutput(
                summary="Total orders.",
                chart_config=ChartConfig(chart_type="none", title="Orders"),
            )
        ],
    })
    set_llm_override(mock_llm)

    gen = stream_agent_events(
        connection_id=demo_id,
        question="What is the total order count?",
        max_retries=3,
    )

    # Consume only the first event then abort (break out of loop)
    first_event = await anext(gen)
    assert "data: " in first_event

    # Close the generator simulating client disconnect
    await gen.aclose()

    # Verify connection pool status
    manager = get_connection_manager()
    engine = manager.get_engine(demo_id)
    if engine is not None and hasattr(engine.pool, "checkedout"):
        assert engine.pool.checkedout() == 0, "Checked-out connection was not returned upon disconnect!"


# ===========================================================================
# 5. Malformed Input & API Boundary Fuzzing
# ===========================================================================

@pytest.mark.asyncio
async def test_api_boundary_fuzzing_chat_query():
    """Test malformed inputs to /api/v1/chat/query yield clean 4xx validation errors, never 500."""
    demo_id = register_demo_connection_if_needed()
    transport = ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Empty question
        r1 = await client.post(
            "/api/v1/chat/query",
            json={"connection_id": demo_id, "question": "", "max_retries": 3},
        )
        assert r1.status_code == 422, f"Expected 422, got {r1.status_code}"

        # 2. Whitespace-only question
        r2 = await client.post(
            "/api/v1/chat/query",
            json={"connection_id": demo_id, "question": "     \n\t  ", "max_retries": 3},
        )
        assert r2.status_code == 422, f"Expected 422, got {r2.status_code}"

        # 3. Oversized question (10,000 characters)
        r3 = await client.post(
            "/api/v1/chat/query",
            json={"connection_id": demo_id, "question": "A" * 10000, "max_retries": 3},
        )
        assert r3.status_code == 422, f"Expected 422, got {r3.status_code}"

        # 4. Out-of-bounds max_retries (0 and 99)
        r4 = await client.post(
            "/api/v1/chat/query",
            json={"connection_id": demo_id, "question": "Valid question?", "max_retries": 0},
        )
        assert r4.status_code == 422, f"Expected 422, got {r4.status_code}"

        r5 = await client.post(
            "/api/v1/chat/query",
            json={"connection_id": demo_id, "question": "Valid question?", "max_retries": 99},
        )
        assert r5.status_code == 422, f"Expected 422, got {r5.status_code}"

        # 5. Non-existent connection ID
        r6 = await client.post(
            "/api/v1/chat/query",
            json={"connection_id": "non_existent_conn_id_999", "question": "Valid question?", "max_retries": 3},
        )
        assert r6.status_code == 404, f"Expected 404, got {r6.status_code}"

        # 6. Corrupt database URI to /api/v1/connections
        r7 = await client.post(
            "/api/v1/connections",
            json={"uri": "corrupt_garbage_uri_not_a_url!@#$%"},
        )
        assert r7.status_code == 400, f"Expected 400, got {r7.status_code}"
