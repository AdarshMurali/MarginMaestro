"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LifecycleStatusLight } from "@/components/lifecycle-status-light";
import { Card, CardContent } from "@/components/ui/card";
import { getMarginCallFeed, type MarginCallFeedResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function AgentTraceIndexPage() {
  const [feed, setFeed] = useState<MarginCallFeedResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMarginCallFeed()
      .then((result) => {
        if (!cancelled) setFeed(result);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-12">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">Agent Trace</h1>
        <p className="text-sm text-muted-foreground">
          Every run the orchestrator has evaluated -- pick one to watch the real step-by-step
          agent activity behind it.
        </p>
      </div>

      {error && (
        <p className="text-sm text-status-danger">
          Could not load recent runs -- is the API running?
        </p>
      )}
      {!error && !feed && <p className="text-sm text-muted-foreground">Loading...</p>}
      {feed && feed.margin_calls.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No runs yet -- trigger one from Simulate Event to see a trace here.
        </p>
      )}

      <Card>
        <CardContent className="flex flex-col divide-y divide-border p-0">
          {feed?.margin_calls.map((item) => (
            <Link
              key={item.thread_id}
              href={`/margin-calls/${encodeURIComponent(item.thread_id)}/trace`}
              className="flex items-center justify-between gap-4 px-4 py-3 text-sm transition-colors hover:bg-card"
            >
              <div className="flex items-center gap-3">
                <LifecycleStatusLight status={item.status} />
                <div className="flex flex-col">
                  <span className="font-medium">{item.counterparty_id}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {item.thread_id}
                  </span>
                </div>
              </div>
              <span className="text-xs text-muted-foreground">
                {formatDateTime(item.occurred_at)}
              </span>
            </Link>
          ))}
        </CardContent>
      </Card>
    </main>
  );
}
