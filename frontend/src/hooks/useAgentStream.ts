"use client";

import { useCallback, useRef, useState } from "react";
import {
  AttemptRecord,
  ChatMessage,
  CompleteEvent,
  ErrorEvent,
  SelfHealingEvent,
  SQLAttemptEvent,
  SSEEvent,
  StatusEvent,
} from "@/types/agent";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") || "http://localhost:8000";

export function useAgentStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [activeStep, setActiveStep] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    setActiveStep(null);
    setMessages((prev) =>
      prev.map((msg) =>
        msg.isStreaming
          ? {
              ...msg,
              isStreaming: false,
              error: msg.error || "Generation stopped by user.",
            }
          : msg
      )
    );
  }, []);

  const clearMessages = useCallback(() => {
    stopGeneration();
    setMessages([]);
  }, [stopGeneration]);

  const sendQuestion = useCallback(
    async (question: string, connectionId: string, maxRetries: number = 3) => {
      if (!question.trim() || !connectionId) return;

      // Abort any ongoing stream
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      const userMsgId = `user_${Date.now()}`;
      const assistantMsgId = `asst_${Date.now() + 1}`;
      const nowIso = new Date().toISOString();

      const userMessage: ChatMessage = {
        id: userMsgId,
        role: "user",
        content: question.trim(),
        timestamp: nowIso,
        steps: [],
        attempts: [],
      };

      const assistantMessage: ChatMessage = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        timestamp: nowIso,
        isStreaming: true,
        currentStep: "Initializing...",
        steps: [],
        attempts: [],
        completeData: null,
        error: null,
      };

      setMessages((prev) => [...prev, userMessage, assistantMessage]);
      setIsStreaming(true);
      setActiveStep("Initializing...");

      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({
            connection_id: connectionId,
            question: question.trim(),
            max_retries: maxRetries,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          let errDetail = `HTTP ${response.status} ${response.statusText}`;
          try {
            const errJson = await response.json();
            if (errJson.detail) errDetail = errJson.detail;
          } catch {
            // Non-JSON error
          }
          throw new Error(errDetail);
        }

        if (!response.body) {
          throw new Error("No response body received from stream.");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Split buffer by double newline (standard SSE frame separator)
          const parts = buffer.split(/\r?\n\r?\n/);
          // Keep the last segment in the buffer because it might be an incomplete chunk
          buffer = parts.pop() || "";

          for (const rawMessage of parts) {
            const trimmed = rawMessage.trim();
            if (!trimmed) continue;

            // Extract payload from "data: { ... }"
            const lines = trimmed.split(/\r?\n/);
            for (const line of lines) {
              if (line.startsWith("data: ")) {
                const jsonStr = line.slice(6).trim();
                try {
                  const event = JSON.parse(jsonStr) as SSEEvent;

                  setMessages((prev) =>
                    prev.map((msg) => {
                      if (msg.id !== assistantMsgId) return msg;

                      const updated = { ...msg };

                      switch (event.event) {
                        case "status": {
                          const statusEvt = event as StatusEvent;
                          setActiveStep(statusEvt.message);
                          updated.currentStep = statusEvt.message;
                          updated.steps = [
                            ...updated.steps,
                            {
                              step: statusEvt.step,
                              message: statusEvt.message,
                              timestamp: new Date().toISOString(),
                            },
                          ];
                          break;
                        }

                        case "sql_attempt": {
                          const sqlEvt = event as SQLAttemptEvent;
                          const existingAttemptIndex = updated.attempts.findIndex(
                            (a) => a.attempt === sqlEvt.attempt
                          );

                          const attemptRecord: AttemptRecord = {
                            attempt: sqlEvt.attempt,
                            sql: sqlEvt.sql,
                            thought_process: sqlEvt.thought_process,
                          };

                          if (existingAttemptIndex >= 0) {
                            updated.attempts = updated.attempts.map((a, i) =>
                              i === existingAttemptIndex
                                ? { ...a, ...attemptRecord }
                                : a
                            );
                          } else {
                            updated.attempts = [...updated.attempts, attemptRecord];
                          }
                          break;
                        }

                        case "self_healing": {
                          const healEvt = event as SelfHealingEvent;
                          updated.attempts = updated.attempts.map((a) =>
                            a.attempt === healEvt.attempt
                              ? {
                                  ...a,
                                  error: healEvt.error,
                                  diagnosis: healEvt.diagnosis,
                                }
                              : a
                          );
                          break;
                        }

                        case "complete": {
                          const compEvt = event as CompleteEvent;
                          updated.isStreaming = false;
                          updated.completeData = compEvt;
                          updated.content = compEvt.summary;
                          updated.currentStep = "Complete";
                          if (compEvt.healing_trace && compEvt.healing_trace.length > 0) {
                            updated.attempts = compEvt.healing_trace;
                          }
                          break;
                        }

                        case "error": {
                          const errEvt = event as ErrorEvent;
                          updated.isStreaming = false;
                          updated.error = errEvt.message;
                          updated.currentStep = "Failed";
                          if (errEvt.healing_trace && errEvt.healing_trace.length > 0) {
                            updated.attempts = errEvt.healing_trace;
                          }
                          break;
                        }
                      }

                      return updated;
                    })
                  );
                } catch (parseErr) {
                  console.warn("Failed to parse SSE line as JSON:", line, parseErr);
                }
              }
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          return;
        }
        const errorMsg = err instanceof Error ? err.message : String(err);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMsgId
              ? {
                  ...msg,
                  isStreaming: false,
                  error: errorMsg,
                  currentStep: "Error",
                }
              : msg
          )
        );
      } finally {
        setIsStreaming(false);
        setActiveStep(null);
        abortControllerRef.current = null;
      }
    },
    []
  );

  return {
    messages,
    isStreaming,
    activeStep,
    sendQuestion,
    stopGeneration,
    clearMessages,
  };
}
