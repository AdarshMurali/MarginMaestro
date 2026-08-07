"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LifecycleStatusLight } from "@/components/lifecycle-status-light";
import { getMarginCallBuckets, type MarginCallBucketFeedResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { DARK_GREEN } from "@/lib/brand";

export default function AgentTraceIndexPage() {
  const [feed, setFeed] = useState<MarginCallBucketFeedResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Same bucketed-by-counterparty data as Margin Calls (MM-63) -- this
    // page's own job is narrower: pick a counterparty, watch the real
    // step-by-step agent activity behind its most relevant run. Approval/
    // SLA/call-amount detail lives on the Margin Calls page, not here.
    getMarginCallBuckets()
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
    <main className="flex min-h-full flex-1 flex-col bg-white">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-12">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-black">Agent Trace</h1>
          <p className="text-sm text-neutral-500">
            Every counterparty the orchestrator has evaluated -- pick one to watch the real
            step-by-step agent activity behind its most relevant run.
          </p>
        </div>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not load recent runs -- is the API running?
          </p>
        )}
        {!error && !feed && <p className="text-sm text-neutral-500">Loading...</p>}
        {feed && feed.buckets.length === 0 && (
          <p className="text-sm text-neutral-500">
            No runs yet -- trigger one from Simulate Event to see a trace here.
          </p>
        )}

        {feed && feed.buckets.length > 0 && (
          <div className="flex flex-col divide-y divide-neutral-100 rounded-xl border border-neutral-200">
            {feed.buckets.map((bucket) => (
              <Link
                key={bucket.counterparty_id}
                href={`/margin-calls/${encodeURIComponent(bucket.latest.thread_id)}/trace`}
                className="group flex items-center justify-between gap-4 px-4 py-3 text-sm transition-colors hover:bg-neutral-50"
              >
                <div className="flex items-center gap-3">
                  <LifecycleStatusLight status={bucket.latest.status} />
                  <div className="flex flex-col">
                    <span className="font-medium text-black">{bucket.counterparty_name}</span>
                    <span className="text-xs text-neutral-500">{bucket.latest.reason}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-neutral-500">
                    {formatDateTime(bucket.latest.occurred_at)}
                  </span>
                  <span
                    className="text-xs font-medium opacity-0 transition-opacity group-hover:opacity-100"
                    style={{ color: DARK_GREEN }}
                  >
                    View trace &rarr;
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
