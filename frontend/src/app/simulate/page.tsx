"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";

import { StatusLight } from "@/components/status-light";
import {
  getMarketUniverse,
  postSimulateEvent,
  type SimulateEventKind,
  type SimulateEventResponse,
} from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { DARK_GREEN, LIGHT_GREEN } from "@/lib/brand";

const EVENT_KINDS: { value: SimulateEventKind; label: string }[] = [
  { value: "price_shock", label: "Price shock" },
  { value: "vol_spike", label: "Volatility spike" },
];

export default function SimulatePage() {
  const { data: session } = useSession();
  const canAct = session?.user.role === "approver";
  const [eventType, setEventType] = useState<SimulateEventKind>("price_shock");
  const [tickers, setTickers] = useState<string[]>([]);
  const [ticker, setTicker] = useState<string>("");
  const [pctChangeInput, setPctChangeInput] = useState("-10");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulateEventResponse | null>(null);

  useEffect(() => {
    getMarketUniverse()
      .then((res) => {
        setTickers(res.tickers);
        setTicker((current) => current || res.tickers[0] || "");
      })
      .catch(() => setError("Couldn't load the ticker universe -- is the API running?"));
  }, []);

  const pctChange = Number(pctChangeInput);
  const canSubmit =
    canAct && ticker !== "" && pctChangeInput.trim() !== "" && !Number.isNaN(pctChange);

  const trigger = async () => {
    if (!session || !canSubmit) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await postSimulateEvent(
        session.backendAccessToken,
        eventType,
        ticker,
        pctChange,
      );
      setResult(response);
    } catch {
      setError("Simulation failed -- is the API running?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-full flex-1 flex-col bg-white">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-12">
        <h1 className="text-2xl font-semibold tracking-tight text-black">Simulate Event</h1>
        <p className="text-sm text-neutral-500">
          Triggers the real orchestrator lifecycle for every real counterparty currently
          holding an affected ticker -- a genuine breach can produce a pending approval on
          the Approvals &amp; SLA page.
        </p>

        <div className="flex flex-col gap-4 rounded-xl border border-neutral-200 bg-white p-5">
          <div className="flex flex-wrap gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-neutral-500">Kind of shock</label>
              <select
                value={eventType}
                onChange={(e) => setEventType(e.target.value as SimulateEventKind)}
                className="w-44 rounded-lg border border-neutral-200 px-3 py-1.5 text-sm text-black outline-none focus:border-[#D3F770] focus:ring-2 focus:ring-[#D3F770]/40"
              >
                {EVENT_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-neutral-500">Ticker</label>
              <select
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                className="w-32 rounded-lg border border-neutral-200 px-3 py-1.5 text-sm text-black outline-none focus:border-[#D3F770] focus:ring-2 focus:ring-[#D3F770]/40"
              >
                {tickers.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-neutral-500">% change</label>
              <input
                type="number"
                step="0.1"
                value={pctChangeInput}
                onChange={(e) => setPctChangeInput(e.target.value)}
                placeholder="-12.5"
                className="w-28 rounded-lg border border-neutral-200 px-3 py-1.5 text-sm text-black outline-none focus:border-[#D3F770] focus:ring-2 focus:ring-[#D3F770]/40"
              />
            </div>
          </div>
          <p className="text-xs text-neutral-500">
            Applies a {pctChangeInput || "?"}% delta to {ticker || "the selected ticker"}&apos;s
            real current price, then runs the real lifecycle for every real counterparty holding
            it.
          </p>
          <button
            disabled={busy || !canSubmit}
            onClick={trigger}
            className="w-fit rounded-full px-4 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            style={{ backgroundColor: LIGHT_GREEN }}
          >
            {busy ? "Simulating..." : "Trigger simulation"}
          </button>
          {!canAct && <p className="text-xs text-neutral-400">Viewer role -- read-only.</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>

        {result && (
          <div className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-5">
            <span className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
              {result.reason}
            </span>
            {result.affected_counterparties.length === 0 && (
              <p className="text-sm text-neutral-500">
                No real counterparty currently holds an affected ticker.
              </p>
            )}
            {result.affected_counterparties.map((item) => (
              <div
                key={item.counterparty_id}
                className="flex items-center justify-between gap-4 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-black">{item.counterparty_id}</span>
                  {item.error ? (
                    <span className="text-red-600">{item.error}</span>
                  ) : (
                    <StatusLight
                      status={item.breached ? "breached" : "healthy"}
                      className="text-xs"
                    />
                  )}
                </div>
                <div className="flex items-center gap-3 font-mono text-xs text-black">
                  {item.call_amount !== null && formatUsd(item.call_amount, "USD")}
                  {item.thread_id && (
                    <Link
                      href={`/margin-calls/${encodeURIComponent(item.thread_id)}/trace`}
                      className="underline underline-offset-4"
                      style={{ color: DARK_GREEN }}
                    >
                      View trace &rarr;
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
