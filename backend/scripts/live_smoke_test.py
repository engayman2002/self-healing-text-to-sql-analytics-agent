"""Live End-to-End Smoke Test Script using Real Groq Cloud AI Inference.

Executes 4 representative analytical queries against the seeded demo_ecommerce.db
using the actual ChatGroq model configured in backend/.env:
1. Multi-table Join + Bar Chart (Top 5 products by revenue)
2. Time-Series Aggregation (Monthly order count & revenue in 2024)
3. Intentional Self-Healing Trigger (Column hallucination recovery)
4. Zero-Row Result Handling (Orders placed in 1995)
"""

import asyncio
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

# Ensure backend directory is in sys.path
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(backend_root / ".env")

from app.agent.graph import run_agent_workflow
from app.agent.nodes import is_groq_configured
from app.core.config import get_settings
from app.db.manager import get_connection_manager
from app.db.seed_demo import get_demo_db_path, get_demo_db_uri, seed_demo_database


QUERIES = [
    {
        "id": 1,
        "name": "Multi-table Join + Bar Chart",
        "question": "What are the top 5 products by total revenue from completed orders?",
    },
    {
        "id": 2,
        "name": "Time-Series Aggregation",
        "question": "Show monthly order count and total revenue across 2024.",
    },
    {
        "id": 3,
        "name": "Intentional Self-Healing Trigger",
        "question": "List the top 5 customers by their total_spend from the orders table using the cust_tier column.",
    },
    {
        "id": 4,
        "name": "Zero-Row Result",
        "question": "Show all orders placed in the year 1995.",
    },
]


def print_separator(char="=", length=100):
    print(char * length)


async def main():
    print_separator("=")
    print("  🚀 SELF-HEALING TEXT-TO-SQL: LIVE GROQ E2E SMOKE TEST SUITE")
    print_separator("=")

    settings = get_settings()
    key = (settings.GROQ_API_KEY or "").strip()
    model = settings.GROQ_MODEL or "openai/gpt-oss-120b"

    masked_key = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "<missing>"
    print(f"• Groq API Key:   {masked_key}")
    print(f"• Groq Model:     {model}")

    if not is_groq_configured():
        print("\n❌ Error: Valid GROQ_API_KEY not configured in backend/.env.")
        print("Please configure a valid Groq Cloud API key from https://console.groq.com.")
        sys.exit(1)

    print("\n📦 Ensuring Demo E-Commerce Database is seeded...")
    db_path = seed_demo_database()
    db_uri = get_demo_db_uri(db_path)
    print(f"• Database URI: {db_uri}")

    conn_id = "live_smoke_test_demo"
    manager = get_connection_manager()
    manager.register_engine(conn_id, db_uri)
    print("• Connection registered in Dynamic Engine Manager.\n")

    results: List[Dict[str, Any]] = []

    for q in QUERIES:
        q_id = q["id"]
        q_name = q["name"]
        q_text = q["question"]

        print_separator("-")
        print(f"▶ Query {q_id}: [{q_name}]")
        print(f"  Prompt: \"{q_text}\"")

        start_time = time.perf_counter()
        try:
            state = await run_agent_workflow(
                connection_id=conn_id,
                question=q_text,
                max_retries=3,
            )
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            data = state.get("query_results") or []
            sql = state.get("generated_sql") or ""
            retries = state.get("retry_count", 0)
            chart = state.get("chart_config") or {}
            chart_type = chart.get("chart_type", "none")
            summary = state.get("final_summary") or ""
            status = state.get("status", "unknown")
            error = state.get("execution_error") or state.get("validation_error")

            success = state.get("query_results") is not None and summary != ""

            print(f"  Status:       {'✅ SUCCESS' if success else '❌ FAILED'}")
            print(f"  Latency:      {elapsed_ms} ms")
            print(f"  Attempts:     {retries + 1}")
            print(f"  Rows:         {len(data)}")
            print(f"  Chart Type:   {chart_type}")
            print(f"  SQL Query:    {sql.replace(chr(10), ' ')}")
            if len(summary) > 0:
                short_summary = summary[:120] + "..." if len(summary) > 120 else summary
                print(f"  Summary:      {short_summary}")
            if error:
                print(f"  Error Detail: {error}")

            # Check healing trace
            history = state.get("attempt_history") or []
            if len(history) > 1:
                print(f"  🩹 Healing Trace ({len(history)} attempts):")
                for item in history:
                    att_num = item.get("attempt")
                    att_err = item.get("error")
                    att_diag = item.get("diagnosis")
                    print(f"    • Attempt {att_num}: error='{att_err}', diagnosis='{att_diag}'")

            results.append({
                "id": q_id,
                "name": q_name,
                "success": success,
                "latency_ms": elapsed_ms,
                "attempts": retries + 1,
                "rows": len(data),
                "chart_type": chart_type,
                "sql": sql,
            })

        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            print(f"  ❌ Unhandled Exception: {exc}")
            results.append({
                "id": q_id,
                "name": q_name,
                "success": False,
                "latency_ms": elapsed_ms,
                "attempts": 0,
                "rows": 0,
                "chart_type": "error",
                "sql": f"Exception: {exc}",
            })

    print_separator("=")
    print("  📊 LIVE GROQ E2E SMOKE TEST SUMMARY TABLE")
    print_separator("=")
    print(f"{'#':<3} | {'Query Description':<32} | {'Status':<10} | {'Latency':<10} | {'Attempts':<8} | {'Rows':<6} | {'Chart':<8}")
    print_separator("-")

    all_passed = True
    for r in results:
        status_str = "PASS ✅" if r["success"] else "FAIL ❌"
        if not r["success"]:
            all_passed = False
        print(f"{r['id']:<3} | {r['name']:<32} | {status_str:<10} | {r['latency_ms']:>6.1f} ms | {r['attempts']:<8} | {r['rows']:<6} | {r['chart_type']:<8}")

    print_separator("=")
    if all_passed:
        print("🎉 ALL 4 LIVE GROQ E2E SMOKE TESTS PASSED CLEANLY!")
    else:
        print("⚠️ SOME LIVE QUERIES ENCOUNTERED FAILURES - CHECK LOGS ABOVE.")
    print_separator("=")


if __name__ == "__main__":
    asyncio.run(main())
