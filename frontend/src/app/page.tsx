"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  Database,
  Plus,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import { ConnectionModal } from "@/components/connections/ConnectionModal";
import { SchemaTree } from "@/components/sidebar/SchemaTree";
import { ChatWorkspace } from "@/components/chat/ChatWorkspace";
import { useAgentStream } from "@/hooks/useAgentStream";
import { ConnectionResponse } from "@/types/agent";

export default function Home() {
  const [connections, setConnections] = useState<ConnectionResponse[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState<string | null>(null);
  const [isConnectModalOpen, setIsConnectModalOpen] = useState<boolean>(false);
  const [backendHealth, setBackendHealth] = useState<"checking" | "online" | "offline">("checking");

  const {
    messages,
    isStreaming,
    activeStep,
    sendQuestion,
    stopGeneration,
    clearMessages,
  } = useAgentStream();

  // Load registered connections and verify backend health on mount
  useEffect(() => {
    let isMounted = true;

    // 1. Health Check
    api
      .checkHealth()
      .then(() => {
        if (isMounted) setBackendHealth("online");
      })
      .catch(() => {
        if (isMounted) setBackendHealth("offline");
      });

    // 2. Load Connections
    api
      .listConnections()
      .then((data) => {
        if (isMounted) {
          setConnections(data);
          if (data.length > 0) {
            setActiveConnectionId(data[0].id);
          } else {
            // Open modal automatically if user has no connections yet
            setIsConnectModalOpen(true);
          }
        }
      })
      .catch((err) => {
        console.error("Failed to load connections:", err);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleConnectionCreated = (newConn: ConnectionResponse) => {
    setConnections((prev) => [newConn, ...prev]);
    setActiveConnectionId(newConn.id);
  };

  const handleDeleteConnection = async (connId: string) => {
    try {
      await api.deleteConnection(connId);
      setConnections((prev) => prev.filter((c) => c.id !== connId));
      if (activeConnectionId === connId) {
        const remaining = connections.filter((c) => c.id !== connId);
        setActiveConnectionId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err) {
      console.error("Failed to delete connection:", err);
    }
  };

  const handleSendMessage = (question: string, maxRetries: number) => {
    if (!activeConnectionId) {
      setIsConnectModalOpen(true);
      return;
    }
    sendQuestion(question, activeConnectionId, maxRetries);
  };

  const activeConn = connections.find((c) => c.id === activeConnectionId);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      {/* Top Application Navigation Bar */}
      <header className="h-14 border-b border-slate-800 bg-slate-900/90 px-4 flex items-center justify-between shrink-0 select-none z-10">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-blue-900/30">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <span className="font-bold text-sm tracking-tight text-white block">
                Self-Healing Text-to-SQL
              </span>
              <span className="text-[10px] text-blue-400 font-mono block -mt-0.5">
                Groq • LangGraph • Zero-Trust AST
              </span>
            </div>
          </div>
        </div>

        {/* Center / Right Header Badges */}
        <div className="flex items-center gap-3">
          {/* Active Connection Indicator */}
          {activeConn ? (
            <div className="hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800/80 border border-slate-700/60 text-xs">
              <Database className="w-3.5 h-3.5 text-blue-400" />
              <span className="text-slate-300 font-medium truncate max-w-[200px]">
                {activeConn.name}
              </span>
              <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-blue-500/20 text-blue-300 uppercase">
                {activeConn.dialect}
              </span>
            </div>
          ) : (
            <button
              onClick={() => setIsConnectModalOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-sm transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Connect Database
            </button>
          )}

          {/* Backend Status Indicator */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 text-[11px] text-slate-400">
            {backendHealth === "online" ? (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-emerald-400 font-medium">Backend Online</span>
              </>
            ) : backendHealth === "offline" ? (
              <>
                <ShieldAlert className="w-3 h-3 text-rose-400" />
                <span className="text-rose-400 font-medium">Backend Offline</span>
              </>
            ) : (
              <>
                <Activity className="w-3 h-3 text-slate-500 animate-spin" />
                <span>Checking...</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Split Layout: Sidebar + Chat Workspace */}
      <div className="flex flex-1 overflow-hidden">
        <SchemaTree
          connections={connections}
          activeConnectionId={activeConnectionId}
          onSelectConnection={setActiveConnectionId}
          onOpenConnectModal={() => setIsConnectModalOpen(true)}
          onDeleteConnection={handleDeleteConnection}
          onSelectPromptSnippet={(snippet) => {
            if (activeConnectionId) {
              sendQuestion(snippet, activeConnectionId);
            }
          }}
        />

        <ChatWorkspace
          messages={messages}
          isStreaming={isStreaming}
          activeStep={activeStep}
          currentStep={activeStep}
          activeConnectionName={activeConn?.name}
          onSendMessage={handleSendMessage}
          onStopGeneration={stopGeneration}
          onClearMessages={clearMessages}
        />
      </div>

      {/* Connection Modal */}
      <ConnectionModal
        isOpen={isConnectModalOpen}
        onClose={() => setIsConnectModalOpen(false)}
        onConnectionCreated={handleConnectionCreated}
      />
    </div>
  );
}
