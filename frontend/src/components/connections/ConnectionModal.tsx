"use client";

import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Database,
  Loader2,
  Plug,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import {
  ConnectionCreateRequest,
  ConnectionResponse,
  ConnectionTestResponse,
} from "@/types/agent";

interface ConnectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConnectionCreated: (connection: ConnectionResponse) => void;
}

export function ConnectionModal({
  isOpen,
  onClose,
  onConnectionCreated,
}: ConnectionModalProps) {
  const [mode, setMode] = useState<"uri" | "form">("uri");
  const [name, setName] = useState<string>("");
  const [uri, setUri] = useState<string>("");

  // Form Mode State
  const [dialect, setDialect] = useState<string>("postgresql");
  const [host, setHost] = useState<string>("localhost");
  const [port, setPort] = useState<number>(5432);
  const [username, setUsername] = useState<string>("postgres");
  const [password, setPassword] = useState<string>("");
  const [database, setDatabase] = useState<string>("");
  const [ssl, setSsl] = useState<boolean>(false);

  // Status & Feedback State
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [testResult, setTestResult] = useState<ConnectionTestResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleDialectChange = (newDialect: string) => {
    setDialect(newDialect);
    if (newDialect === "postgresql") setPort(5432);
    else if (newDialect === "mysql") setPort(3306);
    else if (newDialect === "mssql") setPort(1433);
  };

  const handleQuickFillDemo = (type: "sqlite" | "postgres" = "sqlite") => {
    setMode("uri");
    if (type === "sqlite") {
      setName("Demo E-Commerce Analytics (SQLite)");
      setUri("sqlite:///./demo_ecommerce.db");
    } else {
      setName("Docker PostgreSQL Analytics");
      setUri("postgresql://postgres:postgres@localhost:5432/demo_analytics");
    }
    setTestResult(null);
    setErrorMessage(null);
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    setErrorMessage(null);

    try {
      const payload =
        mode === "uri"
          ? { uri: uri.trim() }
          : {
              dialect,
              host,
              port,
              username,
              password,
              database,
              ssl,
            };

      const res = await api.testConnection(payload);
      setTestResult(res);
      if (!res.success && res.error) {
        setErrorMessage(res.error);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTesting(false);
    }
  };

  const handleSaveConnection = async () => {
    setIsSaving(true);
    setErrorMessage(null);

    try {
      const payload: ConnectionCreateRequest =
        mode === "uri"
          ? {
              name: name.trim() || undefined,
              uri: uri.trim(),
            }
          : {
              name: name.trim() || undefined,
              dialect,
              host,
              port,
              username,
              password,
              database,
              ssl,
            };

      const newConnection = await api.createConnection(payload);
      onConnectionCreated(newConnection);
      onClose();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-xl rounded-xl border border-slate-700/80 bg-slate-900 shadow-2xl overflow-hidden flex flex-col">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4 bg-slate-900/80">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
              <Database className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white tracking-tight">
                Connect Relational Database
              </h2>
              <p className="text-xs text-slate-400">
                Credentials are encrypted at rest with symmetric Fernet encryption
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5 max-h-[75vh] overflow-y-auto">
          {/* Quick Demo Helper */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 p-3 rounded-lg bg-gradient-to-r from-blue-950/40 via-indigo-950/30 to-purple-950/40 border border-blue-800/40">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-amber-400 shrink-0 animate-pulse" />
              <span className="text-xs text-slate-200 font-medium">
                Want to test instantly? Select a pre-seeded demo:
              </span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                onClick={() => handleQuickFillDemo("sqlite")}
                className="text-xs font-semibold px-2.5 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-white transition-colors shadow-sm"
              >
                SQLite Demo
              </button>
              <button
                type="button"
                onClick={() => handleQuickFillDemo("postgres")}
                className="text-xs font-semibold px-2.5 py-1 rounded-md bg-indigo-600 hover:bg-indigo-500 text-white transition-colors shadow-sm"
              >
                Postgres (Docker)
              </button>
            </div>
          </div>

          {/* Mode Selector Tabs */}
          <div className="flex rounded-lg bg-slate-950 p-1 border border-slate-800">
            <button
              type="button"
              onClick={() => setMode("uri")}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all ${
                mode === "uri"
                  ? "bg-slate-800 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Connection URI Mode
            </button>
            <button
              type="button"
              onClick={() => setMode("form")}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all ${
                mode === "form"
                  ? "bg-slate-800 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Form Builder Mode
            </button>
          </div>

          {/* Connection Name Field */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Connection Display Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Production Analytics PostgreSQL"
              className="w-full px-3 py-2 text-sm rounded-lg bg-slate-950 border border-slate-800 text-white placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-all"
            />
          </div>

          {/* URI Mode Inputs */}
          {mode === "uri" ? (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-medium text-slate-300">
                  Database Connection String (URI)
                </label>
                <span className="text-[10px] text-slate-500 font-mono">
                  postgresql://, mysql://, sqlite:///
                </span>
              </div>
              <textarea
                rows={3}
                value={uri}
                onChange={(e) => setUri(e.target.value)}
                placeholder="postgresql://user:password@hostname:5432/dbname"
                className="w-full px-3 py-2 text-sm font-mono rounded-lg bg-slate-950 border border-slate-800 text-white placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-all resize-none"
              />
            </div>
          ) : (
            /* Form Mode Inputs */
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Dialect
                  </label>
                  <select
                    value={dialect}
                    onChange={(e) => handleDialectChange(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="postgresql">PostgreSQL</option>
                    <option value="mysql">MySQL</option>
                    <option value="sqlite">SQLite</option>
                    <option value="mssql">SQL Server (MSSQL)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Port
                  </label>
                  <input
                    type="number"
                    value={port}
                    onChange={(e) => setPort(Number(e.target.value))}
                    disabled={dialect === "sqlite"}
                    className="w-full px-3 py-2 text-sm rounded-lg bg-slate-950 border border-slate-800 text-white disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Host / Endpoint
                </label>
                <input
                  type="text"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  disabled={dialect === "sqlite"}
                  placeholder="db.example.internal"
                  className="w-full px-3 py-2 text-sm rounded-lg bg-slate-950 border border-slate-800 text-white disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Username
                  </label>
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    disabled={dialect === "sqlite"}
                    className="w-full px-3 py-2 text-sm rounded-lg bg-slate-950 border border-slate-800 text-white disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={dialect === "sqlite"}
                    className="w-full px-3 py-2 text-sm rounded-lg bg-slate-950 border border-slate-800 text-white disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div className="flex items-center justify-between pt-1">
                <div className="flex-1 mr-4">
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Database Name / Path
                  </label>
                  <input
                    type="text"
                    value={database}
                    onChange={(e) => setDatabase(e.target.value)}
                    placeholder={dialect === "sqlite" ? ":memory: or ./db.sqlite" : "analytics_db"}
                    className="w-full px-3 py-2 text-sm rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                {dialect !== "sqlite" && (
                  <label className="flex items-center gap-2 cursor-pointer pt-6">
                    <input
                      type="checkbox"
                      checked={ssl}
                      onChange={(e) => setSsl(e.target.checked)}
                      className="rounded bg-slate-950 border-slate-700 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-xs text-slate-300">Require SSL</span>
                  </label>
                )}
              </div>
            </div>
          )}

          {/* Test Feedback Messages */}
          {testResult && testResult.success && (
            <div className="p-3 rounded-lg bg-emerald-950/40 border border-emerald-500/40 text-emerald-300 flex items-start gap-2.5 text-xs animate-in fade-in">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">Connection verified successfully!</p>
                <p className="text-[11px] text-emerald-400/80 mt-0.5">
                  Dialect: <span className="font-semibold uppercase">{testResult.dialect}</span> • Round-trip Latency: {testResult.latency_ms}ms
                </p>
              </div>
            </div>
          )}

          {errorMessage && (
            <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-500/40 text-rose-300 flex items-start gap-2.5 text-xs animate-in fade-in">
              <AlertCircle className="w-4 h-4 text-rose-400 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium">Connection failed</p>
                <p className="text-[11px] text-rose-400/80 mt-0.5 break-all">
                  {errorMessage}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer Actions */}
        <div className="flex items-center justify-between border-t border-slate-800 px-6 py-4 bg-slate-900/60">
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={isTesting || (mode === "uri" && !uri.trim())}
            className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 transition-colors"
          >
            {isTesting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Plug className="w-3.5 h-3.5" />
            )}
            Test Connection
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 text-xs font-medium rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSaveConnection}
              disabled={isSaving || (mode === "uri" && !uri.trim())}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white transition-all shadow-md shadow-blue-900/20"
            >
              {isSaving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Save & Introspect
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
