"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LifecycleStatusLight } from "@/components/lifecycle-status-light";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getMarginCallFeed, type MarginCallFeedResponse, type MarginCallSummary } from "@/lib/api";
import { formatDateTime, formatUsd } from "@/lib/format";

function MarginCallCard({ item }: { item: MarginCallSummary }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">
          {item.counterparty_id}{" "}
          <span className="font-mono text-xs text-muted-foreground">({item.thread_id})</span>
        </CardTitle>
        <LifecycleStatusLight status={item.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <p className="text-muted-foreground">{item.reason}</p>
        <div className="grid grid-cols-2 gap-2 font-mono sm:grid-cols-4">
          <div>
            <div className="text-xs text-muted-foreground">Event</div>
            {item.event_type}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Call amount</div>
            {formatUsd(item.call_amount, item.currency)}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Approval</div>
            {item.approval_decision ?? "--"}
          </div>
          <div>
            <div className="text-xs text-muted-foreground">SLA outcome</div>
            {item.sla_outcome ?? "--"}
          </div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">{formatDateTime(item.occurred_at)}</span>
          <Link
            href={`/margin-calls/${encodeURIComponent(item.thread_id)}/trace`}
            className="text-xs text-primary underline underline-offset-4"
          >
            View agent trace &rarr;
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export default function MarginCallsPage() {
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
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-12">
      <h1 className="text-xl font-semibold">Margin Calls</h1>

      {error && (
        <p className="text-sm text-status-danger">
          Could not load the margin-call feed -- is the API running?
        </p>
      )}
      {!error && !feed && <p className="text-sm text-muted-foreground">Loading...</p>}
      {feed && feed.margin_calls.length === 0 && (
        <p className="text-sm text-muted-foreground">No margin calls have run yet.</p>
      )}

      <div className="flex flex-col gap-4">
        {feed?.margin_calls.map((item) => (
          <MarginCallCard key={item.thread_id} item={item} />
        ))}
      </div>
    </main>
  );
}
