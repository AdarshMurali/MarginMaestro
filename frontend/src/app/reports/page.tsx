"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import {
  getCollateralAdequacy,
  getConcentration,
  getExposureTrend,
  getMarginCallPerformance,
  getReportsStatus,
  getStressBacktest,
  type CollateralAdequacyReport,
  type ConcentrationReport,
  type ExposureTrendReport,
  type MarginCallPerformanceReport,
  type ReportBook,
  type ReportPeriod,
  type ReportsStatusResponse,
  type StressBacktestReport,
} from "@/lib/api";
import { DARK_GREEN } from "@/lib/brand";
import { formatUsdCompact } from "@/lib/format";
import { cn } from "@/lib/utils";

// MM-142: the five warehouse reports. Every number is computed upstream (the
// calc engine, aggregated in BigQuery's report tables); this page only
// renders what /reports/* returns -- no business logic here.

const AMBER = "#b45309";
const RED = "#dc2626";
const GREY = "#a3a3a3";

const BOOK_LABELS: Record<ReportBook, string> = {
  live: "Live book",
  "historical-sim": "Simulated history (1,000 counterparties, 5 years)",
};
const PERIODS: { value: ReportPeriod; label: string }[] = [
  { value: "3m", label: "3 months" },
  { value: "1y", label: "1 year" },
  { value: "5y", label: "5 years" },
];

type Load<T> = { state: "loading" } | { state: "ready"; data: T } | { state: "error" };

/** Fetches one report whenever the book or period changes. The parent keys
 * each section on book+period, so a change remounts it and starts from
 * "loading" again. */
function useReport<T>(fetcher: () => Promise<T>): Load<T> {
  const [load, setLoad] = useState<Load<T>>({ state: "loading" });
  useEffect(() => {
    let cancelled = false;
    fetcher()
      .then((data) => {
        if (!cancelled) setLoad({ state: "ready", data });
      })
      .catch(() => {
        if (!cancelled) setLoad({ state: "error" });
      });
    return () => {
      cancelled = true;
    };
    // The fetcher is rebuilt each render; the section is remounted per filter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return load;
}

const usd = (value: number) => formatUsdCompact(value, "USD");

function Section({
  number,
  title,
  description,
  children,
}: {
  number: number;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-neutral-200 bg-white p-6">
      <div className="flex flex-col gap-1">
        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-400">
          Report {number}
        </span>
        <h2 className="text-lg font-semibold text-black">{title}</h2>
        <p className="text-sm text-neutral-500">{description}</p>
      </div>
      {children}
    </section>
  );
}

function Status<T>({ load, children }: { load: Load<T>; children: (data: T) => React.ReactNode }) {
  if (load.state === "loading") {
    return <p className="text-sm text-neutral-500">Loading…</p>;
  }
  if (load.state === "error") {
    return <p className="text-sm text-red-600">Could not load this report.</p>;
  }
  return <>{children(load.data)}</>;
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: "danger" }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-neutral-200 px-4 py-3">
      <span className={cn("font-mono text-xl font-semibold", tone === "danger" ? "text-[#dc2626]" : "text-black")}>
        {value}
      </span>
      <span className="text-xs text-neutral-500">{label}</span>
    </div>
  );
}

function Empty() {
  return <p className="text-sm text-neutral-500">No data in the warehouse for this selection yet.</p>;
}

// --- 1. exposure & threshold headroom ------------------------------------------------

const exposureConfig = {
  exposure: { label: "Exposure", color: DARK_GREEN },
  threshold: { label: "Threshold", color: GREY },
  headroom: { label: "Headroom", color: AMBER },
} satisfies ChartConfig;

function ExposureTrend({ book, period }: { book: ReportBook; period: ReportPeriod }) {
  const load = useReport<ExposureTrendReport>(() => getExposureTrend(book, period));
  return (
    <Section
      number={1}
      title="Exposure & threshold headroom"
      description="Total exposure (VM + IM) against total CSA thresholds per day; headroom = threshold + collateral held - exposure."
    >
      <Status load={load}>
        {(report) => {
          const last = report.points.at(-1);
          if (!last) return <Empty />;
          return (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Tile label={`Exposure on ${last.as_of_date}`} value={usd(last.exposure)} />
                <Tile label="Threshold" value={usd(last.threshold)} />
                <Tile label="Headroom" value={usd(last.headroom)} tone={last.headroom < 0 ? "danger" : undefined} />
                <Tile label="Counterparties in breach" value={`${last.breached} / ${last.counterparties}`} tone={last.breached > 0 ? "danger" : undefined} />
              </div>
              <ChartContainer config={exposureConfig} className="h-[260px] w-full">
                <LineChart data={report.points} margin={{ left: 8, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e5e5e5" />
                  <XAxis dataKey="as_of_date" tickLine={false} axisLine={false} minTickGap={40} stroke={GREY} />
                  <YAxis tickLine={false} axisLine={false} width={72} tickFormatter={usd} stroke={GREY} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Line dataKey="exposure" stroke="var(--color-exposure)" strokeWidth={2} dot={false} />
                  <Line dataKey="threshold" stroke="var(--color-threshold)" strokeWidth={1.5} dot={false} />
                  <Line dataKey="headroom" stroke="var(--color-headroom)" strokeWidth={1.5} dot={false} />
                </LineChart>
              </ChartContainer>
            </>
          );
        }}
      </Status>
    </Section>
  );
}

// --- 2. collateral adequacy ----------------------------------------------------------

const adequacyConfig = {
  counterparties: { label: "Counterparties", color: DARK_GREEN },
} satisfies ChartConfig;

function CollateralAdequacy({ book, period }: { book: ReportBook; period: ReportPeriod }) {
  const load = useReport<CollateralAdequacyReport>(() => getCollateralAdequacy(book, period));
  return (
    <Section
      number={2}
      title="Collateral adequacy"
      description="Collateral held (after haircuts) against the credit support each CSA requires, on the latest day."
    >
      <Status load={load}>
        {(report) => {
          if (!report.as_of_date) return <Empty />;
          return (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Tile label={`Required support on ${report.as_of_date}`} value={usd(report.required_support)} />
                <Tile label="Collateral held" value={usd(report.collateral_held)} />
                <Tile label="Counterparties" value={String(report.counterparties)} />
              </div>
              <ChartContainer config={adequacyConfig} className="h-[220px] w-full">
                <BarChart data={report.buckets} margin={{ left: 8, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e5e5e5" />
                  <XAxis dataKey="bucket" tickLine={false} axisLine={false} stroke={GREY} />
                  <YAxis tickLine={false} axisLine={false} width={48} allowDecimals={false} stroke={GREY} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="counterparties" fill="var(--color-counterparties)" radius={4} />
                </BarChart>
              </ChartContainer>
              <ReportTable
                caption="Lowest headroom"
                headers={["Counterparty", "Tier", "Required", "Held", "Coverage", "Headroom"]}
                rows={report.lowest_headroom.map((r) => [
                  r.counterparty_id,
                  r.tier,
                  usd(r.required_support),
                  usd(r.collateral_held),
                  r.coverage_ratio === null ? "--" : `${(r.coverage_ratio * 100).toFixed(0)}%`,
                  usd(r.headroom),
                ])}
              />
            </>
          );
        }}
      </Status>
    </Section>
  );
}

// --- 3. concentration ------------------------------------------------------------------

const concentrationConfig = {
  gross: { label: "Gross market value", color: DARK_GREEN },
} satisfies ChartConfig;

function Concentration({ book, period }: { book: ReportBook; period: ReportPeriod }) {
  const load = useReport<ConcentrationReport>(() => getConcentration(book, period));
  return (
    <Section
      number={3}
      title="Concentration risk"
      description="Gross and net market value by GICS sector, asset class and the largest tickers, at the latest month-end snapshot."
    >
      <Status load={load}>
        {(report) => {
          if (!report.as_of_date) return <Empty />;
          return (
            <>
              <span className="text-xs text-neutral-500">As of {report.as_of_date}</span>
              <ChartContainer config={concentrationConfig} className="h-[320px] w-full">
                <BarChart data={report.by_sector} layout="vertical" margin={{ left: 8, right: 8 }}>
                  <CartesianGrid horizontal={false} stroke="#e5e5e5" />
                  <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={usd} stroke={GREY} />
                  <YAxis type="category" dataKey="key" tickLine={false} axisLine={false} width={150} stroke={GREY} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="gross" fill="var(--color-gross)" radius={4} />
                </BarChart>
              </ChartContainer>
              <div className="grid gap-4 lg:grid-cols-2">
                <ReportTable
                  caption="Largest tickers"
                  headers={["Ticker", "Gross", "Net", "Counterparties"]}
                  rows={report.top_tickers.map((r) => [r.key, usd(r.gross), usd(r.net), String(r.counterparties)])}
                />
                <ReportTable
                  caption="By asset class"
                  headers={["Asset class", "Gross", "Net", "Counterparties"]}
                  rows={report.by_asset_class.map((r) => [r.key, usd(r.gross), usd(r.net), String(r.counterparties)])}
                />
              </div>
            </>
          );
        }}
      </Status>
    </Section>
  );
}

// --- 4. margin-call performance ----------------------------------------------------------

const performanceConfig = {
  sla_met: { label: "SLA met", color: DARK_GREEN },
  sla_breached: { label: "SLA breached", color: RED },
  open_calls: { label: "Open", color: GREY },
} satisfies ChartConfig;

function MarginCallPerformance({ book, period }: { book: ReportBook; period: ReportPeriod }) {
  const load = useReport<MarginCallPerformanceReport>(() => getMarginCallPerformance(book, period));
  return (
    <Section
      number={4}
      title="Margin-call performance"
      description="Calls per month by SLA outcome, with amounts, approval turnaround and escalations."
    >
      <Status load={load}>
        {(report) => {
          if (report.months.length === 0) return <Empty />;
          return (
            <>
              <ChartContainer config={performanceConfig} className="h-[240px] w-full">
                <BarChart data={report.months} margin={{ left: 8, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e5e5e5" />
                  <XAxis dataKey="month" tickLine={false} axisLine={false} minTickGap={24} stroke={GREY} />
                  <YAxis tickLine={false} axisLine={false} width={48} allowDecimals={false} stroke={GREY} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Bar dataKey="sla_met" stackId="calls" fill="var(--color-sla_met)" />
                  <Bar dataKey="sla_breached" stackId="calls" fill="var(--color-sla_breached)" />
                  <Bar dataKey="open_calls" stackId="calls" fill="var(--color-open_calls)" />
                </BarChart>
              </ChartContainer>
              <ReportTable
                caption="By month"
                headers={["Month", "Calls", "Amount", "Avg approval", "P90 approval", "Escalations"]}
                rows={[...report.months].reverse().map((m) => [
                  m.month.slice(0, 7),
                  String(m.calls),
                  usd(m.amount),
                  m.avg_approval_minutes === null ? "--" : `${m.avg_approval_minutes.toFixed(1)} min`,
                  m.p90_approval_minutes === null ? "--" : `${m.p90_approval_minutes.toFixed(1)} min`,
                  String(m.escalations),
                ])}
              />
            </>
          );
        }}
      </Status>
    </Section>
  );
}

// --- 5. stress / backtest ------------------------------------------------------------------

const stressConfig = {
  calls_raised: { label: "Calls raised", color: DARK_GREEN },
  max_vix: { label: "Max VIX", color: AMBER },
} satisfies ChartConfig;

function StressBacktest({ book, period }: { book: ReportBook; period: ReportPeriod }) {
  const load = useReport<StressBacktestReport>(() => getStressBacktest(book, period));
  return (
    <Section
      number={5}
      title="Stress & backtest"
      description="On which days the CSA thresholds would have triggered calls, and for how much, against the VIX."
    >
      <Status load={load}>
        {(report) => {
          if (report.months.length === 0) return <Empty />;
          return (
            <>
              <ChartContainer config={stressConfig} className="h-[260px] w-full">
                <ComposedChart data={report.months} margin={{ left: 8, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e5e5e5" />
                  <XAxis dataKey="month" tickLine={false} axisLine={false} minTickGap={24} stroke={GREY} />
                  <YAxis yAxisId="calls" tickLine={false} axisLine={false} width={48} stroke={GREY} />
                  <YAxis yAxisId="vix" orientation="right" tickLine={false} axisLine={false} width={40} stroke={GREY} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <ChartLegend content={<ChartLegendContent />} />
                  <Bar yAxisId="calls" dataKey="calls_raised" fill="var(--color-calls_raised)" radius={3} />
                  <Line yAxisId="vix" dataKey="max_vix" stroke="var(--color-max_vix)" strokeWidth={2} dot={false} />
                </ComposedChart>
              </ChartContainer>
              <ReportTable
                caption="Heaviest days"
                headers={["Day", "Calls raised", "Amount called", "In breach", "VIX"]}
                rows={report.top_days.map((d) => [
                  d.as_of_date,
                  String(d.calls_raised),
                  usd(d.call_amount),
                  String(d.breached),
                  d.vix.toFixed(1),
                ])}
              />
            </>
          );
        }}
      </Status>
    </Section>
  );
}

// --- shared table ---------------------------------------------------------------------------

function ReportTable({
  caption,
  headers,
  rows,
}: {
  caption: string;
  headers: string[];
  rows: string[][];
}) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium text-neutral-500">{caption}</span>
      <div className="overflow-x-auto rounded-xl border border-neutral-200">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-left text-xs text-neutral-500">
            <tr>
              {headers.map((h) => (
                <th key={h} className="px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.join("|")} className="border-t border-neutral-100">
                {row.map((cell, i) => (
                  <td
                    key={`${headers[i]}-${cell}`}
                    className={cn("px-3 py-2 text-black", i > 0 && "font-mono")}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --- the page ----------------------------------------------------------------------------------

function Toggle<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-full border border-neutral-200 p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-full px-3 py-1 text-sm transition-colors",
            option.value === value ? "bg-black text-white" : "text-neutral-500 hover:text-black",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export default function ReportsPage() {
  const [status, setStatus] = useState<Load<ReportsStatusResponse>>({ state: "loading" });
  const [book, setBook] = useState<ReportBook>("live");
  const [period, setPeriod] = useState<ReportPeriod>("1y");

  useEffect(() => {
    let cancelled = false;
    getReportsStatus()
      .then((data) => {
        if (!cancelled) setStatus({ state: "ready", data });
      })
      .catch(() => {
        if (!cancelled) setStatus({ state: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const key = `${book}:${period}`;

  return (
    <main className="flex min-h-full flex-1 flex-col bg-neutral-50">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-10">
        <div className="flex flex-col gap-2">
          <h1 className="text-3xl font-semibold tracking-tight text-black">Reports</h1>
          <p className="max-w-2xl text-sm text-neutral-500">
            Five finance reports from the BigQuery warehouse. Each figure was computed by the
            deterministic calc engine and aggregated into pre-built report tables; results are
            cached for 10 minutes.
          </p>
        </div>

        {status.state === "loading" && <p className="text-sm text-neutral-500">Checking the warehouse…</p>}
        {status.state === "error" && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
            Could not reach the API -- is the backend running?
          </p>
        )}
        {status.state === "ready" && !status.data.configured && (
          <div className="rounded-2xl border border-neutral-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-black">The warehouse is not configured</h2>
            <p className="mt-1 text-sm text-neutral-500">
              Reports read the BigQuery warehouse, which this deployment doesn&apos;t use
              (WAREHOUSE=none). Everything else in the app works as usual.
            </p>
          </div>
        )}
        {status.state === "ready" && status.data.configured && (
          <>
            <div className="flex flex-wrap items-center gap-3">
              {status.data.books.length > 1 && (
                <Toggle
                  options={status.data.books.map((b) => ({ value: b, label: BOOK_LABELS[b] }))}
                  value={book}
                  onChange={setBook}
                />
              )}
              <Toggle options={PERIODS} value={period} onChange={setPeriod} />
              {status.data.scoped && (
                <span className="text-xs text-neutral-500">
                  Showing only the counterparties you cover (live book).
                </span>
              )}
            </div>
            <ExposureTrend key={`exposure:${key}`} book={book} period={period} />
            <CollateralAdequacy key={`adequacy:${key}`} book={book} period={period} />
            <Concentration key={`concentration:${key}`} book={book} period={period} />
            <MarginCallPerformance key={`calls:${key}`} book={book} period={period} />
            <StressBacktest key={`stress:${key}`} book={book} period={period} />
          </>
        )}
      </div>
    </main>
  );
}
