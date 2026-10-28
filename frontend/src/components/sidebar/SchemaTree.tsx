"use client";

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Database,
  Eye,
  Key,
  Link2,
  Loader2,
  Plus,
  RefreshCw,
  Table,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { ConnectionResponse, DatabaseSchema, TableMetadata } from "@/types/agent";

interface SchemaTreeProps {
  connections: ConnectionResponse[];
  activeConnectionId: string | null;
  onSelectConnection: (id: string) => void;
  onOpenConnectModal: () => void;
  onDeleteConnection: (id: string) => void;
  onSelectPromptSnippet?: (snippet: string) => void;
}

export function SchemaTree({
  connections,
  activeConnectionId,
  onSelectConnection,
  onOpenConnectModal,
  onDeleteConnection,
  onSelectPromptSnippet,
}: SchemaTreeProps) {
  const [schema, setSchema] = useState<DatabaseSchema | null>(null);
  const [isLoadingSchema, setIsLoadingSchema] = useState<boolean>(false);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());
  const [previewTable, setPreviewTable] = useState<TableMetadata | null>(null);

  // Load schema whenever active connection changes
  useEffect(() => {
    if (!activeConnectionId) {
      setSchema(null);
      return;
    }

    let isMounted = true;
    setIsLoadingSchema(true);

    api
      .getConnectionSchema(activeConnectionId)
      .then((data) => {
        if (isMounted) {
          setSchema(data);
          // Auto-expand first 2 tables
          const initialExpanded = new Set<string>();
          Object.keys(data.tables).slice(0, 2).forEach((tbl) => initialExpanded.add(tbl));
          setExpandedTables(initialExpanded);
        }
      })
      .catch((err) => {
        console.error("Failed to fetch schema:", err);
      })
      .finally(() => {
        if (isMounted) setIsLoadingSchema(false);
      });

    return () => {
      isMounted = false;
    };
  }, [activeConnectionId]);

  const handleRefreshSchema = async () => {
    if (!activeConnectionId) return;
    setIsRefreshing(true);
    try {
      const refreshed = await api.refreshConnectionSchema(activeConnectionId);
      setSchema(refreshed);
    } catch (err) {
      console.error("Failed to refresh schema:", err);
    } finally {
      setIsRefreshing(false);
    }
  };

  const toggleTableExpanded = (tableName: string) => {
    setExpandedTables((prev) => {
      const next = new Set(prev);
      if (next.has(tableName)) {
        next.delete(tableName);
      } else {
        next.add(tableName);
      }
      return next;
    });
  };

  const activeConnection = connections.find((c) => c.id === activeConnectionId);

  return (
    <aside className="w-80 h-full flex flex-col bg-slate-900 border-r border-slate-800 select-none">
      {/* Sidebar Header: Connection Switcher */}
      <div className="p-4 border-b border-slate-800 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-slate-200">
            <Database className="w-4 h-4 text-blue-400" />
            <span className="text-xs font-semibold tracking-wider uppercase text-slate-400">
              Database Explorer
            </span>
          </div>
          <button
            onClick={onOpenConnectModal}
            title="Connect New Database"
            className="p-1 rounded-md bg-blue-600 hover:bg-blue-500 text-white transition-colors"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>

        {/* Connection Selector Dropdown */}
        {connections.length > 0 ? (
          <div className="flex items-center gap-1.5">
            <select
              value={activeConnectionId || ""}
              onChange={(e) => onSelectConnection(e.target.value)}
              className="flex-1 bg-slate-950 border border-slate-800 text-xs text-white rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 truncate"
            >
              {connections.map((conn) => (
                <option key={conn.id} value={conn.id}>
                  {conn.name} ({conn.dialect})
                </option>
              ))}
            </select>
            <button
              onClick={handleRefreshSchema}
              disabled={isRefreshing}
              title="Refresh Schema Cache"
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-50 transition-colors"
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin text-blue-400" : ""}`}
              />
            </button>
            {activeConnectionId && (
              <button
                onClick={() => onDeleteConnection(activeConnectionId)}
                title="Disconnect & Delete"
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-rose-900/40 text-slate-400 hover:text-rose-400 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={onOpenConnectModal}
            className="w-full py-2 px-3 border border-dashed border-slate-700 hover:border-blue-500 rounded-lg text-xs font-medium text-slate-400 hover:text-blue-400 flex items-center justify-center gap-2 transition-colors bg-slate-950/50"
          >
            <Plus className="w-3.5 h-3.5" />
            Connect Database
          </button>
        )}

        {/* Active Connection Dialect & Masked URI Badge */}
        {activeConnection && (
          <div className="flex items-center justify-between text-[11px] text-slate-400 px-1 font-mono">
            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-blue-400 uppercase font-semibold text-[10px]">
              {activeConnection.dialect}
            </span>
            <span className="truncate max-w-[170px]" title={activeConnection.masked_uri}>
              {activeConnection.masked_uri}
            </span>
          </div>
        )}
      </div>

      {/* Schema Tree Content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-1">
        {isLoadingSchema ? (
          <div className="flex flex-col items-center justify-center h-48 text-slate-500 gap-2">
            <Loader2 className="w-5 h-5 animate-spin text-blue-400" />
            <span className="text-xs">Introspecting schema...</span>
          </div>
        ) : schema && Object.keys(schema.tables).length > 0 ? (
          Object.values(schema.tables).map((table) => {
            const isExpanded = expandedTables.has(table.name);

            return (
              <div key={table.name} className="rounded-lg overflow-hidden border border-transparent hover:border-slate-800/80 transition-colors">
                {/* Table Header Row */}
                <div className="flex items-center justify-between py-1.5 px-2 hover:bg-slate-800/60 rounded-md group cursor-pointer">
                  <div
                    className="flex items-center gap-1.5 flex-1 min-w-0"
                    onClick={() => toggleTableExpanded(table.name)}
                  >
                    {isExpanded ? (
                      <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    ) : (
                      <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    )}
                    <Table className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                    <span
                      className="text-xs font-medium text-slate-200 truncate group-hover:text-white"
                      title={table.name}
                    >
                      {table.name}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0">
                    <span className="text-[10px] text-slate-500 font-mono">
                      {table.columns.length} cols
                    </span>
                    {table.sample_rows.length > 0 && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setPreviewTable(table);
                        }}
                        title="Preview sample rows"
                        className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-700 transition-colors"
                      >
                        <Eye className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Expanded Columns Tree */}
                {isExpanded && (
                  <div className="pl-6 pr-2 py-1 space-y-0.5 border-l-2 border-slate-800 ml-3.5 my-1">
                    {table.columns.map((col) => {
                      const isPk = table.primary_keys.includes(col.name);
                      const fkRelation = table.foreign_keys.find((fk) =>
                        fk.constrained_columns.includes(col.name)
                      );

                      return (
                        <div
                          key={col.name}
                          className="flex items-center justify-between text-[11px] py-0.5 px-1 rounded hover:bg-slate-800/40"
                        >
                          <div className="flex items-center gap-1.5 truncate">
                            {isPk ? (
                              <span title="Primary Key" className="shrink-0 flex items-center">
                                <Key className="w-3 h-3 text-amber-400" />
                              </span>
                            ) : fkRelation ? (
                              <span title={`Foreign Key: -> ${fkRelation.referred_table}`} className="shrink-0 flex items-center">
                                <Link2 className="w-3 h-3 text-indigo-400" />
                              </span>
                            ) : (
                              <span className="w-3 h-3 inline-block" />
                            )}
                            <span
                              className={`truncate ${
                                isPk
                                  ? "text-amber-200 font-medium"
                                  : fkRelation
                                  ? "text-indigo-200 font-medium"
                                  : "text-slate-300"
                              }`}
                              title={col.name}
                            >
                              {col.name}
                            </span>
                          </div>

                          <span
                            className="text-[10px] text-slate-500 font-mono shrink-0 max-w-[80px] truncate ml-1"
                            title={col.type}
                          >
                            {col.type}
                          </span>
                        </div>
                      );
                    })}

                    {/* Quick Starter Query Pill */}
                    {onSelectPromptSnippet && (
                      <button
                        onClick={() =>
                          onSelectPromptSnippet(`Show the top 10 rows in ${table.name}`)
                        }
                        className="mt-1 text-[10px] text-blue-400 hover:text-blue-300 hover:underline block truncate text-left"
                      >
                        + Query {table.name}
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })
        ) : (
          <div className="text-center py-12 px-4 text-slate-500 space-y-2">
            <p className="text-xs">No tables introspected yet.</p>
            <p className="text-[11px] text-slate-600">
              Connect a database to explore tables, columns, and sample records.
            </p>
          </div>
        )}
      </div>

      {/* Sample Rows Preview Drawer/Modal */}
      {previewTable && (
        <div className="p-3 border-t border-slate-800 bg-slate-950 text-xs">
          <div className="flex items-center justify-between mb-2">
            <span className="font-semibold text-slate-200 flex items-center gap-1.5">
              <Eye className="w-3.5 h-3.5 text-blue-400" />
              {previewTable.name} (Sample Rows)
            </span>
            <button
              onClick={() => setPreviewTable(null)}
              className="text-slate-400 hover:text-white"
            >
              ✕
            </button>
          </div>
          <div className="max-h-36 overflow-auto border border-slate-800 rounded bg-slate-900 p-2 font-mono text-[10px] text-slate-300 space-y-1">
            {previewTable.sample_rows.map((row, idx) => (
              <pre key={idx} className="whitespace-pre-wrap break-all">
                {JSON.stringify(row, null, 2)}
              </pre>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}
