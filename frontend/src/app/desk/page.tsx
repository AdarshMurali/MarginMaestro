"use client";

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";

import { postDeskChat } from "@/lib/api";
import { DARK_GREEN, LIGHT_GREEN } from "@/lib/brand";

// MM-129: "Ask the margin desk" -- a chat with the ADK agent on Agent
// Runtime. The page only shows the conversation: the agent picks its tools
// (prices, CSA/policy search, margin-call status) and the API makes sure it
// answers as the signed-in analyst, scoped to their counterparties.

interface Turn {
  role: "analyst" | "desk";
  text: string;
  tools?: string[];
}

const SUGGESTIONS = [
  "Which of my margin calls are awaiting approval?",
  "What is CP-3's threshold and minimum transfer amount?",
  "What is HPE trading at right now?",
];

const TOOL_LABELS: Record<string, string> = {
  get_current_prices: "Live prices",
  get_historical_prices: "Price history",
  retrieve_document_chunks: "CSA & policy search",
  list_margin_calls: "Margin calls",
  get_margin_call: "Margin call status",
};

export default function DeskPage() {
  const { data: session } = useSession();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!session || !message || busy) return;
    setTurns((current) => [...current, { role: "analyst", text: message }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const reply = await postDeskChat(session.backendAccessToken, message, sessionId);
      setSessionId(reply.session_id);
      setTurns((current) => [
        ...current,
        { role: "desk", text: reply.answer, tools: reply.tools_used },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The desk assistant is unavailable.");
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setTurns([]);
    setSessionId(null);
    setError(null);
  };

  return (
    <main className="flex min-h-full flex-1 flex-col bg-white">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-6 py-12">
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-black">Ask the Desk</h1>
            <p className="text-sm text-neutral-500">
              A Gemini agent on Agent Platform that answers from live prices, CSA and policy
              documents, and your margin calls -- only the counterparties you cover. It can
              read, never act: approvals stay on the Approvals &amp; SLA page.
            </p>
          </div>
          {turns.length > 0 && (
            <button
              type="button"
              onClick={reset}
              className="shrink-0 rounded-lg border border-neutral-200 px-3 py-1.5 text-xs text-neutral-600 hover:bg-neutral-50"
            >
              New chat
            </button>
          )}
        </div>

        <div className="flex flex-1 flex-col gap-4 rounded-xl border border-neutral-200 bg-white p-5">
          {turns.length === 0 && (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-neutral-500">Try asking:</p>
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  disabled={busy}
                  onClick={() => send(suggestion)}
                  className="rounded-lg border border-neutral-200 px-3 py-2 text-left text-sm text-neutral-700 hover:bg-neutral-50"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}

          {turns.map((turn, index) => (
            <div
              key={index}
              className={`flex flex-col gap-1.5 ${turn.role === "analyst" ? "items-end" : "items-start"}`}
            >
              <div
                className="max-w-[85%] whitespace-pre-wrap rounded-xl px-4 py-2.5 text-sm"
                style={
                  turn.role === "analyst"
                    ? { backgroundColor: DARK_GREEN, color: "white" }
                    : { backgroundColor: "#f5f5f5", color: "black" }
                }
              >
                {turn.text}
              </div>
              {turn.tools && turn.tools.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {turn.tools.map((tool) => (
                    <span
                      key={tool}
                      className="rounded-full px-2 py-0.5 text-[11px]"
                      style={{ backgroundColor: LIGHT_GREEN, color: DARK_GREEN }}
                    >
                      {TOOL_LABELS[tool] ?? tool}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {busy && <p className="text-xs text-neutral-500">The desk is checking…</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div ref={bottomRef} />
        </div>

        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void send(input);
          }}
        >
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            maxLength={2000}
            placeholder="Ask about prices, CSA terms or your margin calls"
            className="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-neutral-400"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: DARK_GREEN }}
          >
            Send
          </button>
        </form>
      </div>
    </main>
  );
}
