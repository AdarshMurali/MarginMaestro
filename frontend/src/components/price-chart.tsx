"use client";

import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { getPriceHistory, type PricePoint } from "@/lib/api";
import { DARK_GREEN } from "@/lib/brand";

const chartConfig = {
  price: { label: "Price (USD)", color: DARK_GREEN },
} satisfies ChartConfig;

type LoadState = "loading" | "ready" | "error";

/** Caller must render this with `key={ticker}` -- remounting on ticker
 * change is what resets `state` back to "loading" for the new ticker,
 * rather than an extra setState call inside the effect. */
export function PriceChart({ ticker, days = 30 }: { ticker: string | null; days?: number }) {
  const [points, setPoints] = useState<PricePoint[]>([]);
  const [state, setState] = useState<LoadState>("loading");

  useEffect(() => {
    if (!ticker) {
      return;
    }
    let cancelled = false;
    getPriceHistory(ticker, days)
      .then((history) => {
        if (!cancelled) {
          setPoints(history.points);
          setState("ready");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, days]);

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white p-4">
      <span className="text-sm font-medium text-neutral-500">
        {ticker ? `${ticker} -- last ${days} days` : "Select a ticker"}
      </span>
      {!ticker && <p className="text-sm text-neutral-500">No ticker selected.</p>}
      {ticker && state === "loading" && (
        <p className="text-sm text-neutral-500">Loading price history...</p>
      )}
      {ticker && state === "error" && (
        <p className="text-sm text-red-600">Could not load price history for {ticker}.</p>
      )}
      {ticker && state === "ready" && (
        <ChartContainer config={chartConfig} className="h-[240px] w-full">
          <LineChart data={points} margin={{ left: 8, right: 8 }}>
            <CartesianGrid vertical={false} stroke="#e5e5e5" />
            <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={32} stroke="#a3a3a3" />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={64}
              domain={["auto", "auto"]}
              tickFormatter={(value: number) => value.toLocaleString()}
              stroke="#a3a3a3"
            />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line
              dataKey="price"
              type="monotone"
              stroke="var(--color-price)"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ChartContainer>
      )}
    </div>
  );
}
