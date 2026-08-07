"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { getCounterparties, type CounterpartyListResponse } from "@/lib/api";
import { DARK_GREEN } from "@/lib/brand";

export default function ExposurePage() {
  const [list, setList] = useState<CounterpartyListResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Names only (MM-62) -- a trivial DB read, no per-counterparty price/
    // CSA/VIX computation. Status only shows on the detail page (MM-61).
    getCounterparties()
      .then((result) => {
        if (!cancelled) setList(result);
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
          <h1 className="text-2xl font-semibold tracking-tight text-black">Positions &amp; Exposure</h1>
          <p className="text-sm text-neutral-500">
            Every counterparty this book is tracking. Pick one for its positions, thresholds and
            price history.
          </p>
        </div>

        {error && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not load counterparties -- is the API running?
          </p>
        )}
        {!error && !list && <p className="text-sm text-neutral-500">Loading...</p>}
        {list && list.counterparties.length === 0 && (
          <p className="text-sm text-neutral-500">No counterparties tracked yet.</p>
        )}

        {list && list.counterparties.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {list.counterparties.map((cp) => (
              <Link
                key={cp.counterparty_id}
                href={`/exposure/${encodeURIComponent(cp.counterparty_id)}`}
                className="group flex items-center justify-between gap-4 rounded-xl border border-neutral-200 p-4 transition-colors hover:border-[#20463B]"
              >
                <div className="flex flex-col">
                  <span className="text-sm font-semibold text-black">{cp.counterparty_name}</span>
                  <span className="font-mono text-xs text-neutral-500">{cp.counterparty_id}</span>
                </div>
                <span
                  className="text-xs font-medium opacity-0 transition-opacity group-hover:opacity-100"
                  style={{ color: DARK_GREEN }}
                >
                  Open &rarr;
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
