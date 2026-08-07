"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";

import {
  getExposureBoard,
  getMarginCallFeed,
  type ExposureBoardResponse,
  type MarginCallFeedResponse,
} from "@/lib/api";
import { formatUsdCompact } from "@/lib/format";
import { cn } from "@/lib/utils";

const TICKER_POLL_MS = 10_000;

const LIFECYCLE_STAGES = [
  { title: "Event", detail: "A real price move lands from the market feed." },
  { title: "Exposure", detail: "MTM, VM and IM are recomputed in deterministic Python." },
  { title: "Breach check", detail: "Exposure is checked against the CSA threshold, grounded via RAG." },
  { title: "Approval", detail: "A human reviews and approves before anything goes out." },
  { title: "Notify", detail: "The client is notified over Slack; an SLA timer starts." },
  { title: "Escalate", detail: "No response in time routes to ServiceNow automatically." },
];

function StatTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "danger" | "warning";
}) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl border border-neutral-200 bg-white px-4 py-5 text-center">
      <span
        className={cn(
          "font-mono text-3xl font-semibold text-black",
          tone === "danger" && "text-[#dc2626]",
          tone === "warning" && "text-[#b45309]",
        )}
      >
        {value}
      </span>
      <span className="text-xs text-neutral-500">{label}</span>
    </div>
  );
}

export default function DashboardPage() {
  const { data: session } = useSession();
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

  const counterparties = exposure?.counterparties ?? [];
  const breached = counterparties.filter((c) => c.status === "breached").length;
  const totalExposureUsd = counterparties
    .filter((c) => c.currency === "USD" && c.exposure !== null)
    .reduce((sum, c) => sum + (c.exposure ?? 0), 0);
  const totalCollateralUsd = counterparties
    .filter((c) => c.currency === "USD" && c.collateral_held !== null)
    .reduce((sum, c) => sum + (c.collateral_held ?? 0), 0);

  const awaitingApproval =
    feed?.margin_calls.filter((m) => m.status === "awaiting_approval").length ?? 0;
  const awaitingSla =
    feed?.margin_calls.filter((m) => m.status === "awaiting_sla_response").length ?? 0;
  const escalated = feed?.margin_calls.filter((m) => m.status === "escalated").length ?? 0;
  const needsAttention = awaitingApproval + awaitingSla + escalated;

  const displayName = session?.user?.name ?? "there";

  return (
    <main className="flex min-h-full flex-1 flex-col bg-white">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-12 px-6 py-12">
        <div className="flex flex-col gap-2">
          <h1 className="text-3xl font-semibold tracking-tight text-black sm:text-4xl">
            Welcome back, {displayName}
          </h1>
          <p className="max-w-md text-sm text-neutral-500">
            {needsAttention > 0
              ? `${needsAttention} margin call${needsAttention === 1 ? "" : "s"} need your attention right now.`
              : "Everything in the book is caught up -- nothing waiting on you."}
          </p>
        </div>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not reach the API -- is the backend running?
          </p>
        )}

        <section className="flex flex-col gap-3">
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
            Needs attention
          </span>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Breached counterparties" value={String(breached)} tone="danger" />
            <StatTile label="Awaiting approval" value={String(awaitingApproval)} tone="warning" />
            <StatTile label="Awaiting SLA response" value={String(awaitingSla)} tone="warning" />
            <StatTile label="Escalated" value={String(escalated)} tone="danger" />
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
            The book, live
          </span>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Counterparties tracked" value={String(counterparties.length)} />
            <StatTile
              label="Total exposure (USD)"
              value={formatUsdCompact(totalExposureUsd, "USD")}
            />
            <StatTile
              label="Collateral held (USD)"
              value={formatUsdCompact(totalCollateralUsd, "USD")}
            />
            <StatTile label="Runs evaluated" value={String(feed?.margin_calls.length ?? 0)} />
          </div>
        </section>

        <section className="flex flex-col gap-8 rounded-2xl border border-neutral-200 p-6 sm:p-8">
          <div className="flex flex-col gap-1">
            <h2 className="text-lg font-semibold text-black">How a call moves through this book</h2>
            <p className="text-sm text-neutral-500">Six steps, every one of them logged and auditable.</p>
          </div>

          {/* Horizontal flow on lg+: each stage is its own flex column so
              the connector (circle + line + arrowhead) and the text
              beneath it share one box -- keeps the arrow tips landing
              exactly at the next node with no separate pixel-math
              needed. */}
          <div className="relative hidden lg:flex">
            {LIFECYCLE_STAGES.map((stage, i) => (
              <div key={stage.title} className="flex flex-1 flex-col gap-3 pr-2">
                <div className="flex items-center">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-black font-mono text-sm font-semibold text-white">
                    {i + 1}
                  </div>
                  {i < LIFECYCLE_STAGES.length - 1 && (
                    <div className="relative ml-2 h-px flex-1 bg-neutral-200">
                      <svg
                        aria-hidden
                        width="8"
                        height="8"
                        viewBox="0 0 8 8"
                        className="absolute -right-px top-1/2 -translate-y-1/2"
                      >
                        <path d="M0 0L8 4L0 8Z" fill="#d4d4d4" />
                      </svg>
                    </div>
                  )}
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-black">{stage.title}</span>
                  <span className="text-xs leading-relaxed text-neutral-500">{stage.detail}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Vertical flow below lg: a connecting line runs down the left
              edge of the numbered circles, same visual language. */}
          <div className="relative flex flex-col lg:hidden">
            {LIFECYCLE_STAGES.map((stage, i) => (
              <div key={stage.title} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-black font-mono text-sm font-semibold text-white">
                    {i + 1}
                  </div>
                  {i < LIFECYCLE_STAGES.length - 1 && (
                    <div className="my-1 w-px flex-1 bg-neutral-200" />
                  )}
                </div>
                <div className="flex flex-col gap-1 pb-6">
                  <span className="text-sm font-medium text-black">{stage.title}</span>
                  <span className="text-xs leading-relaxed text-neutral-500">{stage.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
