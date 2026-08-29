"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { AgentTrace } from "@/components/agent-trace";
import { getMarginCallTrace, type MarginCallTraceResponse } from "@/lib/api";
import { DARK_GREEN } from "@/lib/brand";

export default function MarginCallTracePage() {
  const params = useParams<{ threadId: string }>();
  const router = useRouter();
  // Next.js does not reliably decode dynamic-segment params containing
  // encoded characters (observed live: a thread_id's "%3A" survived into
  // params.threadId undecoded, silently double-encoding the API request
  // and 404ing) -- decode explicitly rather than trusting the framework.
  const threadId = decodeURIComponent(params.threadId);
  const [trace, setTrace] = useState<MarginCallTraceResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMarginCallTrace(threadId)
      .then((result) => {
        if (!cancelled) setTrace(result);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [threadId]);

  return (
    <main className="flex min-h-full flex-1 flex-col bg-white">
      <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-6 px-6 py-12">
        <div className="flex flex-col gap-1">
          {/* Three different places link into this page (Margin Calls, Agent
              Trace, a counterparty's margin-call-history section) -- a fixed
              destination would be wrong from at least two of them, so this
              goes back to wherever the user actually came from. */}
          <button
            onClick={() => router.back()}
            className="w-fit text-sm font-medium underline-offset-4 hover:underline"
            style={{ color: DARK_GREEN }}
          >
            &larr; Back
          </button>
          <h1 className="text-2xl font-semibold tracking-tight text-black">Agent Trace</h1>
          <p className="font-mono text-xs text-neutral-500">{threadId}</p>
        </div>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not load this run&apos;s trace.
          </p>
        )}
        {!error && !trace && <p className="text-sm text-neutral-500">Loading...</p>}

        {trace && (
          <div className="rounded-xl border border-neutral-200 p-6">
            <span className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
              {trace.steps.length} step{trace.steps.length === 1 ? "" : "s"}
            </span>
            <div className="mt-4">
              <AgentTrace steps={trace.steps} />
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
