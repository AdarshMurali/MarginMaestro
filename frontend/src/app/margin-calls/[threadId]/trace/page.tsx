"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { AgentTrace } from "@/components/agent-trace";
import { Logo } from "@/components/logo";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getMarginCallTrace, type MarginCallTraceResponse } from "@/lib/api";

export default function MarginCallTracePage() {
  const params = useParams<{ threadId: string }>();
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
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-12">
      <Logo size={32} />
      <div className="flex flex-col gap-1">
        <Link href="/margin-calls" className="text-sm text-primary underline underline-offset-4">
          &larr; Back to margin calls
        </Link>
        <h1 className="text-xl font-semibold">Agent Trace</h1>
        <p className="font-mono text-sm text-muted-foreground">{threadId}</p>
      </div>

      {error && <p className="text-sm text-status-danger">Could not load this run&apos;s trace.</p>}
      {!error && !trace && <p className="text-sm text-muted-foreground">Loading...</p>}

      {trace && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {trace.steps.length} step{trace.steps.length === 1 ? "" : "s"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <AgentTrace steps={trace.steps} />
          </CardContent>
        </Card>
      )}
    </main>
  );
}
