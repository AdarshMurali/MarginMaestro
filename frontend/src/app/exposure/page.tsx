"use client";

import { useEffect, useMemo, useState } from "react";

import { PriceChart } from "@/components/price-chart";
import { StatusLight } from "@/components/status-light";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getExposureBoard, type CounterpartyExposure, type ExposureBoardResponse } from "@/lib/api";
import { formatUsd } from "@/lib/format";

function CounterpartyCard({ item }: { item: CounterpartyExposure }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">
          {item.counterparty_name}{" "}
          <span className="font-mono text-xs text-muted-foreground">({item.counterparty_id})</span>
        </CardTitle>
        <StatusLight status={item.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {item.detail ? (
          <p className="text-sm text-muted-foreground">{item.detail}</p>
        ) : (
          <div className="grid grid-cols-2 gap-2 font-mono text-sm sm:grid-cols-4">
            <div>
              <div className="text-xs text-muted-foreground">Exposure</div>
              {formatUsd(item.exposure, item.currency)}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Threshold</div>
              {formatUsd(item.threshold, item.currency)}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Collateral held</div>
              {formatUsd(item.collateral_held, item.currency)}
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Call amount</div>
              {formatUsd(item.call_amount, item.currency)}
            </div>
          </div>
        )}

        {item.positions.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead>Asset class</TableHead>
                <TableHead className="text-right">Quantity</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">MTM</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {item.positions.map((position) => (
                <TableRow key={position.ticker}>
                  <TableCell className="font-mono">{position.ticker}</TableCell>
                  <TableCell>{position.asset_class}</TableCell>
                  <TableCell className="text-right font-mono">
                    {position.quantity.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {formatUsd(position.price, item.currency)}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {formatUsd(position.mtm, item.currency)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export default function ExposurePage() {
  const [board, setBoard] = useState<ExposureBoardResponse | null>(null);
  const [error, setError] = useState(false);
  const [ticker, setTicker] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getExposureBoard()
      .then((result) => {
        if (cancelled) return;
        setBoard(result);
        const firstTicker = result.counterparties.flatMap((cp) => cp.positions)[0]?.ticker;
        if (firstTicker) setTicker(firstTicker);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tickers = useMemo(() => {
    if (!board) return [];
    const all = board.counterparties.flatMap((cp) => cp.positions.map((p) => p.ticker));
    return Array.from(new Set(all)).sort();
  }, [board]);

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-12">
      <h1 className="text-xl font-semibold">Positions &amp; Exposure</h1>

      {error && (
        <p className="text-sm text-status-danger">
          Could not load the exposure board -- is the API running?
        </p>
      )}
      {!error && !board && <p className="text-sm text-muted-foreground">Loading...</p>}

      {board && (
        <>
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">Price chart:</span>
            <Select value={ticker ?? undefined} onValueChange={setTicker}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Select ticker" />
              </SelectTrigger>
              <SelectContent>
                {tickers.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <PriceChart key={ticker ?? "none"} ticker={ticker} />

          <div className="flex flex-col gap-4">
            {board.counterparties.map((item) => (
              <CounterpartyCard key={item.counterparty_id} item={item} />
            ))}
          </div>
        </>
      )}
    </main>
  );
}
