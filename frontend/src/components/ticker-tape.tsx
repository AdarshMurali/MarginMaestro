"use client";

import { useEffect, useState } from "react";

import { getMarketUniverse, getPriceHistory } from "@/lib/api";
import { BRAND_GREEN } from "@/lib/brand";

interface Quote {
  ticker: string;
  price: number;
  changePct: number;
}

// Fetched once per page load and shared by every page: the nav shell stays
// mounted across navigation, so the tape doesn't re-query on each click.
let cached: Promise<Quote[]> | null = null;

async function loadQuotes(): Promise<Quote[]> {
  const { tickers } = await getMarketUniverse();
  const results = await Promise.allSettled(tickers.map((t) => getPriceHistory(t, 7)));
  const quotes: Quote[] = [];
  results.forEach((result) => {
    if (result.status !== "fulfilled") return; // ticker with no stored prices
    const points = result.value.points;
    if (points.length < 2) return;
    const last = points[points.length - 1].price;
    const prev = points[points.length - 2].price;
    // Display only: the move between the last two stored closes.
    quotes.push({ ticker: result.value.ticker, price: last, changePct: ((last - prev) / prev) * 100 });
  });
  return quotes;
}

function formatPrice(price: number): string {
  return price.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Scrolling market ticker for the top bar (White Paper theme). */
export function TickerTape() {
  const [quotes, setQuotes] = useState<Quote[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    cached ??= loadQuotes().catch((err) => {
      cached = null; // let the next mount retry
      throw err;
    });
    cached
      .then((q) => {
        if (!cancelled) setQuotes(q);
      })
      .catch(() => {
        if (!cancelled) setQuotes([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (quotes !== null && quotes.length === 0) return null;

  const items = quotes ?? [];
  return (
    <div
      className="mm-tape-wrap overflow-hidden bg-[#0A0A0A]"
      role="marquee"
      aria-label="Market prices"
      style={{ minHeight: 40 }}
    >
      <div className="mm-tape">
        {[...items, ...items].map((q, i) => {
          const up = q.changePct >= 0;
          return (
            <span
              key={`${q.ticker}-${i}`}
              aria-hidden={i >= items.length}
              className="inline-flex items-baseline gap-2 whitespace-nowrap px-6 py-2.5 font-mono text-[13px]"
            >
              <span className="font-semibold text-white">{q.ticker}</span>
              <span className="text-[#BDBDBD]">{formatPrice(q.price)}</span>
              <span className="font-semibold" style={{ color: up ? BRAND_GREEN : "#FF5A52" }}>
                {up ? "▲" : "▼"} {Math.abs(q.changePct).toFixed(2)}%
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}
