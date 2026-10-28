"use client";

import { useState } from "react";
import {
  BarChart2,
  Check,
  Clock,
  Code2,
  Copy,
  Database,
  FileSpreadsheet,
  Sparkles,
} from "lucide-react";
import { CompleteEvent } from "@/types/agent";
import { DataTable } from "./DataTable";
import { DynamicChart } from "./DynamicChart";

interface ResultCardProps {
  result: CompleteEvent;
}

export function ResultCard({ result }: ResultCardProps) {
  const [activeTab, setActiveTab] = useState<"chart" | "table" | "sql">("chart");
  const [copied, setCopied] = useState<boolean>(false);

  const handleCopySQL = () => {
    if (!result.sql) return;
    navigator.clipboard.writeText(result.sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="w-full rounded-2xl border border-slate-800 bg-slate-900/90 shadow-xl overflow-hidden my-3 animate-in fade-in duration-300">
      {/* Executive Summary Banner */}
      <div className="p-4 sm:p-5 border-b border-slate-800 bg-gradient-to-r from-blue-950/40 via-slate-900 to-indigo-950/30">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles className="w-4 h-4 text-blue-400" />
          <span className="text-xs font-semibold uppercase tracking-wider text-blue-300">
            Executive Analytical Insight
          </span>
        </div>
        <p className="text-sm text-slate-100 leading-relaxed font-sans">
          {result.summary}
        </p>
      </div>

      {/* Tabs Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-slate-950/60">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setActiveTab("chart")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              activeTab === "chart"
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <BarChart2 className="w-3.5 h-3.5" />
            Visualization
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("table")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              activeTab === "table"
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            Data Table ({result.row_count})
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("sql")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              activeTab === "sql"
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <Code2 className="w-3.5 h-3.5" />
            SQL Query
          </button>
        </div>

        {/* Execution Metrics Badges */}
        <div className="hidden sm:flex items-center gap-3 text-[11px] text-slate-400 font-mono">
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3 text-slate-500" />
            {result.execution_time_ms}ms
          </span>
          <span className="flex items-center gap-1">
            <Database className="w-3 h-3 text-slate-500" />
            {result.row_count} rows
          </span>
        </div>
      </div>

      {/* Tabs Content */}
      <div className="p-4 sm:p-5 bg-slate-900/50">
        {activeTab === "chart" && (
          <DynamicChart data={result.data} config={result.chart_config} />
        )}

        {activeTab === "table" && (
          <DataTable data={result.data} columns={result.columns} />
        )}

        {activeTab === "sql" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400 font-medium">
                Sanitized & Transpiled Read-Only SQL Query:
              </span>
              <button
                type="button"
                onClick={handleCopySQL}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    Copied!
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    Copy SQL
                  </>
                )}
              </button>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 font-mono text-xs text-blue-300 leading-relaxed overflow-x-auto shadow-inner">
              <pre className="whitespace-pre-wrap">{result.sql}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
