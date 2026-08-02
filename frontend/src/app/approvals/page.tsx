"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getMarginCallFeed,
  postApproval,
  postCheckSla,
  postRespond,
  type MarginCallSummary,
} from "@/lib/api";
import { formatDateTime, formatUsd } from "@/lib/format";

function slaRemainingLabel(deadline: string): string {
  const diffMs = new Date(deadline).getTime() - Date.now();
  if (diffMs <= 0) return "overdue";
  const minutes = Math.round(diffMs / 60_000);
  return minutes < 1 ? "due any moment" : `${minutes}m remaining`;
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
      } catch {
        setError("Action failed -- is the API running?");
      } finally {
        setBusy(false);
      }
    },
    [amount, token, item.thread_id, onActed],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{item.counterparty_id}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <p className="text-muted-foreground">{item.reason}</p>
        <p className="font-mono">
          Call amount: <span className="text-primary">{formatUsd(item.call_amount, item.currency)}</span>
        </p>

        {error && <p className="text-status-danger">{error}</p>}
        {!canAct && (
          <p className="text-xs text-muted-foreground">Viewer role -- read-only.</p>
        )}

        {canAct && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={busy} onClick={() => act("approved")}>
                Approve
              </Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => act("rejected")}>
                Reject
              </Button>
              {!adjusting && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setAdjusting(true)}
                >
                  Adjust...
                </Button>
              )}
            </div>

            {adjusting && (
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  placeholder="Adjusted amount"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="max-w-40 font-mono"
                />
                <Button size="sm" disabled={busy} onClick={() => act("adjusted")}>
                  Confirm
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
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
      } catch {
        setError("Action failed -- is the API running?");
      } finally {
        setBusy(false);
      }
    },
    [token, item.thread_id, onActed],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{item.counterparty_id}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <p className="font-mono">
          Call amount: <span className="text-primary">{formatUsd(item.call_amount, item.currency)}</span>
        </p>
        {item.sla_deadline && (
          <p className="text-muted-foreground">
            Deadline: {formatDateTime(item.sla_deadline)} ({slaRemainingLabel(item.sla_deadline)})
          </p>
        )}

        {error && <p className="text-status-danger">{error}</p>}
        {!canAct && (
          <p className="text-xs text-muted-foreground">Viewer role -- read-only.</p>
        )}

        {canAct && (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={busy} onClick={() => act("respond")}>
              Simulate counterparty response
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => act("check")}>
              Check SLA deadline
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
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
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-8 px-6 py-12">
      <h1 className="text-xl font-semibold">Approvals &amp; SLA</h1>

      {error && (
        <p className="text-sm text-status-danger">Could not load margin calls -- is the API running?</p>
      )}
      {!error && !items && <p className="text-sm text-muted-foreground">Loading...</p>}

      {items && (
        <>
          <section className="flex flex-col gap-3">
            <h2 className="text-sm font-medium text-muted-foreground">
              Awaiting approval ({awaitingApproval.length})
            </h2>
            {awaitingApproval.length === 0 && (
              <p className="text-sm text-muted-foreground">Nothing awaiting approval.</p>
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
            <h2 className="text-sm font-medium text-muted-foreground">
              Awaiting SLA response ({awaitingSla.length})
            </h2>
            {awaitingSla.length === 0 && (
              <p className="text-sm text-muted-foreground">Nothing awaiting an SLA response.</p>
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
    </main>
  );
}
