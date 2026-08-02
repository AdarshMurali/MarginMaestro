"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Logo } from "@/components/logo";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getHealth } from "@/lib/api";

type BackendStatus = "checking" | "healthy" | "unreachable";

const STATUS_LEGEND: { key: string; label: string; colorClass: string }[] = [
  { key: "success", label: "Healthy / met", colorClass: "bg-status-success" },
  { key: "warning", label: "Approaching / at risk", colorClass: "bg-status-warning" },
  { key: "danger", label: "Breached / escalated", colorClass: "bg-status-danger" },
  { key: "info", label: "In progress", colorClass: "bg-status-info" },
];

function BackendStatusDot({ status }: { status: BackendStatus }) {
  const colorClass =
    status === "healthy"
      ? "bg-status-success"
      : status === "unreachable"
        ? "bg-status-danger"
        : "bg-status-warning";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${colorClass}`} />;
}

export default function Home() {
  const [status, setStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then(() => {
        if (!cancelled) setStatus("healthy");
      })
      .catch(() => {
        if (!cancelled) setStatus("unreachable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="flex min-h-full flex-1 flex-col items-center justify-center gap-8 px-6 py-16">
      <Logo size={40} showTagline className="text-center" />

      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Backend connectivity
          </CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-2">
          <BackendStatusDot status={status} />
          <span className="font-mono text-sm">
            {status === "checking" && "checking..."}
            {status === "healthy" && "FastAPI /health -> ok"}
            {status === "unreachable" && "unreachable -- is the API running?"}
          </span>
        </CardContent>
      </Card>

      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Status-color legend
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {STATUS_LEGEND.map((item) => (
            <div key={item.key} className="flex items-center gap-2 text-sm">
              <span className={`inline-block h-2.5 w-2.5 rounded-full ${item.colorClass}`} />
              <span>{item.label}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      <p className="max-w-sm text-center text-xs text-muted-foreground">
        Placeholder page (MM-51): proves the design system and a live backend
        connection. The real Home dashboard lands in MM-58.
      </p>

      <Link href="/exposure" className="text-sm text-primary underline underline-offset-4">
        View Positions &amp; Exposure board (MM-52) &rarr;
      </Link>
      <Link href="/margin-calls" className="text-sm text-primary underline underline-offset-4">
        View Margin Calls feed (MM-53) &rarr;
      </Link>
      <Link href="/approvals" className="text-sm text-primary underline underline-offset-4">
        View Approvals &amp; SLA (MM-55) &rarr;
      </Link>
      <Link href="/simulate" className="text-sm text-primary underline underline-offset-4">
        Simulate Event (MM-56) &rarr;
      </Link>
    </main>
  );
}
