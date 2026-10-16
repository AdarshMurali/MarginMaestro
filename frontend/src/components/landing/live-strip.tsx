"use client";

import { useEffect, useState } from "react";

import { getMarketUniverse, getPublicStats, type PublicStatsResponse } from "@/lib/api";
import { BRAND_GREEN } from "@/lib/brand";

/**
 * Black band under the landing hero (MM-147): real counts from the public
 * `/public/stats` endpoint and the tickers being watched from
 * `/market-universe` -- both readable before sign-in. Prices need a session,
 * so the tape shows names only. Hides itself if the API is unreachable.
 */
export function LiveStrip() {
  const [stats, setStats] = useState<PublicStatsResponse | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getPublicStats(), getMarketUniverse()]).then(([s, u]) => {
      if (cancelled) return;
      if (s.status === "fulfilled") setStats(s.value);
      if (u.status === "fulfilled") setTickers(u.value.tickers);
      if (s.status === "rejected" && u.status === "rejected") setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) return null;

  const figures = stats
    ? [
        { value: stats.counterparties, label: "counterparties monitored" },
        { value: stats.runs_evaluated, label: "agent runs evaluated" },
        { value: stats.calls_raised, label: "margin calls raised" },
      ]
    : null;

  return (
    <section aria-label="Live from the book" className="bg-[#0A0A0A] text-white">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-6 px-6 py-8 sm:grid-cols-3">
        {(figures ?? [0, 1, 2].map(() => null)).map((f, i) => (
          <div key={i} className="flex flex-col gap-1">
            <span className="font-mono text-3xl font-semibold tracking-tight">
              {f ? f.value.toLocaleString() : <span className="animate-pulse text-white/30">—</span>}
            </span>
            <span className="text-sm text-[#A3A3A3]">{f?.label ?? " "}</span>
          </div>
        ))}
      </div>
      {tickers.length > 0 && (
        <div className="mm-tape-wrap overflow-hidden border-t border-white/10" role="marquee" aria-label="Tickers being watched">
          <div className="mm-tape">
            {[...tickers, ...tickers].map((t, i) => (
              <span
                key={`${t}-${i}`}
                aria-hidden={i >= tickers.length}
                className="inline-flex items-center gap-2 whitespace-nowrap px-5 py-2.5 font-mono text-[13px] text-[#D4D4D4]"
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: BRAND_GREEN }} />
                {t}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
