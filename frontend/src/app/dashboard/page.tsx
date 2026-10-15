"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";

import {
  getExposureBoard,
  getMarginCallFeed,
  type CounterpartyExposure,
  type ExposureBoardResponse,
  type MarginCallFeedResponse,
  type MarginCallLifecycleStatus,
  type MarginCallSummary,
} from "@/lib/api";
import { LiveBadge } from "@/components/live-badge";
import {
  INK,
  STATUS_AMBER,
  STATUS_RED,
  TEXT_AMBER,
  TEXT_RED,
} from "@/lib/brand";
import { formatUsd, formatUsdCompact } from "@/lib/format";
import { useLiveCallStatus } from "@/lib/use-live-call-status";
import { cn } from "@/lib/utils";

const FEED_POLL_MS = 10_000;
const CLOCK_TICK_MS = 30_000;
const QUEUE_LIMIT = 8;

// Home page, White Paper theme ("E4", 2026-10-15). Every figure comes from
// the API as-is; the page only sorts, filters and formats (golden rule 6).

type QueueFilter = "all" | "needs_me" | "with_client" | "escalated";

const OPEN_STATUSES: MarginCallLifecycleStatus[] = [
  "awaiting_approval",
  "awaiting_manager_approval",
  "awaiting_sla_response",
  "escalated",
];

const FILTERS: { key: QueueFilter; label: string; match: (s: MarginCallLifecycleStatus) => boolean }[] = [
  { key: "all", label: "All", match: () => true },
  {
    key: "needs_me",
    label: "Needs me",
    match: (s) => s === "awaiting_approval" || s === "awaiting_manager_approval",
  },
  { key: "with_client", label: "With client", match: (s) => s === "awaiting_sla_response" },
  { key: "escalated", label: "Escalated", match: (s) => s === "escalated" },
];

// Lifecycle bar under each queue row: breach -> approval -> sign-off ->
// notified -> SLA running -> escalation. `current` is the step in progress.
const STAGE: Record<string, { label: string; current: number; alarm?: boolean }> = {
  awaiting_approval: { label: "Needs your approval", current: 1 },
  awaiting_manager_approval: { label: "Manager sign-off", current: 2 },
  awaiting_sla_response: { label: "With client · SLA running", current: 4 },
  escalated: { label: "Escalated to ServiceNow", current: 5, alarm: true },
};

const HOW_IT_WORKS = [
  {
    title: "Reads the agreement",
    body: "Thresholds come from each CSA, with the clause cited.",
    tech: "Gemini · RAG",
  },
  {
    title: "Calculates in code",
    body: "Every amount on this page is computed, never generated.",
    tech: "Python calc engine",
  },
  {
    title: "Waits for you",
    body: "No call reaches a client until a person approves it.",
    tech: "LangGraph · Cloud Run",
  },
];

function minutesBetween(fromIso: string, toMs: number): number {
  return Math.round((toMs - new Date(fromIso).getTime()) / 60_000);
}

function formatMinutes(total: number): string {
  if (total < 60) return `${total}m`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

interface QueueRow {
  call: MarginCallSummary;
  name: string;
  stage: (typeof STAGE)[string];
  timeText: string;
  urgent: boolean;
  clockPct: number | null;
  sortKey: number;
  action: { label: string; href: string; primary: boolean };
}

function buildRow(call: MarginCallSummary, name: string, now: number): QueueRow {
  const stage = STAGE[call.status];
  let timeText = "";
  let urgent = false;
  let clockPct: number | null = null;
  let sortKey = Number.MAX_SAFE_INTEGER;

  if (call.status === "awaiting_sla_response" && call.sla_deadline) {
    const left = -minutesBetween(call.sla_deadline, now);
    sortKey = left; // soonest deadline first
    if (left <= 0) {
      timeText = "deadline passed";
      urgent = true;
      clockPct = 100;
    } else {
      urgent = left <= 30;
      const windowMin = call.notification_sent_at
        ? minutesBetween(call.notification_sent_at, new Date(call.sla_deadline).getTime())
        : null;
      timeText = windowMin ? `${formatMinutes(left)} left of ${formatMinutes(windowMin)}` : `${formatMinutes(left)} left`;
      clockPct = windowMin ? Math.min(100, Math.max(0, ((windowMin - left) / windowMin) * 100)) : null;
    }
  } else if (call.status === "escalated") {
    timeText = `since ${new Date(call.occurred_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
    sortKey = Number.MAX_SAFE_INTEGER - 1;
  } else {
    const waited = Math.max(0, minutesBetween(call.occurred_at, now));
    timeText = `waiting ${formatMinutes(waited)}`;
    sortKey = 1_000_000 - waited; // after live SLA clocks, oldest approval first
  }

  const action =
    call.status === "awaiting_approval"
      ? { label: "Review", href: "/approvals", primary: true }
      : call.status === "awaiting_manager_approval"
        ? { label: "Sign off", href: "/approvals", primary: true }
        : call.status === "awaiting_sla_response"
          ? { label: urgent ? "Chase" : "View", href: "/approvals", primary: urgent }
          : { label: "Trace", href: `/margin-calls/${call.thread_id}/trace`, primary: false };

  return { call, name, stage, timeText, urgent, clockPct, sortKey, action };
}

function Kpi({ label, value, sub }: { label: string; value: string | null; sub: string }) {
  return (
    <div className="flex flex-col gap-1.5 border-b border-r border-[#E5E5E5] px-5 py-4">
      <span className="text-xs font-semibold text-[#5C5C5C]">{label}</span>
      <span className="font-mono text-[28px] font-medium tracking-tight text-[#0A0A0A]">
        {value ?? <span className="animate-pulse text-neutral-300">—</span>}
      </span>
      <span className="text-xs text-[#5C5C5C]">{sub}</span>
    </div>
  );
}

function StageBar({ current, alarm }: { current: number; alarm?: boolean }) {
  return (
    <div className="flex gap-[3px]" aria-label={`Stage ${current + 1} of 6`}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className="h-1 flex-1 rounded-sm"
          style={{
            background: i < current ? INK : i === current ? (alarm ? STATUS_RED : INK) : "#E5E5E5",
            opacity: i === current && !alarm ? 0.45 : 1,
          }}
        />
      ))}
    </div>
  );
}

function RunwayRow({ cp, scale }: { cp: CounterpartyExposure; scale: number }) {
  // Display only: how far exposure sits below (or above) the CSA threshold,
  // both values straight from the API.
  const headroom = (cp.threshold ?? 0) - (cp.exposure ?? 0);
  const width = scale > 0 ? (Math.abs(headroom) / scale) * 78 : 0;
  const breached = cp.status === "breached";
  const atRisk = cp.status === "at_risk";
  return (
    <div className="grid grid-cols-[190px_1fr_110px_150px] items-center gap-4 border-t border-[#F5F5F5] py-2.5">
      <Link href={`/exposure/${cp.counterparty_id}`} className="min-w-0 hover:underline">
        <div className="truncate font-semibold text-[#0A0A0A]">{cp.counterparty_name}</div>
        <div className="text-xs text-[#5C5C5C]">{cp.counterparty_id}</div>
      </Link>
      <div className="relative h-[18px]">
        {headroom > 0 ? (
          <div
            className="absolute inset-y-0 rounded-l"
            style={{ left: `${78 - width}%`, width: `${width}%`, background: atRisk ? STATUS_AMBER : "#2B2B2B" }}
          />
        ) : (
          <div
            className="absolute inset-y-0 rounded-r"
            style={{ left: "78%", width: `${Math.min(width, 22)}%`, background: STATUS_RED }}
          />
        )}
        <div className="absolute -inset-y-1 w-0.5 bg-[#0A0A0A]" style={{ left: "78%" }} />
      </div>
      <span
        className="text-right font-mono text-sm"
        style={{ color: breached ? TEXT_RED : atRisk ? TEXT_AMBER : INK, fontWeight: breached || atRisk ? 600 : 400 }}
      >
        {headroom < 0 ? "−" : ""}
        {formatUsdCompact(Math.abs(headroom), cp.currency)}
      </span>
      <span className="text-sm" style={{ color: breached ? TEXT_RED : atRisk ? INK : "#5C5C5C", fontWeight: breached || atRisk ? 600 : 400 }}>
        {breached
          ? cp.call_amount !== null
            ? `Call · ${formatUsdCompact(cp.call_amount, cp.currency)}`
            : "Over threshold"
          : atRisk
            ? "At risk"
            : "Healthy"}
      </span>
    </div>
  );
}

export default function DashboardPage() {
  const { data: session } = useSession();
  const [exposure, setExposure] = useState<ExposureBoardResponse | null>(null);
  const [feed, setFeed] = useState<MarginCallFeedResponse | null>(null);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState<QueueFilter>("all");
  const [now, setNow] = useState(() => Date.now());

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

  const refetchFeed = useCallback(() => {
    getMarginCallFeed()
      .then(setFeed)
      .catch(() => setError(true));
  }, []);

  const live = useLiveCallStatus(refetchFeed);

  useEffect(() => {
    refetchFeed();
    if (live) return;
    const id = setInterval(refetchFeed, FEED_POLL_MS);
    return () => clearInterval(id);
  }, [refetchFeed, live]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => clearInterval(id);
  }, []);

  const counterparties = useMemo(() => exposure?.counterparties ?? [], [exposure]);
  const names = useMemo(
    () => new Map(counterparties.map((c) => [c.counterparty_id, c.counterparty_name])),
    [counterparties],
  );

  const openCalls = useMemo(
    () => (feed?.margin_calls ?? []).filter((m) => OPEN_STATUSES.includes(m.status)),
    [feed],
  );
  const rows = useMemo(
    () =>
      openCalls
        .map((c) => buildRow(c, names.get(c.counterparty_id) ?? c.counterparty_id, now))
        .sort((a, b) => a.sortKey - b.sortKey),
    [openCalls, names, now],
  );
  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.key, rows.filter((r) => f.match(r.call.status)).length])),
    [rows],
  ) as Record<QueueFilter, number>;
  const visibleRows = rows
    .filter((r) => FILTERS.find((f) => f.key === filter)!.match(r.call.status))
    .slice(0, QUEUE_LIMIT);

  const decisions = counts.needs_me ?? 0;
  const nextDeadline = rows.find((r) => r.call.status === "awaiting_sla_response" && r.sortKey > 0);

  const usd = counterparties.filter((c) => c.currency === "USD");
  const grossExposure = usd.reduce((sum, c) => sum + (c.exposure ?? 0), 0);
  const collateralHeld = usd.reduce((sum, c) => sum + (c.collateral_held ?? 0), 0);
  const breached = counterparties.filter((c) => c.status === "breached").length;
  const atRisk = counterparties.filter((c) => c.status === "at_risk").length;
  const escalated = counts.escalated ?? 0;

  const runway = counterparties
    .filter((c) => c.exposure !== null && c.threshold !== null)
    .sort((a, b) => (a.threshold! - a.exposure!) - (b.threshold! - b.exposure!));
  const runwayScale = Math.max(0, ...runway.map((c) => Math.abs(c.threshold! - c.exposure!)));

  const firstName = session?.user?.name?.split(" ")[0];
  const hour = new Date(now).getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <main className="flex min-h-full flex-1 flex-col bg-white text-[#0A0A0A]">
      <div className="mx-auto flex w-full max-w-[1360px] flex-col gap-7 px-6 pb-12 pt-11">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex max-w-3xl flex-col gap-3">
            <h1 className="text-4xl font-extrabold leading-[1.05] tracking-[-0.035em] sm:text-[44px]">
              Stop reading documents.
              <br />
              <span className="text-[#8A8A8A]">Start making decisions.</span>
            </h1>
            <p className="text-base text-[#3D3D3D]">
              {feed === null ? (
                "Checking the book…"
              ) : (
                <>
                  {greeting}
                  {firstName ? `, ${firstName}` : ""}.{" "}
                  {decisions > 0 ? (
                    <>
                      <strong>
                        {decisions} decision{decisions === 1 ? "" : "s"}
                      </strong>{" "}
                      {decisions === 1 ? "is" : "are"} ready for you
                    </>
                  ) : (
                    "Nothing is waiting on you"
                  )}
                  {nextDeadline
                    ? `, and the next client deadline is in ${formatMinutes(nextDeadline.sortKey)}.`
                    : "."}
                </>
              )}
            </p>
          </div>
          <div className="flex flex-wrap gap-2.5">
            <Link
              href="/simulate"
              className="inline-flex min-h-11 items-center rounded-[10px] border border-[#D4D4D4] px-4 font-semibold hover:bg-[#F7F7F7]"
            >
              Simulate event
            </Link>
            <Link
              href="/approvals"
              className="inline-flex min-h-11 items-center rounded-[10px] bg-[#0A0A0A] px-[18px] font-bold text-white hover:bg-[#262626]"
            >
              Review queue
            </Link>
          </div>
        </div>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Could not reach the API. Is the backend running?
          </p>
        )}

        <section
          aria-label="Key figures"
          className="-mb-px grid grid-cols-2 overflow-hidden rounded-[14px] border-l border-t border-[#E5E5E5] sm:grid-cols-3 lg:grid-cols-5"
        >
          <Kpi
            label="Gross exposure"
            value={exposure && formatUsdCompact(grossExposure, "USD")}
            sub={exposure ? `${counterparties.length} counterparties` : ""}
          />
          <Kpi
            label="Collateral held"
            value={exposure && formatUsdCompact(collateralHeld, "USD")}
            sub="after haircuts"
          />
          <Kpi label="Breached" value={exposure && String(breached)} sub={`${atRisk} more at risk`} />
          <Kpi label="Open calls" value={feed && String(rows.length)} sub={`${decisions} need a decision`} />
          <Kpi label="Escalated" value={feed && String(escalated)} sub="ServiceNow incidents" />
        </section>

        <section aria-labelledby="queue" className="flex flex-col rounded-[14px] border border-[#E5E5E5]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E5E5E5] px-5 py-4">
            <div className="flex items-center gap-4">
              <h2 id="queue" className="text-[17px] font-bold">
                Action queue
              </h2>
              <LiveBadge live={live} pollSeconds={FEED_POLL_MS / 1000} />
            </div>
            <div role="group" aria-label="Filter queue" className="flex gap-1 rounded-[10px] bg-[#F4F4F4] p-[3px]">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  aria-pressed={filter === f.key}
                  onClick={() => setFilter(f.key)}
                  className={cn(
                    "min-h-8 rounded-lg px-3 text-[13px] font-semibold",
                    filter === f.key ? "bg-white text-[#0A0A0A] shadow-sm" : "text-[#5C5C5C] hover:text-[#0A0A0A]",
                  )}
                >
                  {f.label} {counts[f.key] ?? 0}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <div className="min-w-[720px]">
              {feed === null ? (
                <p className="px-5 py-6 text-sm text-[#5C5C5C]">Loading the queue…</p>
              ) : visibleRows.length === 0 ? (
                <p className="px-5 py-6 text-sm text-[#5C5C5C]">Nothing here. The book is caught up.</p>
              ) : (
                visibleRows.map((r) => (
                  <div
                    key={r.call.thread_id}
                    className="grid grid-cols-[minmax(200px,1.6fr)_minmax(170px,1.3fr)_minmax(110px,0.9fr)_minmax(140px,1fr)_116px] items-center gap-4 border-b border-[#F0F0F0] px-5 py-3.5 last:border-b-0"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span
                        aria-hidden
                        className={cn(
                          "inline-flex h-9 w-9 flex-none items-center justify-center rounded-[10px] text-xs font-bold",
                          r.stage.alarm || r.urgent ? "bg-[#FDECEC] text-[#B4232A]" : "bg-[#F2F2F2] text-[#0A0A0A]",
                        )}
                      >
                        {initials(r.name)}
                      </span>
                      <div className="min-w-0">
                        <div className="truncate font-bold">{r.name}</div>
                        <div className="truncate text-xs text-[#5C5C5C]">
                          {r.call.counterparty_id} · {r.call.reason}
                        </div>
                      </div>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <span className="text-[13px] font-semibold">{r.stage.label}</span>
                      <StageBar current={r.stage.current} alarm={r.stage.alarm} />
                    </div>
                    <span className="text-right font-mono font-medium">
                      {formatUsd(r.call.call_amount, r.call.currency)}
                    </span>
                    <div className="flex flex-col gap-1.5">
                      <span
                        className="font-mono text-[13px]"
                        style={{ color: r.urgent ? TEXT_RED : "#3D3D3D", fontWeight: r.urgent ? 600 : 400 }}
                      >
                        {r.timeText}
                      </span>
                      {r.clockPct !== null && (
                        <div className="relative h-1 rounded-sm bg-[#EFEFEF]">
                          <div
                            className="absolute inset-y-0 left-0 rounded-sm"
                            style={{ width: `${r.clockPct}%`, background: r.urgent ? STATUS_RED : INK }}
                          />
                        </div>
                      )}
                    </div>
                    <Link
                      href={r.action.href}
                      className={cn(
                        "inline-flex min-h-[38px] min-w-24 items-center justify-center justify-self-end rounded-[9px] px-3.5 text-[13px] font-bold",
                        r.action.primary
                          ? "bg-[#0A0A0A] text-white hover:bg-[#262626]"
                          : "border border-[#D4D4D4] text-[#0A0A0A] hover:bg-[#F7F7F7]",
                      )}
                    >
                      {r.action.label}
                    </Link>
                  </div>
                ))
              )}
            </div>
          </div>
          {rows.length > QUEUE_LIMIT && (
            <Link href="/approvals" className="border-t border-[#E5E5E5] px-5 py-3 text-sm font-semibold hover:underline">
              See all {rows.length} open calls
            </Link>
          )}
        </section>

        <section aria-labelledby="runway" className="rounded-[14px] border border-[#E5E5E5] px-5 pb-3.5 pt-4">
          <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-3">
            <div>
              <h2 id="runway" className="text-[17px] font-bold">
                Runway to the next call
              </h2>
              <p className="mt-1 text-xs text-[#5C5C5C]">
                Headroom left before each CSA threshold, or already over it · closest to a call first
              </p>
            </div>
            <span className="flex gap-4 text-xs text-[#5C5C5C]">
              <span>
                <span style={{ color: "#2B2B2B" }}>▮</span> headroom
              </span>
              <span>
                <span style={{ color: STATUS_AMBER }}>▮</span> at risk
              </span>
              <span>
                <span style={{ color: STATUS_RED }}>▮</span> over threshold
              </span>
            </span>
          </div>
          <div className="overflow-x-auto">
            <div className="min-w-[760px]">
              <div className="grid grid-cols-[190px_1fr_110px_150px] gap-4 py-1.5 text-[11px] text-[#5C5C5C]">
                <span />
                <div className="relative h-3.5">
                  <span className="absolute left-0">more headroom</span>
                  <span className="absolute -translate-x-1/2 font-bold text-[#0A0A0A]" style={{ left: "78%" }}>
                    threshold
                  </span>
                  <span className="absolute right-0">over</span>
                </div>
                <span className="text-right">Headroom</span>
                <span>Status</span>
              </div>
              {exposure === null ? (
                <p className="py-4 text-sm text-[#5C5C5C]">Loading exposure…</p>
              ) : runway.length === 0 ? (
                <p className="py-4 text-sm text-[#5C5C5C]">No counterparties with exposure yet.</p>
              ) : (
                runway.map((cp) => <RunwayRow key={cp.counterparty_id} cp={cp} scale={runwayScale} />)
              )}
            </div>
          </div>
        </section>

        <section
          aria-labelledby="how"
          className="grid grid-cols-1 gap-6 border-t border-[#E5E5E5] pt-5 sm:grid-cols-3"
        >
          <h2 id="how" className="sr-only">
            How it works
          </h2>
          {HOW_IT_WORKS.map((h) => (
            <div key={h.title} className="flex flex-col gap-1">
              <span className="font-extrabold">{h.title}</span>
              <span className="text-[13px] text-[#3D3D3D]">{h.body}</span>
              <span className="font-mono text-[11px] text-[#5C5C5C]">{h.tech}</span>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
