"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LifecycleStatusLight } from "@/components/lifecycle-status-light";
import { getMarginCallBuckets, type MarginCallBucket, type MarginCallBucketFeedResponse } from "@/lib/api";
import { formatDateTime, formatUsd } from "@/lib/format";
import { DARK_GREEN } from "@/lib/brand";

function BucketCard({ bucket }: { bucket: MarginCallBucket }) {
  const call = bucket.latest;
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-neutral-200 p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-black">{bucket.counterparty_name}</span>
          <span className="font-mono text-xs text-neutral-500">{bucket.counterparty_id}</span>
        </div>
        <span className="text-black">
          <LifecycleStatusLight status={call.status} />
        </span>
      </div>

      <p className="text-sm text-neutral-600">{call.reason}</p>

      <div className="grid grid-cols-2 gap-3 font-mono text-xs sm:grid-cols-4">
        <div>
          <div className="text-neutral-400">Event</div>
          <div className="mt-0.5 text-black">{call.event_type}</div>
        </div>
        <div>
          <div className="text-neutral-400">Call amount</div>
          <div className="mt-0.5 text-black">{formatUsd(call.call_amount, call.currency)}</div>
        </div>
        <div>
          <div className="text-neutral-400">Approval</div>
          <div className="mt-0.5 text-black">{call.approval_decision ?? "--"}</div>
        </div>
        <div>
          <div className="text-neutral-400">SLA outcome</div>
          <div className="mt-0.5 text-black">{call.sla_outcome ?? "--"}</div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 border-t border-neutral-100 pt-3">
        <span className="text-xs text-neutral-500">{formatDateTime(call.occurred_at)}</span>
        <div className="flex items-center gap-4">
          {bucket.total_count > 1 && (
            <Link
              href={`/exposure/${encodeURIComponent(bucket.counterparty_id)}`}
              className="text-xs font-medium text-neutral-500 underline-offset-4 hover:underline"
            >
              +{bucket.total_count - 1} more for {bucket.counterparty_name} &rarr;
            </Link>
          )}
          <Link
            href={`/margin-calls/${encodeURIComponent(call.thread_id)}/trace`}
            className="text-xs font-medium underline-offset-4 hover:underline"
            style={{ color: DARK_GREEN }}
          >
            View agent trace &rarr;
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function MarginCallsPage() {
  const [feed, setFeed] = useState<MarginCallBucketFeedResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
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
          <h1 className="text-2xl font-semibold tracking-tight text-black">Margin Calls</h1>
          <p className="text-sm text-neutral-500">
            One row per counterparty -- whichever call needs attention most, with older resolved
            calls tucked behind it rather than cluttering the list. Full history lives on each
            counterparty&apos;s own page.
          </p>
        </div>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not load the margin-call feed -- is the API running?
          </p>
        )}
        {!error && !feed && <p className="text-sm text-neutral-500">Loading...</p>}
        {feed && feed.buckets.length === 0 && (
          <p className="text-sm text-neutral-500">No margin calls have run yet.</p>
        )}

        {feed && feed.buckets.length > 0 && (
          <div className="flex flex-col gap-4">
            {feed.buckets.map((bucket) => (
              <BucketCard key={bucket.counterparty_id} bucket={bucket} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
