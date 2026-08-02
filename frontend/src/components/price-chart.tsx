"use client";

import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { getPriceHistory, type PricePoint } from "@/lib/api";

const chartConfig = {
  price: { label: "Price (USD)", color: "var(--primary)" },
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
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {ticker ? `${ticker} -- last ${days} days` : "Select a ticker"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!ticker && <p className="text-sm text-muted-foreground">No ticker selected.</p>}
        {ticker && state === "loading" && (
          <p className="text-sm text-muted-foreground">Loading price history...</p>
        )}
        {ticker && state === "error" && (
          <p className="text-sm text-status-danger">Could not load price history for {ticker}.</p>
        )}
        {ticker && state === "ready" && (
          <ChartContainer config={chartConfig} className="h-[240px] w-full">
            <LineChart data={points} margin={{ left: 8, right: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={32} />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={64}
                domain={["auto", "auto"]}
                tickFormatter={(value: number) => value.toLocaleString()}
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
      </CardContent>
    </Card>
  );
}
