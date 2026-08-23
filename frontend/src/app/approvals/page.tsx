"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";

import {
  getMarginCallFeed,
  postApproval,
  postCheckSla,
  postRespond,
  type MarginCallSummary,
} from "@/lib/api";
import { formatDateTime, formatUsd } from "@/lib/format";
import { DARK_GREEN, LIGHT_GREEN } from "@/lib/brand";

function slaRemainingLabel(deadline: string): string {
  const diffMs = new Date(deadline).getTime() - Date.now();
  if (diffMs <= 0) return "overdue";
  const minutes = Math.round(diffMs / 60_000);
  return minutes < 1 ? "due any moment" : `${minutes}m remaining`;
}

function PrimaryButton({
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="rounded-full px-4 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      style={{ backgroundColor: LIGHT_GREEN }}
    >
      {children}
    </button>
  );
}

function OutlineButton({
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="rounded-full border border-neutral-200 px-4 py-1.5 text-sm font-medium text-black transition-colors hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function ApprovalCard({
  item,
  token,
  canAct,
  onActed,
}: {
  item: MarginCallSummary;
  token: string;
  canAct: boolean;
  onActed: () => void;
}) {
  const [adjusting, setAdjusting] = useState(false);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = useCallback(
    async (decision: "approved" | "rejected" | "adjusted") => {
      setError(null);
      setBusy(true);
      try {
        const adjustedAmount = decision === "adjusted" ? Number(amount) : undefined;
        if (decision === "adjusted" && (!amount || Number.isNaN(adjustedAmount))) {
          throw new Error("Enter a valid adjusted amount first.");
        }
        await postApproval(token, item.thread_id, decision, adjustedAmount);
        onActed();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Action failed -- is the API running?");
      } finally {
        setBusy(false);
      }
    },
    [amount, token, item.thread_id, onActed],
  );

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-5 text-sm">
      <span className="font-medium text-black">{item.counterparty_id}</span>
      <p className="text-neutral-500">{item.reason}</p>
      <p className="font-mono text-black">
        Call amount:{" "}
        <span style={{ color: DARK_GREEN }}>{formatUsd(item.call_amount, item.currency)}</span>
      </p>

      {error && <p className="text-red-600">{error}</p>}
      {!canAct && <p className="text-xs text-neutral-400">Viewer role -- read-only.</p>}

      {canAct && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <PrimaryButton disabled={busy} onClick={() => act("approved")}>
              Approve
            </PrimaryButton>
            <OutlineButton disabled={busy} onClick={() => act("rejected")}>
              Reject
            </OutlineButton>
            {!adjusting && (
              <OutlineButton disabled={busy} onClick={() => setAdjusting(true)}>
                Adjust...
              </OutlineButton>
            )}
          </div>

          {adjusting && (
            <div className="flex items-center gap-2">
              <input
                type="number"
                placeholder="Adjusted amount"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-40 rounded-lg border border-neutral-200 px-3 py-1.5 font-mono text-sm text-black outline-none focus:border-[#D3F770] focus:ring-2 focus:ring-[#D3F770]/40"
              />
              <PrimaryButton disabled={busy} onClick={() => act("adjusted")}>
                Confirm
              </PrimaryButton>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SlaCard({
  item,
  token,
  canAct,
  onActed,
}: {
  item: MarginCallSummary;
  token: string;
  canAct: boolean;
  onActed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = useCallback(
    async (action: "respond" | "check") => {
      setError(null);
      setBusy(true);
      try {
        if (action === "respond") await postRespond(token, item.thread_id);
        else await postCheckSla(token, item.thread_id);
        onActed();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Action failed -- is the API running?");
      } finally {
        setBusy(false);
      }
    },
    [token, item.thread_id, onActed],
  );

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-5 text-sm">
      <span className="font-medium text-black">{item.counterparty_id}</span>
      <p className="font-mono text-black">
        Call amount:{" "}
        <span style={{ color: DARK_GREEN }}>{formatUsd(item.call_amount, item.currency)}</span>
      </p>
      {item.sla_deadline && (
        <p className="text-neutral-500">
          Deadline: {formatDateTime(item.sla_deadline)} ({slaRemainingLabel(item.sla_deadline)})
        </p>
      )}

      {error && <p className="text-red-600">{error}</p>}
      {!canAct && <p className="text-xs text-neutral-400">Viewer role -- read-only.</p>}

      {canAct && (
        <div className="flex flex-wrap items-center gap-2">
          <PrimaryButton disabled={busy} onClick={() => act("respond")}>
            Simulate counterparty response
          </PrimaryButton>
          <OutlineButton disabled={busy} onClick={() => act("check")}>
            Check SLA deadline
          </OutlineButton>
        </div>
      )}
    </div>
  );
}

export default function ApprovalsPage() {
  const { data: session } = useSession();
  const [items, setItems] = useState<MarginCallSummary[] | null>(null);
  const [error, setError] = useState(false);

  const refetch = useCallback(() => {
    getMarginCallFeed()
      .then((result) => setItems(result.margin_calls))
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const awaitingApproval = items?.filter((item) => item.status === "awaiting_approval") ?? [];
  const awaitingSla = items?.filter((item) => item.status === "awaiting_sla_response") ?? [];
  const token = session?.backendAccessToken ?? "";
  const canAct = session?.user.role === "approver";

  return (
    <main className="flex min-h-full flex-1 flex-col bg-white">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-8 px-6 py-12">
        <h1 className="text-2xl font-semibold tracking-tight text-black">Approvals &amp; SLA</h1>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not load margin calls -- is the API running?
          </p>
        )}
        {!error && !items && <p className="text-sm text-neutral-500">Loading...</p>}

        {items && (
          <>
            <section className="flex flex-col gap-3">
              <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
                Awaiting approval ({awaitingApproval.length})
              </h2>
              {awaitingApproval.length === 0 && (
                <p className="text-sm text-neutral-500">Nothing awaiting approval.</p>
              )}
              {awaitingApproval.map((item) => (
                <ApprovalCard
                  key={item.thread_id}
                  item={item}
                  token={token}
                  canAct={canAct}
                  onActed={refetch}
                />
              ))}
            </section>

            <section className="flex flex-col gap-3">
              <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
                Awaiting SLA response ({awaitingSla.length})
              </h2>
              {awaitingSla.length === 0 && (
                <p className="text-sm text-neutral-500">Nothing awaiting an SLA response.</p>
              )}
              {awaitingSla.map((item) => (
                <SlaCard
                  key={item.thread_id}
                  item={item}
                  token={token}
                  canAct={canAct}
                  onActed={refetch}
                />
              ))}
            </section>
          </>
        )}
      </div>
    </main>
  );
}
