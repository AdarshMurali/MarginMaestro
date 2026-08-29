"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LifecycleStatusLight } from "@/components/lifecycle-status-light";
import { getMarginCallBuckets, type MarginCallBucketFeedResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { DARK_GREEN } from "@/lib/brand";

// Fixed column template -- status pill | counterparty | date | arrow -- so
// every row's fields line up regardless of how long a status label or
// counterparty name is (found live: ad hoc flex groups let a long status
// label push the counterparty name's start position around row to row).
const ROW_GRID = "grid grid-cols-[10.5rem_1fr_11rem_5rem] items-center gap-4";

export default function AgentTraceIndexPage() {
  const [feed, setFeed] = useState<MarginCallBucketFeedResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Same bucketed-by-counterparty data as Margin Calls (MM-63) -- this
    // page's own job is narrower: pick a counterparty, watch the real
    // step-by-step agent activity behind its most recent run. Approval/
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
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-12">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-black">Agent Trace</h1>
          <p className="text-sm text-neutral-500">
            Every counterparty the orchestrator has evaluated, most recent activity first -- pick
            one to watch the real step-by-step agent activity behind it.
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
          <div className="flex flex-col rounded-xl border border-neutral-200">
            <div
              className={`${ROW_GRID} border-b border-neutral-100 px-4 py-2.5 text-xs font-medium tracking-wide text-neutral-400 uppercase`}
            >
              <span>Status</span>
              <span>Counterparty</span>
              <span>Occurred</span>
              <span className="text-right">Trace</span>
            </div>
            <div className="flex flex-col divide-y divide-neutral-100">
              {feed.buckets.map((bucket) => (
                <Link
                  key={bucket.counterparty_id}
                  href={`/margin-calls/${encodeURIComponent(bucket.latest.thread_id)}/trace`}
                  className={`${ROW_GRID} group px-4 py-3.5 text-sm transition-colors hover:bg-neutral-50`}
                >
                  <LifecycleStatusLight status={bucket.latest.status} />
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate font-medium text-black">
                      {bucket.counterparty_name}
                    </span>
                    <span className="truncate text-xs text-neutral-500">
                      {bucket.latest.reason}
                    </span>
                  </div>
                  <span className="font-mono text-xs text-neutral-500">
                    {formatDateTime(bucket.latest.occurred_at)}
                  </span>
                  <span
                    className="text-right text-xs font-medium opacity-0 transition-opacity group-hover:opacity-100"
                    style={{ color: DARK_GREEN }}
                  >
                    View &rarr;
                  </span>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
