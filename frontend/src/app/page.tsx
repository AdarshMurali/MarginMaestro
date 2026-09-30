"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { getPublicStats } from "@/lib/api";
import { LogoMarkV2 } from "@/components/logo-v2";
import { BLACK, DARK_GREEN, LIGHT_GREEN, WHITE, HERO_GRADIENT } from "@/lib/brand";

const STACK = ["LangGraph", "OpenAI", "ChromaDB", "Kafka", "Azure SQL", "FastAPI"];

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
    <main className="landing-v2 flex min-h-full flex-col" style={{ backgroundColor: WHITE }}>
      <style>{`
        .landing-v2 { --primary: ${DARK_GREEN}; }
        .landing-v2 .fade-up {
          animation: landingFadeUp 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
        }
        .landing-v2 .fade-up.d1 { animation-delay: 80ms; }
        .landing-v2 .fade-up.d2 { animation-delay: 160ms; }
        .landing-v2 .fade-up.d3 { animation-delay: 240ms; }
        @keyframes landingFadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .landing-v2 .fade-up { animation: none; }
        }
      `}</style>

      {/* ---------- dark zone: header + hero ----------
          Tech strip moved out to the white zone below -- the reference
          shows the partner-logos row already sitting on a light background
          with dark text.
          Gradient axis re-derived 2026-08-04 from a "channel" the user
          drew as two roughly-parallel freehand lines on a screenshot,
          rather than two isolated points (that was tried first: aiming
          the color-flow axis straight from point 1 to point 2 -- wrong,
          it read as a left-to-right wash and washed the top-right corner
          white too early). Pixel-sampled both curves with Pillow/numpy,
          fit each to a line, and took the direction PERPENDICULAR to
          those lines as the gradient axis (a linear-gradient's iso-color
          lines are perpendicular to its direction, so the drawn lines
          *are* the iso-color contours, not the flow axis). That comes out
          to 187.13deg -- tilted opposite to the original 172deg: here the
          right side lags (stays dark longer) instead of leading. Verified
          by projecting both fitted lines back onto the resulting axis:
          the top line lands at a near-constant 61.9-64.3% and the bottom
          line at 79.4-81.8% across the full width, confirming the axis
          choice. Original channel: dark green fully arrived by ~63.2%,
          white by ~80.3% (17.1-point band), later widened +20% and
          shifted +5 points to 66.49%..87.01%. Removed 2026-08-05 per the
          user: no more green-to-white ramp at all -- solid DARK_GREEN
          holds from 66.49% (where it first fully arrives) through 100%
          (the bottom of the 602px hero, right before "The real stack
          underneath"), so the hero is black-to-green only, no white
          anywhere inside it. The black-to-green lead-in itself (0%..66.49%)
          is untouched from the channel-derived tuning above. */}
      <div
        className="relative overflow-hidden"
        style={{
          minHeight: "602px",
          background: HERO_GRADIENT,
        }}
      >
        {/* ---------- header ---------- */}
        <header className="relative mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-6">
          <div className="flex items-center gap-3">
            <LogoMarkV2 size={36} />
            <span className="text-2xl font-semibold tracking-tight">
              <span style={{ color: WHITE }}>Margin</span>
              <span style={{ color: LIGHT_GREEN }}>Maestro</span>
            </span>
          </div>
          <Link
            href="/login"
            className="rounded-full px-5 py-2 text-sm font-semibold transition-opacity hover:opacity-90"
            style={{ backgroundColor: LIGHT_GREEN, color: BLACK }}
          >
            Sign in
          </Link>
        </header>

        {/* ---------- hero ---------- */}
        <section className="relative overflow-hidden px-6 pt-10 pb-24">
          {/* Grid scoped to the hero section only (not header, not the
              tech strip further down), matching the earlier design
              exploration routes exactly: 64px squares, 0.04 opacity, simple
              top-to-bottom fade -- was previously on the whole dark zone
              at 86px/0.05 with a diagonal fade tied to the old (now
              removed) white transition, which cut it off early. */}
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
              <h1
                className="fade-up text-4xl font-semibold leading-[1.08] tracking-tight text-balance sm:text-5xl"
                style={{ color: WHITE }}
              >
                Stop reading documents.
                <br />
                <span style={{ color: LIGHT_GREEN }}>Start making decisions.</span>
              </h1>
              <p className="fade-up d1 max-w-md text-[15px] leading-relaxed text-white/70">
                AI agents watch every counterparty&apos;s exposure in real time, ground every
                threshold in the actual CSA agreement, and pause for a human before anything ever
                reaches a client.
              </p>
              <div className="fade-up d2 flex flex-wrap items-center gap-3">
                <Link
                  href="/login"
                  className="rounded-full px-6 py-3 text-sm font-semibold transition-opacity hover:opacity-90"
                  style={{ backgroundColor: LIGHT_GREEN, color: BLACK }}
                >
                  Sign in to the dashboard
                </Link>
                <a
                  href="#how-it-works"
                  className="rounded-full border border-white/20 px-6 py-3 text-sm font-medium transition-colors hover:bg-white/10"
                  style={{ color: WHITE }}
                >
                  See how it works
                </a>
              </div>
            </div>

            <div
              className="fade-up d3 w-full max-w-sm rounded-2xl p-5 shadow-2xl shadow-black/40"
              style={{ backgroundColor: WHITE, color: BLACK }}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-neutral-500">
                  Margin call · illustrative
                </span>
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

        {/* ---------- tech strip (dark zone, "soft white text" -- white/60,
            white/70 -- since it sits on dark green, not the neutral-500
            gray that worked when this lived in the white zone). ---------- */}
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

      {/* ---------- white zone: stats + how it works + CTA + footer ---------- */}
      <div style={{ backgroundColor: WHITE }}>

        {/* ---------- live stats ---------- */}
        <section className="px-6 py-16">
          <div className="mx-auto flex w-full max-w-4xl flex-col items-center gap-2 divide-y divide-black/10 sm:flex-row sm:divide-x sm:divide-y-0">
            <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
              <span className="font-mono text-4xl font-semibold" style={{ color: DARK_GREEN }}>
                <AnimatedNumber value={counterparties} />
              </span>
              <span className="text-xs text-neutral-600">Counterparties tracked, live</span>
            </div>
            <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
              <span className="font-mono text-4xl font-semibold" style={{ color: DARK_GREEN }}>
                <AnimatedNumber value={runsEvaluated} />
              </span>
              <span className="text-xs text-neutral-600">Margin-call runs evaluated</span>
            </div>
            <div className="flex flex-1 flex-col items-center gap-1 py-6 sm:py-0">
              <span className="font-mono text-4xl font-semibold" style={{ color: DARK_GREEN }}>
                <AnimatedNumber value={breachesCaught} />
              </span>
              <span className="text-xs text-neutral-600">Real breaches caught</span>
            </div>
          </div>
        </section>

        {/* ---------- how it works ---------- */}
        <section id="how-it-works" className="px-6 py-16">
          <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex max-w-md flex-col gap-5">
              <h2 className="text-3xl font-semibold leading-tight text-balance" style={{ color: BLACK }}>
                See every decision.
                <br />
                Not just the outcome.
              </h2>
              <ul className="flex flex-col gap-4 text-[15px] text-neutral-600">
                <li className="flex gap-3">
                  <span
                    className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: DARK_GREEN }}
                  />
                  Thresholds are pulled straight from the real CSA agreement via RAG -- never
                  guessed, never hard-coded.
                </li>
                <li className="flex gap-3">
                  <span
                    className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: DARK_GREEN }}
                  />
                  Every run leaves a full, step-by-step agent trace -- what ran, in what order,
                  what it found.
                </li>
                <li className="flex gap-3">
                  <span
                    className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ backgroundColor: DARK_GREEN }}
                  />
                  A margin call never fires on its own -- a human always approves before anything
                  reaches a client.
                </li>
              </ul>
            </div>

            <div
              className="w-full max-w-sm rounded-2xl border border-neutral-200 p-5 shadow-xl shadow-black/10"
              style={{ backgroundColor: WHITE, color: BLACK }}
            >
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

        {/* ---------- closing CTA ---------- */}
        <section className="px-6 py-20">
          <div
            className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 rounded-2xl border border-neutral-200 px-8 py-14 text-center shadow-xl shadow-black/10"
            style={{ backgroundColor: WHITE, color: BLACK }}
          >
            <h2 className="text-2xl font-semibold text-balance sm:text-3xl">
              Ready to watch it decide?
            </h2>
            <Link
              href="/login"
              className="rounded-full px-7 py-3 text-sm font-semibold transition-opacity hover:opacity-90"
              style={{ backgroundColor: LIGHT_GREEN, color: BLACK }}
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
