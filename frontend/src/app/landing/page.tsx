"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { LogoMark } from "@/components/logo";
import { getExposureBoard, getMarginCallFeed } from "@/lib/api";

const STACK = ["LangGraph", "OpenAI", "ChromaDB", "Kafka", "Azure SQL", "FastAPI"];
const ACCENT = "#1e8449";

function AnimatedNumber({ value }: { value: number | null }) {
  return <span>{value === null ? "--" : value.toLocaleString()}</span>;
}

export default function LandingPage() {
  const [counterparties, setCounterparties] = useState<number | null>(null);
  const [runsEvaluated, setRunsEvaluated] = useState<number | null>(null);
  const [breachesCaught, setBreachesCaught] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getExposureBoard()
      .then((board) => {
        if (!cancelled) setCounterparties(board.counterparties.length);
      })
      .catch(() => {});
    getMarginCallFeed()
      .then((feed) => {
        if (cancelled) return;
        setRunsEvaluated(feed.margin_calls.length);
        setBreachesCaught(
          feed.margin_calls.filter((m) => m.call_amount !== null && m.call_amount > 0).length,
        );
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="landing flex min-h-full flex-col">
      <style>{`
        .landing { --primary: ${ACCENT}; }
        .landing .fade-up {
          animation: landingFadeUp 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
        }
        .landing .fade-up.d1 { animation-delay: 80ms; }
        .landing .fade-up.d2 { animation-delay: 160ms; }
        .landing .fade-up.d3 { animation-delay: 240ms; }
        @keyframes landingFadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .landing .fade-up { animation: none; }
        }
      `}</style>

      {/* ---------- dark zone: header + hero + tech strip ----------
          Sized to its own content, independent of the light zone below --
          guarantees this stays dark-to-mid-green all the way through,
          rather than a single page-length gradient landing on the wrong
          shade wherever content happens to wrap (found live, 2026-08-03:
          a single continuous gradient put the stats row on mid-green with
          green-on-green text). */}
      <div
        style={{
          background:
            "linear-gradient(to bottom, #05080a 0%, #0b2016 30%, #143b26 62%, #1f5133 100%)",
        }}
      >
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2">
          <LogoMark size={26} />
          <span className="text-sm font-semibold tracking-tight">
            <span className="text-white">Margin</span>
            <span style={{ color: "#4ade80" }}>Maestro</span>
          </span>
        </div>
        <Link
          href="/login"
          className="rounded-full px-5 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
          style={{ backgroundColor: ACCENT }}
        >
          Sign in
        </Link>
      </header>

      {/* ---------- hero (dark zone, white text, light floating card) ---------- */}
      <section className="relative overflow-hidden px-6 pt-14 pb-24">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              "repeating-linear-gradient(0deg, rgba(255,255,255,0.04) 0px, rgba(255,255,255,0.04) 1px, transparent 1px, transparent 64px)," +
              "repeating-linear-gradient(90deg, rgba(255,255,255,0.04) 0px, rgba(255,255,255,0.04) 1px, transparent 1px, transparent 64px)",
            maskImage: "linear-gradient(to bottom, black, transparent)",
          }}
        />

        <div className="relative mx-auto flex w-full max-w-6xl flex-col items-start gap-10 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex max-w-xl flex-col items-start gap-6">
            <h1 className="fade-up text-4xl font-semibold leading-[1.08] tracking-tight text-balance text-white sm:text-5xl">
              Stop reading documents.
              <br />
              <span style={{ color: "#4ade80" }}>Start making decisions.</span>
            </h1>
            <p className="fade-up d1 max-w-md text-[15px] leading-relaxed text-white/70">
              AI agents watch every counterparty&apos;s exposure in real time, ground every
              threshold in the actual CSA agreement, and pause for a human before anything ever
              reaches a client.
            </p>
            <div className="fade-up d2 flex flex-wrap items-center gap-3">
              <Link
                href="/login"
                className="rounded-full px-6 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                style={{ backgroundColor: ACCENT }}
              >
                Sign in to the dashboard
              </Link>
              <a
                href="#how-it-works"
                className="rounded-full border border-white/20 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-white/10"
              >
                See how it works
              </a>
            </div>
          </div>

          <div className="fade-up d3 w-full max-w-sm rounded-2xl bg-white p-5 text-[#0b0f17] shadow-2xl shadow-black/40">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-500">Margin call · illustrative</span>
              <span className="flex items-center gap-1.5 text-xs font-medium text-[#b45309]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#f5a524]" />
                At risk
              </span>
            </div>
            <div className="mt-4 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-semibold">$135,388</span>
              <span className="text-xs text-neutral-500">USD</span>
            </div>
            <p className="mt-1 text-xs text-neutral-500">Barnes Capital Management · CP-7</p>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t border-neutral-200 pt-4 font-mono text-xs">
              <div>
                <div className="text-neutral-500">Threshold</div>
                <div className="mt-0.5 font-medium">$340,000</div>
              </div>
              <div>
                <div className="text-neutral-500">Collateral held</div>
                <div className="mt-0.5 font-medium">$4,900,000</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- tech strip (still dark zone, soft white text) ---------- */}
      <section className="px-6 py-8">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-4">
          <span className="text-xs uppercase tracking-[0.14em] text-white/60">
            The real stack underneath
          </span>
          <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
            {STACK.map((name) => (
              <span key={name} className="text-sm font-medium text-white/70">
                {name}
              </span>
            ))}
          </div>
        </div>
      </section>
      </div>

      {/* ---------- light zone: stats + how it works + CTA + footer ----------
          Starts light and stays light through to the bottom, independent of
          how tall the dark zone above ended up. */}
      <div
        style={{
          background: "linear-gradient(to bottom, #e4f0e8 0%, #f5faf6 12%, #ffffff 30%)",
        }}
      >

      {/* ---------- live stats (light zone, dark text) ---------- */}
      <section className="px-6 py-16">
        <div className="mx-auto flex w-full max-w-4xl flex-col items-center gap-2 divide-y divide-black/10 sm:flex-row sm:divide-x sm:divide-y-0">
          <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
            <span className="font-mono text-4xl font-semibold" style={{ color: ACCENT }}>
              <AnimatedNumber value={counterparties} />
            </span>
            <span className="text-xs text-neutral-600">Counterparties tracked, live</span>
          </div>
          <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
            <span className="font-mono text-4xl font-semibold" style={{ color: ACCENT }}>
              <AnimatedNumber value={runsEvaluated} />
            </span>
            <span className="text-xs text-neutral-600">Margin-call runs evaluated</span>
          </div>
          <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
            <span className="font-mono text-4xl font-semibold" style={{ color: ACCENT }}>
              <AnimatedNumber value={breachesCaught} />
            </span>
            <span className="text-xs text-neutral-600">Real breaches caught</span>
          </div>
        </div>
      </section>

      {/* ---------- how it works (white zone, black text) ---------- */}
      <section id="how-it-works" className="px-6 py-16">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex max-w-md flex-col gap-5">
            <h2 className="text-3xl font-semibold leading-tight text-balance text-[#0b0f17]">
              See every decision.
              <br />
              Not just the outcome.
            </h2>
            <ul className="flex flex-col gap-4 text-[15px] text-neutral-600">
              <li className="flex gap-3">
                <span
                  className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: ACCENT }}
                />
                Thresholds are pulled straight from the real CSA agreement via RAG -- never
                guessed, never hard-coded.
              </li>
              <li className="flex gap-3">
                <span
                  className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: ACCENT }}
                />
                Every run leaves a full, step-by-step agent trace -- what ran, in what order,
                what it found.
              </li>
              <li className="flex gap-3">
                <span
                  className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: ACCENT }}
                />
                A margin call never fires on its own -- a human always approves before anything
                reaches a client.
              </li>
            </ul>
          </div>

          <div className="w-full max-w-sm rounded-2xl border border-neutral-200 bg-white p-5 text-[#0b0f17] shadow-xl shadow-black/10">
            <div className="text-xs font-medium text-neutral-500">Agent trace · illustrative</div>
            <div className="mt-4 flex flex-col gap-4">
              {[
                ["Event received", "Simulated price_shock on TSLA, NVDA"],
                ["Compute exposure", "VM 135,388, IM 1,102,077"],
                ["Fetch CSA terms", "Threshold 340,000 USD"],
              ].map(([title, detail]) => (
                <div key={title} className="flex gap-3">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#22c55e]" />
                  <div className="flex flex-col">
                    <span className="text-sm font-medium">{title}</span>
                    <span className="text-xs text-neutral-500">{detail}</span>
                  </div>
                </div>
              ))}
              <div className="flex gap-3">
                <span className="mt-1.5 h-2 w-2 shrink-0 animate-pulse rounded-full bg-[#3b82f6]" />
                <div className="flex flex-col">
                  <span className="text-sm font-medium">Evaluate breach</span>
                  <span className="text-xs text-neutral-500">in progress...</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- closing CTA (white zone) ---------- */}
      <section className="px-6 py-20">
        <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 rounded-2xl border border-neutral-200 bg-white px-8 py-14 text-center text-[#0b0f17] shadow-xl shadow-black/10">
          <h2 className="text-2xl font-semibold text-balance sm:text-3xl">
            Ready to watch it decide?
          </h2>
          <Link
            href="/login"
            className="rounded-full px-7 py-3 text-sm font-semibold text-white transition-opacity hover:opacity-90"
            style={{ backgroundColor: ACCENT }}
          >
            Sign in to the dashboard
          </Link>
        </div>
      </section>

      <footer className="px-6 py-8 text-center text-xs text-neutral-500">
        MarginMaestro -- a portfolio project. Data is real; scenarios are synthetic.
      </footer>
      </div>
    </main>
  );
}
