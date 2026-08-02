"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";

import { StatusLight } from "@/components/status-light";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  postSimulateEvent,
  type SimulateEventResponse,
  type SimulateScenario,
} from "@/lib/api";
import { formatUsd } from "@/lib/format";

const SCENARIOS: { value: SimulateScenario; label: string; description: string }[] = [
  {
    value: "price_shock",
    label: "Price shock",
    description: "TSLA -12%, NVDA -10%, layered on real current prices.",
  },
  {
    value: "vol_spike",
    label: "Volatility spike",
    description: "BTC-USD -18%, ETH-USD -16%, SOL-USD -20%, layered on real current prices.",
  },
];

export default function SimulatePage() {
  const { data: session } = useSession();
  const canAct = session?.user.role === "approver";
  const [scenario, setScenario] = useState<SimulateScenario>("price_shock");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulateEventResponse | null>(null);

  const trigger = async () => {
    if (!session) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await postSimulateEvent(session.backendAccessToken, scenario);
      setResult(response);
    } catch {
      setError("Simulation failed -- is the API running?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-12">
      <h1 className="text-xl font-semibold">Simulate Event</h1>
      <p className="text-sm text-muted-foreground">
        Triggers the real orchestrator lifecycle for every real counterparty currently
        holding an affected ticker -- a genuine breach can produce a pending approval on
        the Approvals &amp; SLA page.
      </p>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-4">
          <Select value={scenario} onValueChange={(v) => setScenario(v as SimulateScenario)}>
            <SelectTrigger className="w-56">
              {/* Base UI's SelectValue echoes the raw value string unless
                  given explicit children -- without this it shows
                  "price_shock" instead of "Price shock". */}
              <SelectValue placeholder="Select scenario">
                {SCENARIOS.find((s) => s.value === scenario)?.label}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {SCENARIOS.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {SCENARIOS.find((s) => s.value === scenario)?.description}
          </p>
          <Button disabled={busy || !canAct} onClick={trigger} className="w-fit">
            {busy ? "Simulating..." : "Trigger simulation"}
          </Button>
          {!canAct && (
            <p className="text-xs text-muted-foreground">Viewer role -- read-only.</p>
          )}
          {error && <p className="text-sm text-status-danger">{error}</p>}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {result.reason}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {result.affected_counterparties.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No real counterparty currently holds an affected ticker.
              </p>
            )}
            {result.affected_counterparties.map((item) => (
              <div
                key={item.counterparty_id}
                className="flex items-center justify-between gap-4 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{item.counterparty_id}</span>
                  {item.error ? (
                    <span className="text-status-danger">{item.error}</span>
                  ) : (
                    <StatusLight
                      status={item.breached ? "breached" : "healthy"}
                      className="text-xs"
                    />
                  )}
                </div>
                <div className="flex items-center gap-3 font-mono text-xs">
                  {item.call_amount !== null && formatUsd(item.call_amount, "USD")}
                  {item.thread_id && (
                    <Link
                      href={`/margin-calls/${encodeURIComponent(item.thread_id)}/trace`}
                      className="text-primary underline underline-offset-4"
                    >
                      View trace &rarr;
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </main>
  );
}
