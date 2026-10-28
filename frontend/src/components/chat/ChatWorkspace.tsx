"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowUp,
  Bot,
  RotateCcw,
  Sparkles,
  Square,
  User,
} from "lucide-react";
import { HealingTraceAccordion } from "./HealingTraceAccordion";
import { ResultCard } from "../analytics/ResultCard";
import { ChatMessage } from "@/types/agent";

interface ChatWorkspaceProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  activeStep: string | null;
  activeConnectionName?: string;
  onSendMessage: (question: string, maxRetries: number) => void;
  onStopGeneration: () => void;
  onClearMessages: () => void;
}

const STARTER_PROMPTS = [
  "Show the top 5 highest-spending customers with their total order value",
  "What is the distribution of orders by customer?",
  "List all products with price greater than the average price",
  "Calculate total revenue and average order size",
];

export function ChatWorkspace({
  messages,
  isStreaming,
  currentStep,
  activeConnectionName,
  onSendMessage,
  onStopGeneration,
  onClearMessages,
}: ChatWorkspaceProps & { currentStep?: string | null }) {
  const [input, setInput] = useState<string>("");
  const [maxRetries, setMaxRetries] = useState<number>(3);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom as new messages / steps stream in
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;
    onSendMessage(input.trim(), maxRetries);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-950 overflow-hidden relative">
      {/* Scrollable Message List */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
        {messages.length === 0 ? (
          /* Empty State Hero & Starter Prompts */
          <div className="flex flex-col items-center justify-center min-h-[65vh] max-w-2xl mx-auto text-center space-y-6 animate-in fade-in duration-300">
            <div className="p-4 rounded-2xl bg-gradient-to-tr from-blue-600/20 via-indigo-600/10 to-purple-600/20 border border-blue-500/20 shadow-lg shadow-blue-900/10 text-blue-400">
              <Sparkles className="w-8 h-8" />
            </div>

            <div className="space-y-2">
              <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
                Ask your database anything.
              </h1>
              <p className="text-sm text-slate-400 max-w-md mx-auto">
                Powered by Groq & LangGraph. The agent writes SQL, executes it against your
                database, self-heals syntax or schema mistakes automatically, and visualizes
                the results.
              </p>
              {activeConnectionName && (
                <div className="inline-block mt-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs text-blue-400 font-medium">
                  Connected to: <span className="text-white">{activeConnectionName}</span>
                </div>
              )}
            </div>

            {/* Starter Suggestion Pills */}
            <div className="w-full pt-2">
              <span className="text-[11px] uppercase tracking-wider font-semibold text-slate-500 block mb-3">
                Suggested Starter Analytics
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left">
                {STARTER_PROMPTS.map((prompt, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      setInput(prompt);
                    }}
                    className="p-3 rounded-xl bg-slate-900/80 hover:bg-slate-850 border border-slate-800 hover:border-blue-500/50 text-xs text-slate-300 hover:text-white transition-all text-left shadow-sm group"
                  >
                    <span className="text-blue-400 group-hover:text-blue-300 font-medium mr-1.5">
                      →
                    </span>
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Render Messages */
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex gap-3 sm:gap-4 max-w-4xl mx-auto ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              {/* Assistant Icon */}
              {msg.role === "assistant" && (
                <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white shrink-0 shadow-md shadow-blue-900/20">
                  <Bot className="w-4 h-4" />
                </div>
              )}

              {/* Message Bubble Container */}
              <div
                className={`flex-1 max-w-3xl ${
                  msg.role === "user" ? "flex justify-end" : ""
                }`}
              >
                {msg.role === "user" ? (
                  <div className="flex items-start gap-2.5">
                    <div className="px-4 py-3 rounded-2xl bg-blue-600 text-white text-sm shadow-md shadow-blue-950/40">
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    </div>
                    <div className="w-8 h-8 rounded-xl bg-slate-800 flex items-center justify-center text-slate-300 shrink-0">
                      <User className="w-4 h-4" />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3 w-full">
                    {/* Collapsible Self-Healing Trace Accordion */}
                    {(msg.steps.length > 0 || msg.attempts.length > 0 || msg.isStreaming) && (
                      <HealingTraceAccordion
                        steps={msg.steps}
                        attempts={msg.attempts}
                        isStreaming={msg.isStreaming}
                        currentStep={msg.currentStep}
                        error={msg.error}
                      />
                    )}

                    {/* Result Card (When Complete) */}
                    {msg.completeData && (
                      <ResultCard result={msg.completeData} />
                    )}

                    {/* Error Banner (When Failed) */}
                    {msg.error && (
                      <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/40 text-rose-300 text-xs flex items-start gap-3">
                        <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
                        <div className="space-y-1">
                          <p className="font-semibold text-rose-200">
                            Query Execution Failed
                          </p>
                          <p className="text-rose-300/80 break-all">{msg.error}</p>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Chat Input Dock */}
      <div className="p-4 border-t border-slate-800/80 bg-slate-900/80 backdrop-blur-md">
        <form
          onSubmit={handleSubmit}
          className="max-w-4xl mx-auto rounded-2xl border border-slate-700/80 bg-slate-950 p-2 shadow-2xl focus-within:border-blue-500/70 focus-within:ring-1 focus-within:ring-blue-500 transition-all"
        >
          <textarea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask an analytics question (e.g. 'Show total revenue grouped by month for 2024')..."
            className="w-full bg-transparent px-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none resize-none"
          />

          {/* Controls Bar */}
          <div className="flex items-center justify-between pt-1 border-t border-slate-800/60 px-2 text-xs">
            <div className="flex items-center gap-3">
              {/* Max Retries Selector */}
              <div className="flex items-center gap-1.5 text-slate-400">
                <span className="text-[11px]">Healing Retries:</span>
                <select
                  value={maxRetries}
                  onChange={(e) => setMaxRetries(Number(e.target.value))}
                  className="bg-slate-900 border border-slate-800 text-[11px] text-slate-200 rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value={1}>1 retry</option>
                  <option value={2}>2 retries</option>
                  <option value={3}>3 retries (default)</option>
                  <option value={5}>5 retries (thorough)</option>
                </select>
              </div>

              {messages.length > 0 && (
                <button
                  type="button"
                  onClick={onClearMessages}
                  className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-200 transition-colors"
                >
                  <RotateCcw className="w-3 h-3" />
                  Clear Chat
                </button>
              )}
            </div>

            {/* Submit / Stop Action Buttons */}
            <div>
              {isStreaming ? (
                <button
                  type="button"
                  onClick={onStopGeneration}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-medium transition-colors shadow-sm"
                >
                  <Square className="w-3.5 h-3.5 fill-current" />
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!input.trim()}
                  className="p-2 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white transition-all shadow-md shadow-blue-900/30"
                >
                  <ArrowUp className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
