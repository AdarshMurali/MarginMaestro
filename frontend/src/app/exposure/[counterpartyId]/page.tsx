"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { LifecycleStatusLight } from "@/components/lifecycle-status-light";
import { PriceChart } from "@/components/price-chart";
import { StatusLight } from "@/components/status-light";
import {
  getCounterpartyExposure,
  getMarginCallsForCounterparty,
  type CounterpartyExposure,
  type MarginCallSummary,
} from "@/lib/api";
import { formatDateTime, formatUsd } from "@/lib/format";
import { INK, LINE, MUTED, STATUS_AMBER, STATUS_GREEN, STATUS_RED, TEXT_AMBER, TEXT_RED } from "@/lib/brand";
import { cn } from "@/lib/utils";
import type { MarginCallLifecycleStatus } from "@/lib/api";

// A flat grey list reads as "nothing here needs you" even for an escalated
// call -- this ties each row's accent bar and amount color to the same
// severity buckets LifecycleStatusLight already uses (danger/warning/
// success/active), so the history reads at a glance instead of requiring
// everything to be read to tell them apart.
const HISTORY_SEVERITY: Record<MarginCallLifecycleStatus, { accent: string; amount: string }> = {
  escalated: { accent: STATUS_RED, amount: TEXT_RED },
  rejected: { accent: STATUS_AMBER, amount: TEXT_AMBER },
  disputed: { accent: STATUS_AMBER, amount: TEXT_AMBER },
  no_breach: { accent: STATUS_GREEN, amount: "#20463B" },
  sla_met: { accent: STATUS_GREEN, amount: "#20463B" },
  below_materiality: { accent: STATUS_GREEN, amount: "#20463B" },
  evaluating: { accent: "#D4D4D4", amount: INK },
  awaiting_approval: { accent: INK, amount: INK },
  awaiting_manager_approval: { accent: INK, amount: INK },
  awaiting_sla_response: { accent: INK, amount: INK },
};

function DetailTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl border border-neutral-200 bg-white px-4 py-5 text-center">
      <span className="font-mono text-xl font-semibold" style={{ color: INK }}>
        {value}
      </span>
      <span className="text-xs text-neutral-500">{label}</span>
    </div>
  );
}

export default function CounterpartyExposurePage() {
  const params = useParams<{ counterpartyId: string }>();
  // See margin-calls/[threadId]/trace: Next.js has not reliably decoded
  // encoded characters in dynamic-segment params here before -- decode
  // explicitly rather than trusting the framework.
  const counterpartyId = decodeURIComponent(params.counterpartyId);

  const [item, setItem] = useState<CounterpartyExposure | null>(null);
  const [error, setError] = useState(false);
  const [ticker, setTicker] = useState<string | null>(null);
  const [marginCalls, setMarginCalls] = useState<MarginCallSummary[] | null>(null);
  const [marginCallsError, setMarginCallsError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Only this counterparty's own board slice -- not the whole book's
    // (MM-61) -- so opening a detail page doesn't recompute every other
    // counterparty's price/CSA/VIX just to show this one. The reset-then-
    // fetch calls live inside this nested function (not the effect body
    // directly) so navigating from one counterparty to another clears the
    // previous counterparty's stale data instead of flashing it.
    async function load() {
      setItem(null);
      setError(false);
      try {
        const result = await getCounterpartyExposure(counterpartyId);
        if (cancelled) return;
        setItem(result);
        const firstTicker = result.positions[0]?.ticker;
        if (firstTicker) setTicker(firstTicker);
      } catch {
        if (!cancelled) setError(true);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [counterpartyId]);

  useEffect(() => {
    let cancelled = false;
    // Full history for this counterparty (MM-63) -- the Margin Calls list
    // page only shows whichever call is most urgent, plus a "+N more" link
    // that lands here.
    async function load() {
      setMarginCalls(null);
      setMarginCallsError(false);
      try {
        const result = await getMarginCallsForCounterparty(counterpartyId);
        if (!cancelled) setMarginCalls(result.margin_calls);
      } catch {
        if (!cancelled) setMarginCallsError(true);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [counterpartyId]);

  // Only this counterparty's own securities -- not the full book's ticker
  // universe -- so the chart dropdown can't wander into another book.
  const tickers = useMemo(() => item?.positions.map((p) => p.ticker) ?? [], [item]);

  return (
    <main className="flex min-h-full flex-1 flex-col bg-white">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-12">
        <Link href="/exposure" className="text-sm font-medium" style={{ color: INK }}>
          &larr; Back to positions &amp; exposure
        </Link>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not load this counterparty -- is the API running?
          </p>
        )}
        {!error && !item && <p className="text-sm text-neutral-500">Loading...</p>}

        {item && (
          <>
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between gap-4">
                <h1 className="text-2xl font-semibold tracking-tight text-black">
                  {item.counterparty_name}
                </h1>
                <span className="text-black">
                  <StatusLight status={item.status} />
                </span>
              </div>
              <span className="font-mono text-xs text-neutral-500">{item.counterparty_id}</span>
            </div>

            {item.detail ? (
              <p className="text-sm text-neutral-500">{item.detail}</p>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <DetailTile label="Exposure" value={formatUsd(item.exposure, item.currency)} />
                <DetailTile label="Threshold" value={formatUsd(item.threshold, item.currency)} />
                <DetailTile
                  label="Collateral held"
                  value={formatUsd(item.collateral_held, item.currency)}
                />
                <DetailTile label="Call amount" value={formatUsd(item.call_amount, item.currency)} />
              </div>
            )}

            {tickers.length > 0 && (
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-neutral-500">Price chart:</span>
                  <select
                    value={ticker ?? ""}
                    onChange={(e) => setTicker(e.target.value)}
                    className="rounded-lg border border-neutral-200 px-3 py-1.5 text-sm text-black outline-none focus:border-[#D3F770] focus:ring-2 focus:ring-[#D3F770]/40"
                  >
                    {tickers.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <PriceChart key={ticker ?? "none"} ticker={ticker} />
              </div>
            )}

            {item.positions.length > 0 && (
              <div className="flex flex-col gap-3">
                <span className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
                  Positions
                </span>
                <div className="overflow-x-auto rounded-xl border border-neutral-200">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                        <th className="px-4 py-2 font-medium">Ticker</th>
                        <th className="px-4 py-2 font-medium">Asset class</th>
                        <th className="px-4 py-2 text-right font-medium">Quantity</th>
                        <th className="px-4 py-2 text-right font-medium">Price</th>
                        <th className="px-4 py-2 text-right font-medium">MTM</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-neutral-100">
                      {item.positions.map((position) => (
                        <tr key={position.ticker} className="text-black">
                          <td className="px-4 py-2 font-mono">{position.ticker}</td>
                          <td className="px-4 py-2">{position.asset_class}</td>
                          <td className="px-4 py-2 text-right font-mono">
                            {position.quantity.toLocaleString()}
                          </td>
                          <td className="px-4 py-2 text-right font-mono">
                            {formatUsd(position.price, item.currency)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono">
                            {formatUsd(position.mtm, item.currency)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="flex flex-col gap-3">
              <h2 className="text-[17px] font-bold" style={{ color: INK }}>
                Margin call history
              </h2>
              {marginCallsError && (
                <p
                  className="rounded-[10px] border px-4 py-3 text-sm"
                  style={{ borderColor: "rgba(229,72,77,0.3)", backgroundColor: "rgba(229,72,77,0.08)", color: "#C42A30" }}
                >
                  Could not load margin call history.
                </p>
              )}
              {!marginCallsError && !marginCalls && (
                <p className="text-sm" style={{ color: MUTED }}>
                  Loading...
                </p>
              )}
              {marginCalls && marginCalls.length === 0 && (
                <p className="text-sm" style={{ color: MUTED }}>
                  No margin calls for this counterparty yet.
                </p>
              )}
              {marginCalls && marginCalls.length > 0 && (
                <div className="flex flex-col overflow-hidden rounded-[14px] border" style={{ borderColor: LINE }}>
                  {marginCalls.map((call, index) => {
                    const severity = HISTORY_SEVERITY[call.status];
                    return (
                      <Link
                        key={call.thread_id}
                        href={`/margin-calls/${encodeURIComponent(call.thread_id)}/trace`}
                        className={cn(
                          "grid grid-cols-[11rem_1fr_auto] items-center gap-4 py-4 pl-3.5 pr-4 text-sm transition-colors hover:bg-[#F7F7F7] sm:grid-cols-[11rem_1fr_auto_auto]",
                          index !== 0 && "border-t",
                        )}
                        style={{
                          borderColor: index !== 0 ? "#F0F0F0" : undefined,
                          borderLeft: `3px solid ${severity.accent}`,
                        }}
                      >
                        <LifecycleStatusLight status={call.status} />
                        <span className="min-w-0 truncate font-semibold" style={{ color: INK }}>
                          {call.reason}
                        </span>
                        <span
                          className="hidden text-right font-mono text-base font-bold sm:inline"
                          style={{ color: severity.amount }}
                        >
                          {formatUsd(call.call_amount, call.currency)}
                        </span>
                        <span className="whitespace-nowrap text-right text-xs" style={{ color: MUTED }}>
                          {formatDateTime(call.occurred_at)}
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </main>
  );
}
