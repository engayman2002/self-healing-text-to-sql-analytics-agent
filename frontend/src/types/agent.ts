/**
 * Strict TypeScript interfaces matching backend FastAPI Pydantic models and SSE stream payloads.
 * No explicit `any` types.
 */

// ---------------------------------------------------------------------------
// Database Connection Types
// ---------------------------------------------------------------------------

export interface ConnectionTestRequest {
  uri?: string;
  dialect?: string;
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  database?: string;
  ssl?: boolean;
}

export interface ConnectionTestResponse {
  success: boolean;
  dialect: string;
  latency_ms: number;
  masked_uri: string;
  error?: string | null;
}

export interface ConnectionCreateRequest {
  name?: string;
  uri?: string;
  dialect?: string;
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  database?: string;
  ssl?: boolean;
}

export interface ConnectionResponse {
  id: string;
  name: string;
  dialect: string;
  masked_uri: string;
  table_count: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Database Schema Explorer Types
// ---------------------------------------------------------------------------

export interface ColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
  default?: string | null;
}

export interface ForeignKeyInfo {
  constrained_columns: string[];
  referred_table: string;
  referred_columns: string[];
}

export interface IndexInfo {
  name?: string | null;
  columns: string[];
  unique: boolean;
}

export interface TableMetadata {
  name: string;
  columns: ColumnInfo[];
  primary_keys: string[];
  foreign_keys: ForeignKeyInfo[];
  indexes: IndexInfo[];
  sample_rows: Record<string, unknown>[];
  row_count_approx?: number | null;
}

export interface DatabaseSchema {
  dialect: string;
  tables: Record<string, TableMetadata>;
  introspected_at: string;
}

// ---------------------------------------------------------------------------
// Visualization & Analytics Types
// ---------------------------------------------------------------------------

export type ChartType = "bar" | "line" | "area" | "pie" | "kpi" | "none";

export interface ChartConfig {
  chart_type: ChartType;
  title: string;
  x_axis_key?: string | null;
  y_axis_keys: string[];
}

export interface AttemptRecord {
  attempt: number;
  sql: string;
  thought_process?: string | null;
  error?: string | null;
  diagnosis?: string | null;
  execution_time_ms?: number | null;
  row_count?: number | null;
  stage?: string | null;
}

// ---------------------------------------------------------------------------
// Server-Sent Events (SSE) Stream Payloads
// ---------------------------------------------------------------------------

export interface StatusEvent {
  event: "status";
  step: string;
  message: string;
}

export interface SQLAttemptEvent {
  event: "sql_attempt";
  attempt: number;
  sql: string;
  thought_process?: string | null;
}

export interface SelfHealingEvent {
  event: "self_healing";
  attempt: number;
  error: string;
  diagnosis: string;
}

export interface CompleteEvent {
  event: "complete";
  sql: string;
  data: Record<string, unknown>[];
  columns: string[];
  row_count: number;
  attempts: number;
  healing_trace: AttemptRecord[];
  summary: string;
  chart_config: ChartConfig;
  execution_time_ms: number;
}

export interface ErrorEvent {
  event: "error";
  message: string;
  attempts: number;
  healing_trace: AttemptRecord[];
}

export type SSEEvent =
  | StatusEvent
  | SQLAttemptEvent
  | SelfHealingEvent
  | CompleteEvent
  | ErrorEvent;

// ---------------------------------------------------------------------------
// UI Chat Message Types
// ---------------------------------------------------------------------------

export interface TraceStep {
  step: string;
  message: string;
  timestamp: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  isStreaming?: boolean;
  currentStep?: string;
  steps: TraceStep[];
  attempts: AttemptRecord[];
  completeData?: CompleteEvent | null;
  error?: string | null;
}
