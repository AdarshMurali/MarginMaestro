"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { getPublicStats } from "@/lib/api";
import { LogoMarkV2 } from "@/components/logo-v2";
import { INK, MUTED, LINE, STATUS_AMBER, TEXT_AMBER } from "@/lib/brand";

const STACK = ["LangGraph", "Gemini · Vertex AI", "Cloud SQL · pgvector", "Pub/Sub", "FastAPI", "Firestore"];

function AnimatedNumber({ value }: { value: number | null }) {
  return <span>{value === null ? "--" : value.toLocaleString()}</span>;
}

export default function LandingPage() {
  const [counterparties, setCounterparties] = useState<number | null>(null);
  const [runsEvaluated, setRunsEvaluated] = useState<number | null>(null);
  const [breachesCaught, setBreachesCaught] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPublicStats()
      .then((stats) => {
        if (cancelled) return;
        setCounterparties(stats.counterparties);
        setRunsEvaluated(stats.runs_evaluated);
        setBreachesCaught(stats.calls_raised);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="landing flex min-h-full flex-col bg-white text-[#0A0A0A]">
      <style>{`
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

      {/* ---------- header ---------- */}
      <header className="border-b border-[#E5E5E5]">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-2.5">
            <LogoMarkV2 size={32} />
            <span className="text-lg font-extrabold tracking-tight">
              Margin<span className="font-medium">Maestro</span>
            </span>
          </div>
          <Link
            href="/login"
            className="inline-flex min-h-10 items-center rounded-[10px] bg-[#0A0A0A] px-5 text-sm font-semibold text-white transition-colors hover:bg-[#262626]"
          >
            Sign in
          </Link>
        </div>
      </header>

      {/* ---------- hero ---------- */}
      <section className="px-6 pb-20 pt-16 sm:pt-20">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-start gap-10 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex max-w-xl flex-col items-start gap-6">
            <h1 className="fade-up text-4xl font-extrabold leading-[1.05] tracking-[-0.03em] text-balance sm:text-5xl">
              Stop reading documents.
              <br />
              <span className="text-[#8A8A8A]">Start making decisions.</span>
            </h1>
            <p className="fade-up d1 max-w-md text-[15px] leading-relaxed" style={{ color: MUTED }}>
              AI agents watch every counterparty&apos;s exposure in real time, ground every
              threshold in the actual CSA agreement, and pause for a human before anything ever
              reaches a client.
            </p>
            <div className="fade-up d2 flex flex-wrap items-center gap-3">
              <Link
                href="/login"
                className="inline-flex min-h-11 items-center rounded-[10px] bg-[#0A0A0A] px-6 text-sm font-bold text-white transition-colors hover:bg-[#262626]"
              >
                Sign in to the dashboard
              </Link>
              <a
                href="#how-it-works"
                className="inline-flex min-h-11 items-center rounded-[10px] border border-[#D4D4D4] px-6 text-sm font-semibold transition-colors hover:bg-[#F7F7F7]"
              >
                See how it works
              </a>
            </div>
          </div>

          <div
            className="fade-up d3 w-full max-w-sm rounded-2xl border p-5 shadow-sm"
            style={{ borderColor: LINE }}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium" style={{ color: MUTED }}>
                Margin call · illustrative
              </span>
              <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: TEXT_AMBER }}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: STATUS_AMBER }} />
                At risk
              </span>
            </div>
            <div className="mt-4 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-semibold">$135,388</span>
              <span className="text-xs" style={{ color: MUTED }}>
                USD
              </span>
            </div>
            <p className="mt-1 text-xs" style={{ color: MUTED }}>
              Barnes Capital Management · CP-7
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t pt-4 font-mono text-xs" style={{ borderColor: LINE }}>
              <div>
                <div style={{ color: MUTED }}>Threshold</div>
                <div className="mt-0.5 font-medium">$340,000</div>
              </div>
              <div>
                <div style={{ color: MUTED }}>Collateral held</div>
                <div className="mt-0.5 font-medium">$4,900,000</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- tech strip ---------- */}
      <section className="border-t px-6 py-8" style={{ borderColor: LINE }}>
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-4">
          <span className="text-xs uppercase tracking-[0.14em]" style={{ color: MUTED }}>
            The real stack underneath
          </span>
          <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
            {STACK.map((name) => (
              <span key={name} className="font-mono text-sm font-medium" style={{ color: "#3D3D3D" }}>
                {name}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- live stats ---------- */}
      <section className="px-6 py-16">
        <div className="mx-auto flex w-full max-w-4xl flex-col items-center gap-2 divide-y sm:flex-row sm:divide-x sm:divide-y-0" style={{ borderColor: LINE }}>
          <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
            <span className="font-mono text-4xl font-semibold">
              <AnimatedNumber value={counterparties} />
            </span>
            <span className="text-xs" style={{ color: MUTED }}>
              Counterparties tracked, live
            </span>
          </div>
          <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
            <span className="font-mono text-4xl font-semibold">
              <AnimatedNumber value={runsEvaluated} />
            </span>
            <span className="text-xs" style={{ color: MUTED }}>
              Margin-call runs evaluated
            </span>
          </div>
          <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
            <span className="font-mono text-4xl font-semibold">
              <AnimatedNumber value={breachesCaught} />
            </span>
            <span className="text-xs" style={{ color: MUTED }}>
              Real breaches caught
            </span>
          </div>
        </div>
      </section>

      {/* ---------- how it works ---------- */}
      <section id="how-it-works" className="border-t px-6 py-16" style={{ borderColor: LINE }}>
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex max-w-md flex-col gap-5">
            <h2 className="text-3xl font-extrabold leading-tight text-balance">
              See every decision.
              <br />
              Not just the outcome.
            </h2>
            <ul className="flex flex-col gap-4 text-[15px]" style={{ color: "#3D3D3D" }}>
              <li className="flex gap-3">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: INK }} />
                Thresholds are pulled straight from the real CSA agreement via RAG -- never
                guessed, never hard-coded.
              </li>
              <li className="flex gap-3">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: INK }} />
                Every run leaves a full, step-by-step agent trace -- what ran, in what order,
                what it found.
              </li>
              <li className="flex gap-3">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: INK }} />
                A margin call never fires on its own -- a human always approves before anything
                reaches a client.
              </li>
            </ul>
          </div>

          <div className="w-full max-w-sm rounded-2xl border p-5 shadow-sm" style={{ borderColor: LINE }}>
            <div className="text-xs font-medium" style={{ color: MUTED }}>
              Agent trace · illustrative
            </div>
            <div className="mt-4 flex flex-col gap-4">
              {[
                ["Event received", "Simulated price_shock on TSLA, NVDA"],
                ["Compute exposure", "VM 135,388, IM 1,102,077"],
                ["Fetch CSA terms", "Threshold 340,000 USD"],
              ].map(([title, detail]) => (
                <div key={title} className="flex gap-3">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: "#00B86B" }} />
                  <div className="flex flex-col">
                    <span className="text-sm font-medium">{title}</span>
                    <span className="text-xs" style={{ color: MUTED }}>
                      {detail}
                    </span>
                  </div>
                </div>
              ))}
              <div className="flex gap-3">
                <span className="mt-1.5 h-2 w-2 shrink-0 animate-pulse rounded-full" style={{ backgroundColor: MUTED }} />
                <div className="flex flex-col">
                  <span className="text-sm font-medium">Evaluate breach</span>
                  <span className="text-xs" style={{ color: MUTED }}>
                    in progress...
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- closing CTA ---------- */}
      <section className="px-6 py-20">
        <div
          className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 rounded-2xl border px-8 py-14 text-center shadow-sm"
          style={{ borderColor: LINE }}
        >
          <h2 className="text-2xl font-extrabold text-balance sm:text-3xl">
            Ready to watch it decide?
          </h2>
          <Link
            href="/login"
            className="inline-flex min-h-11 items-center rounded-[10px] bg-[#0A0A0A] px-7 text-sm font-bold text-white transition-colors hover:bg-[#262626]"
          >
            Sign in to the dashboard
          </Link>
        </div>
      </section>

      <footer className="border-t px-6 py-8 text-center text-xs" style={{ borderColor: LINE, color: MUTED }}>
        MarginMaestro -- a portfolio project. Data is real; scenarios are synthetic.
      </footer>
    </main>
  );
}
