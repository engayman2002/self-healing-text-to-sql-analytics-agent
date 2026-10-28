# Technical Specification: Self-Healing Text-to-SQL Analytics Agent

## 1. System Overview & Core Objectives

The **Self-Healing Text-to-SQL Analytics Agent** is a full-stack AI analytics platform that enables users to connect external relational databases, ask natural language questions, and receive accurate data tables, natural language insights, and auto-generated visualizations.

### Key Architectural Pillars

* **Zero-Trust Database Execution:** Strict read-only enforcement at both the AST (Abstract Syntax Tree) parser level and the database transaction level.
* **Deterministic Self-Healing Loop:** If a generated SQL query fails due to syntax errors, dialect mismatches, or missing columns, the agent automatically captures the database traceback, reflects on the schema, rewrites the query, and retries up to a bounded limit (maximum 3 attempts).
* **Ultra-Low Latency Inference:** Powered by **Groq API** (`llama-3.3-70b-versatile`) via LangChain to ensure multi-step self-healing loops complete in under 2–3 seconds.
* **Real-Time Observability:** Streams intermediate agent states (Schema Selection → SQL Generation → Error Recovery → Chart Synthesis) to the Next.js client via Server-Sent Events (SSE).

---

## 2. Technology Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| **Frontend Framework** | Next.js 15 (App Router, TypeScript) | UI rendering, state management, SSE stream consumption |
| **UI & Charts** | Tailwind CSS, shadcn/ui, Recharts, TanStack Table | Clean dashboard UI, interactive data tables, dynamic charts |
| **Backend API** | Python 3.11+, FastAPI, Pydantic v2 | REST APIs, SSE streaming, connection lifecycle management |
| **AI Orchestration** | LangChain (`langchain-core`, `langchain-groq`) + LangGraph | Stateful cyclical graph for the self-healing retry loop |
| **LLM Provider** | Groq Cloud API | High-speed LLM inference with structured JSON outputs |
| **Database & Security** | SQLAlchemy 2.0, `sqlglot`, `cryptography` (Fernet) | Multi-dialect DB pooling, AST SQL validation, credential encryption |

---

## 3. System Architecture & Data Flow

```
[Next.js Client] 
   │  (1) POST /api/v1/chat/stream (Question + Connection ID)
   ▼
[FastAPI Gateway] ──► [Connection Manager (SQLAlchemy Pool)]
   │
   ▼
[LangChain / LangGraph Orchestrator (Groq API)]
   ├──► Node 1: Schema Pruning & Context Builder
   ├──► Node 2: SQL Generator (LLM)
   ├──► Node 3: AST Security Guardrail (sqlglot)
   ├──► Node 4: Safe Read-Only SQL Executor
   │       ├──► (If Success) ──► Node 6: Insight & Chart Config Synthesizer
   │       └──► (If Error & Retries < 3) ──► Node 5: Self-Healing Reflector ──► (Back to Node 3)
   ▼
[SSE Stream to Next.js] ──► Renders Live Steps + SQL + Table + Recharts Visualization

```

---

## 4. Deep-Dive: Database Integration & Security Layer

A production Text-to-SQL system must never expose the target database to destructive operations, connection exhaustion, or unoptimized full-table scans.

### 4.1 Dynamic Connection Manager

* **Supported Dialects:** PostgreSQL (`psycopg2`), MySQL (`pymysql`), SQLite, and MSSQL.
* **Credential Storage:** Connection URIs provided by users in the Next.js UI are encrypted at rest using symmetric Fernet encryption (`AES-128-CBC` with HMAC) before being stored in the application's internal metadata store.
* **Connection Pooling:** Maintain an LRU cache of active `SQLAlchemy` engines per `connection_id` with `pool_size=5`, `max_overflow=10`, and `pool_pre_ping=True` to gracefully handle dropped connections.

### 4.2 Smart Schema Introspection & Pruning

Dumping an entire database schema into the LLM prompt wastes tokens and degrades SQL accuracy.

1. **Metadata Extraction:** Extract table names, column names, data types, primary/foreign keys, and **3 sample rows per table** using SQLAlchemy's `inspect()` module.
2. **Schema Caching:** Cache the extracted DDL summary in memory (or Redis) with a 15-minute TTL, alongside a manual "Refresh Schema" button in the UI.
3. **Table Selection Step:** If the database contains more than 10 tables, run a lightweight Groq call first to filter only the relevant tables for the user's question before generating SQL.

### 4.3 Multi-Layer Read-Only Guardrails

Every generated SQL query must pass three strict checks before touching the user's database:

1. **AST Validation (`sqlglot`):** Parse the SQL string into an Abstract Syntax Tree. Reject immediately if the root statement is not `SELECT` or `WITH` (blocks `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `GRANT`, `EXEC`).
2. **Automatic Row Limiting:** Using `sqlglot`, automatically inject or cap `LIMIT 500` on the outer query if no `LIMIT` clause exists, preventing memory crashes on million-row tables.
3. **Database-Level Read-Only Transaction & Timeout:** Execute queries inside a read-only transaction block with a hard statement timeout of **10 seconds** (e.g., `SET LOCAL statement_timeout = '10s'` in PostgreSQL).

---

## 5. Deep-Dive: Self-Healing AI Agent Workflow (LangChain + Groq)

To avoid spaghetti `while` loops, implement the agent as a deterministic State Graph using `LangGraph` and `ChatGroq`.

### 5.1 Agent State Schema

```python
from typing import TypedDict, Optional, List, Dict, Any

class AgentState(TypedDict):
    question: str
    connection_id: str
    dialect: str
    relevant_schema: str
    generated_sql: Optional[str]
    validation_error: Optional[str]
    execution_error: Optional[str]
    retry_count: int
    max_retries: int
    query_results: Optional[List[Dict[str, Any]]]
    final_summary: Optional[str]
    chart_config: Optional[Dict[str, Any]]

```

### 5.2 Graph Nodes & Self-Healing Logic

1. **`schema_pruner_node`:**
* Fetches cached schema metadata for `connection_id`.
* Selects relevant tables and formats compact DDL + 3 sample rows per table.


2. **`sql_generator_node`:**
* Model: `ChatGroq(model="llama-3.3-70b-versatile", temperature=0.0)`
* Uses `.with_structured_output()` to return `{ "thought_process": str, "sql_query": str }`.
* Enforces dialect-specific rules (e.g., double quotes for case-sensitive identifiers in PostgreSQL, backticks in MySQL).


3. **`ast_validator_node`:**
* Parses `sql_query` via `sqlglot.transpile(sql_query, read=dialect)`.
* Verifies read-only compliance and appends `LIMIT 500` if absent.
* If invalid, populates `validation_error` and routes to `self_healer_node`.


4. **`sql_executor_node`:**
* Executes the validated SQL against the SQLAlchemy engine.
* If execution succeeds: stores rows in `query_results` and routes to `analytics_synthesizer_node`.
* If `SQLAlchemyError` occurs: captures the exact database error message (e.g., `column "revnue" does not exist. Did you mean "revenue"?`), stores it in `execution_error`, increments `retry_count`, and routes to `self_healer_node`.


5. **`self_healer_node` (The Core Self-Healing Engine):**
* Triggered when `validation_error` or `execution_error` is present and `retry_count` is less than `max_retries` (default 3).
* **Prompt Strategy:** Passes the original question, the exact database DDL, the **failed SQL query**, and the **exact database error traceback** to Groq.
* Instructs the model to diagnose *why* the query failed, explain the fix in one sentence, and output the corrected SQL.
* Routes back to `ast_validator_node`.


6. **`analytics_synthesizer_node`:**
* Receives the question, the final working SQL, and a preview of `query_results` (first 20 rows + summary statistics).
* Outputs a structured response containing:
* `summary`: Concise markdown explanation of the findings.
* `chart_config`: JSON specification for the Next.js frontend (`chart_type`: `"bar" | "line" | "pie" | "kpi" | "none"`, `x_axis_key`, `y_axis_keys`, `title`).





---

## 6. Backend API Specification (FastAPI)

### 6.1 Endpoints

* `POST /api/v1/connections/test` — Validates a database connection URI and returns connection latency and detected dialect.
* `POST /api/v1/connections` — Encrypts and saves a database connection; triggers initial schema introspection.
* `GET /api/v1/connections/{id}/schema` — Returns the structured list of tables, columns, and types for the UI sidebar explorer.
* `POST /api/v1/chat/stream` — Executes the Self-Healing Agent and streams events via **Server-Sent Events (SSE)**.

### 6.2 SSE Stream Contract (`POST /api/v1/chat/stream`)

The Next.js frontend listens to standard SSE events so the user can visually watch the self-healing process in real time:

```json
// Event 1: Status Update
{"event": "status", "step": "schema_selection", "message": "Selected 3 relevant tables: orders, customers, order_items"}

// Event 2: Initial SQL Attempt
{"event": "sql_attempt", "attempt": 1, "sql": "SELECT c.name, SUM(o.total) FROM customers c JOIN orders o ON c.id = o.cust_id GROUP BY c.name"}

// Event 3: Self-Healing Triggered (if an error occurred)
{"event": "self_healing", "attempt": 1, "error": "column o.cust_id does not exist", "diagnosis": "Foreign key in orders table is named customer_id, not cust_id. Rewriting query."}

// Event 4: Healed SQL Attempt
{"event": "sql_attempt", "attempt": 2, "sql": "SELECT c.name, SUM(o.total) AS total_spent FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name LIMIT 500"}

// Event 5: Final Payload
{
  "event": "complete",
  "sql": "SELECT c.name, SUM(o.total) AS total_spent ...",
  "data": [{"name": "Acme Corp", "total_spent": 45200}],
  "summary": "Acme Corp is the highest-spending customer with $45,200 in total orders.",
  "chart_config": {
    "chart_type": "bar",
    "title": "Top Customers by Total Spend",
    "x_axis_key": "name",
    "y_axis_keys": ["total_spent"]
  }
}

```

---

## 7. Frontend Architecture (Next.js App Router)

### 7.1 Key UI Views & Components

1. **Database Connection Manager Modal (`components/connections/ConnectionModal.tsx`):**
* Supports switching between **Connection URI Mode** (`postgresql://user:pass@host:5432/db`) and **Form Mode** (Host, Port, User, Password, Database, SSL Toggle).
* Includes a "Test Connection" button with visual feedback before saving.


2. **Schema Explorer Sidebar (`components/sidebar/SchemaTree.tsx`):**
* Collapsible tree view showing connected tables, column names, and data type badges (`VARCHAR`, `INT`, `TIMESTAMP`).


3. **Agent Reasoning & Self-Healing Trace (`components/chat/HealingTraceAccordion.tsx`):**
* A collapsible timeline stepper inside each chat message.
* Displays green checkmarks for successful steps and an amber badge (`Self-Healed in 2 attempts`) whenever the agent recovered from a SQL error, allowing technical users to inspect the failed query alongside the fixed query.


4. **Multi-Tab Analytics Result Card (`components/analytics/ResultCard.tsx`):**
* **Tab 1 — Visualization:** Dynamically renders a responsive `BarChart`, `LineChart`, `AreaChart`, or `PieChart` using **Recharts** based on `chart_config`.
* **Tab 2 — Data Table:** Paginated, sortable table using **TanStack Table** with a one-click **Export CSV** button.
* **Tab 3 — SQL Query:** Syntax-highlighted SQL block with a "Copy SQL" button.



---

## 8. Project Directory Structure (Monorepo)

```text
self-healing-sql-agent/
├── docker-compose.yml
├── README.md
├── backend/                          # Python FastAPI + LangChain Service
│   ├── pyproject.toml
│   ├── .env.example                  # GROQ_API_KEY, ENCRYPTION_KEY
│   └── app/
│       ├── main.py                   # FastAPI entrypoint & CORS configuration
│       ├── core/
│       │   ├── config.py             # Environment settings
│       │   └── security.py           # Fernet credential encryption/decryption
│       ├── db/
│       │   ├── manager.py            # SQLAlchemy dynamic pool & read-only execution
│       │   ├── introspector.py       # Schema DDL & sample rows extractor
│       │   └── guardrails.py         # sqlglot AST validator & LIMIT injector
│       ├── agent/
│       │   ├── state.py              # LangGraph AgentState definition
│       │   ├── prompts.py            # SQL generation & Self-Healing system prompts
│       │   ├── nodes.py              # Graph nodes (Generator, Validator, Healer, Synthesizer)
│       │   └── graph.py              # Compiled LangGraph workflow
│       └── api/
│           ├── connections.py        # Connection CRUD & schema endpoints
│           └── chat.py               # SSE streaming endpoint
└── frontend/                         # Next.js 15 App Router (TypeScript)
    ├── package.json
    ├── src/
    │   ├── app/
    │   │   ├── layout.tsx
    │   │   └── page.tsx              # Main workspace layout (Sidebar + Chat/Analytics)
    │   ├── components/
    │   │   ├── connections/          # ConnectionModal, ConnectionSelector
    │   │   ├── sidebar/              # SchemaTree
    │   │   ├── chat/                 # ChatInput, MessageList, HealingTraceAccordion
    │   │   └── analytics/            # ResultCard, DynamicChart, DataTable
    │   ├── hooks/
    │   │   └── useAgentStream.ts     # Custom hook for consuming FastAPI SSE streams
    │   └── types/
    │       └── agent.ts              # Strict TypeScript interfaces matching backend schemas

```

---

## 9. Step-by-Step Implementation Roadmap (Execution Plan)

### Phase 1: Database Engine & Security Foundation (Days 1–2)

1. Initialize the `backend/` FastAPI project and configure environment variables (`GROQ_API_KEY`, `ENCRYPTION_KEY`).
2. Implement `db/manager.py` with SQLAlchemy connection pooling, read-only session execution, and 10-second statement timeouts.
3. Implement `db/introspector.py` to extract compact table schemas, foreign keys, and 3 sample rows per table.
4. Implement `db/guardrails.py` using `sqlglot` to block non-SELECT queries and enforce `LIMIT 500`.

* **Deliverable:** Unit tests passing against a sample PostgreSQL/SQLite database verifying that `DROP TABLE` is blocked and schemas are accurately extracted.

### Phase 2: LangChain + Groq Self-Healing Agent (Days 3–4)

1. Define the `AgentState` and structured Pydantic output models for Groq (`SQLGenerationOutput`, `SelfHealingOutput`, `AnalyticsOutput`).
2. Build the LangGraph workflow in `agent/graph.py` connecting the Generator, AST Validator, Executor, Self-Healer, and Synthesizer nodes.
3. Expose the workflow via `POST /api/v1/chat/stream` using FastAPI's `StreamingResponse` (SSE).

* **Deliverable:** Ability to send a deliberately tricky natural language query via cURL/Postman, watch the agent fail on attempt 1, self-heal on attempt 2, and return structured JSON results.

### Phase 3: Next.js Frontend & Live Streaming UI (Days 5–7)

1. Scaffold the Next.js 15 project with Tailwind CSS, `shadcn/ui`, `lucide-react`, `recharts`, and `@tanstack/react-table`.
2. Build the Database Connection Modal and the Left Sidebar Schema Explorer connected to `/api/v1/connections`.
3. Implement `useAgentStream.ts` using the `fetch` ReadableStream API to parse SSE chunks in real time.
4. Build the `HealingTraceAccordion` and `ResultCard` (Dynamic Recharts renderer + CSV exportable Data Table).

* **Deliverable:** End-to-end working application where a user connects a database, asks a question, watches the self-healing steps live, and interacts with the resulting chart.

### Phase 4: Containerization & Production Hardening (Day 8)

1. Seed a demo database (e.g., Chinook or Northwind E-commerce dataset) so the app works out-of-the-box for testing.
2. Write `Dockerfile`s for both `frontend` and `backend` and unify them in `docker-compose.yml` alongside a demo PostgreSQL container.
3. Add error boundaries, empty-state handling (when a valid query returns 0 rows), and rate-limiting middleware.

---