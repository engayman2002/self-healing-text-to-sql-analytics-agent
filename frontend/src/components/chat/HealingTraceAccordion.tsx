"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  Layers,
  Loader2,
  ShieldCheck,
  Wrench,
  XCircle,
} from "lucide-react";
import { AttemptRecord, TraceStep } from "@/types/agent";

interface HealingTraceAccordionProps {
  steps: TraceStep[];
  attempts: AttemptRecord[];
  isStreaming?: boolean;
  currentStep?: string;
  error?: string | null;
}

export function HealingTraceAccordion({
  steps,
  attempts,
  isStreaming,
  currentStep,
  error,
}: HealingTraceAccordionProps) {
  // Default to open while streaming so the user watches real-time steps
  const [isOpen, setIsOpen] = useState<boolean>(true);

  const attemptCount = attempts.length;
  const isSelfHealed = attemptCount > 1 && !error;
  const isSuccessFirstTry = attemptCount === 1 && !error && !isStreaming;

  return (
    <div className="w-full rounded-xl border border-slate-800 bg-slate-900/90 shadow-sm overflow-hidden my-3">
      {/* Header Bar */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-900 hover:bg-slate-800/80 transition-colors text-left"
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
            <Cpu className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-slate-200">
                Agent Reasoning & Self-Healing Trace
              </span>

              {/* Status Badges */}
              {isStreaming ? (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  {currentStep || "Processing..."}
                </span>
              ) : isSelfHealed ? (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30">
                  <Wrench className="w-3 h-3" />
                  Self-Healed in {attemptCount} attempts
                </span>
              ) : isSuccessFirstTry ? (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  <CheckCircle2 className="w-3 h-3" />
                  Executed on 1st attempt
                </span>
              ) : error ? (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-rose-500/10 text-rose-400 border border-rose-500/30">
                  <XCircle className="w-3 h-3" />
                  Execution Failed
                </span>
              ) : null}
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Zero-trust AST validation, schema reflection, and multi-step recovery
            </p>
          </div>
        </div>

        <div className="text-slate-400">
          {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {/* Accordion Content */}
      {isOpen && (
        <div className="p-4 border-t border-slate-800/80 space-y-3 bg-slate-950/40 text-xs">
          {/* Status Progression Steps */}
          {steps.length > 0 && (
            <div className="space-y-1.5 pb-2 border-b border-slate-800/60">
              <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500 flex items-center gap-1">
                <Layers className="w-3 h-3" />
                Pipeline Progression
              </span>
              <div className="space-y-1">
                {steps.map((st, i) => (
                  <div key={i} className="flex items-center gap-2 text-slate-300 text-[11px]">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />
                    <span>{st.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Attempts Timeline */}
          {attempts.length > 0 ? (
            <div className="space-y-3">
              <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500 flex items-center gap-1">
                <ShieldCheck className="w-3 h-3 text-emerald-400" />
                SQL Generation & Reflection History
              </span>

              {attempts.map((att) => {
                const hasError = !!att.error;

                return (
                  <div
                    key={att.attempt}
                    className={`rounded-lg border p-3 space-y-2 transition-all ${
                      hasError
                        ? "border-amber-500/30 bg-amber-950/20"
                        : "border-slate-800 bg-slate-900/60"
                    }`}
                  >
                    {/* Attempt Header */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                            hasError
                              ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                              : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                          }`}
                        >
                          Attempt #{att.attempt}
                        </span>
                        {att.execution_time_ms && (
                          <span className="text-[11px] text-slate-400 font-mono">
                            Latency: {att.execution_time_ms}ms
                          </span>
                        )}
                      </div>

                      {hasError ? (
                        <span className="flex items-center gap-1 text-[11px] text-amber-400 font-medium">
                          <AlertTriangle className="w-3 h-3" />
                          Recovery Triggered
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                          <CheckCircle2 className="w-3 h-3" />
                          Passed AST & DB Execution
                        </span>
                      )}
                    </div>

                    {/* Thought Process */}
                    {att.thought_process && (
                      <p className="text-[11px] text-slate-300 italic">
                        &quot;{att.thought_process}&quot;
                      </p>
                    )}

                    {/* SQL Snippet Preview */}
                    <div className="rounded bg-slate-950 p-2.5 font-mono text-[11px] text-slate-200 border border-slate-800 overflow-x-auto">
                      <code>{att.sql}</code>
                    </div>

                    {/* Error & Diagnosis Recovery Card */}
                    {hasError && (
                      <div className="mt-2 p-2.5 rounded bg-amber-950/40 border border-amber-500/30 space-y-1.5 text-[11px]">
                        <div>
                          <span className="font-semibold text-rose-400 uppercase text-[10px] tracking-wider block">
                            Database Traceback / Validation Error:
                          </span>
                          <span className="font-mono text-rose-300/90 break-all">
                            {att.error}
                          </span>
                        </div>

                        {att.diagnosis && (
                          <div className="pt-1 border-t border-amber-500/20">
                            <span className="font-semibold text-amber-300 uppercase text-[10px] tracking-wider block">
                              Agent Reflection & Diagnostic Fix:
                            </span>
                            <span className="text-amber-200">
                              {att.diagnosis}
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            isStreaming && (
              <div className="flex items-center gap-2 text-slate-400 py-2">
                <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                <span>Agent is analyzing schema and generating query...</span>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
