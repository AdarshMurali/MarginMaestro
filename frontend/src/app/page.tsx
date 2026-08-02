"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LifecycleStatusLight } from "@/components/lifecycle-status-light";
import { Logo } from "@/components/logo";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getExposureBoard,
  getMarginCallFeed,
  type ExposureBoardResponse,
  type MarginCallFeedResponse,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const TICKER_POLL_MS = 10_000;

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "danger" | "warning";
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 pt-4">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span
          className={cn(
            "font-mono text-3xl font-semibold",
            tone === "danger" && "text-status-danger",
            tone === "warning" && "text-status-warning",
          )}
        >
          {value}
        </span>
      </CardContent>
    </Card>
  );
}

export default function Home() {
  const [exposure, setExposure] = useState<ExposureBoardResponse | null>(null);
  const [feed, setFeed] = useState<MarginCallFeedResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getExposureBoard()
      .then((result) => {
        if (!cancelled) setExposure(result);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const refetch = () => {
      getMarginCallFeed()
        .then((result) => {
          if (!cancelled) setFeed(result);
        })
        .catch(() => {
          if (!cancelled) setError(true);
        });
    };
    refetch();
    const id = setInterval(refetch, TICKER_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const breached = exposure?.counterparties.filter((c) => c.status === "breached").length ?? 0;
  const awaitingApproval =
    feed?.margin_calls.filter((m) => m.status === "awaiting_approval").length ?? 0;
  const awaitingSla =
    feed?.margin_calls.filter((m) => m.status === "awaiting_sla_response").length ?? 0;
  const escalated = feed?.margin_calls.filter((m) => m.status === "escalated").length ?? 0;

  const recentActivity = feed?.margin_calls.slice(0, 8) ?? [];

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-8 px-6 py-12">
      <Logo size={40} showTagline className="text-center" />

      {error && (
        <p className="text-center text-sm text-status-danger">
          Could not reach the API -- is the backend running?
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Breached counterparties" value={breached} tone="danger" />
        <Kpi label="Awaiting approval" value={awaitingApproval} tone="warning" />
        <Kpi label="Awaiting SLA response" value={awaitingSla} tone="warning" />
        <Kpi label="Escalated" value={escalated} tone="danger" />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Nothing here waits on paperwork
          </CardTitle>
          <Link href="/simulate" className={cn(buttonVariants({ size: "sm" }))}>
            Simulate an event &rarr;
          </Link>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Inject a real price shock or volatility spike and watch the whole margin-call
            lifecycle -- exposure, breach evaluation, approval, SLA -- unfold live from here.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Recent activity
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col divide-y divide-border p-0">
          {recentActivity.length === 0 && (
            <p className="px-4 py-3 text-sm text-muted-foreground">
              Nothing has run yet -- simulate an event above to see it appear here.
            </p>
          )}
          {recentActivity.map((item) => (
            <Link
              key={item.thread_id}
              href={`/margin-calls/${encodeURIComponent(item.thread_id)}/trace`}
              className="flex items-center justify-between gap-4 px-4 py-3 text-sm transition-colors hover:bg-card"
            >
              <div className="flex items-center gap-3">
                <LifecycleStatusLight status={item.status} />
                <div className="flex flex-col">
                  <span className="font-medium">{item.counterparty_id}</span>
                  <span className="text-xs text-muted-foreground">{item.reason}</span>
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
