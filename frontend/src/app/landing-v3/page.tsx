"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { getExposureBoard, getMarginCallFeed } from "@/lib/api";
import { LogoMarkV2 } from "@/components/logo-v2";

const STACK = ["LangGraph", "OpenAI", "ChromaDB", "Kafka", "Azure SQL", "FastAPI"];

// Exact palette given by the user (2026-08-03), v2 comparison route:
const BLACK = "#090909";
const DARK_GREEN = "#20463B";
const LIGHT_GREEN = "#D3F770";
const WHITE = "#FFFFFF";

function AnimatedNumber({ value }: { value: number | null }) {
  return <span>{value === null ? "--" : value.toLocaleString()}</span>;
}

export default function LandingPageV3() {
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
    <main className="landing-v3 flex min-h-full flex-col" style={{ backgroundColor: WHITE }}>
      <style>{`
        .landing-v3 { --primary: ${DARK_GREEN}; }
        .landing-v3 .fade-up {
          animation: landingFadeUp 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
        }
        .landing-v3 .fade-up.d1 { animation-delay: 80ms; }
        .landing-v3 .fade-up.d2 { animation-delay: 160ms; }
        .landing-v3 .fade-up.d3 { animation-delay: 240ms; }
        @keyframes landingFadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .landing-v3 .fade-up { animation: none; }
        }
      `}</style>

      {/* ---------- dark zone: header + hero ----------
          Copied from landing-v2 (2026-08-05) at the user's request, to
          A/B a flat background against v2's tuned gradient -- "not
          convinced with the gradient." Confirmed by tracing the actual v2
          gradient stops that its top (header area) is solid BLACK, not
          green -- 187.13deg gradient puts the whole top row at 0-28.5%,
          entirely inside the "BLACK 0%..51.15%" stop range -- user
          confirmed BLACK is correct. Final: solid BLACK for the *entire*
          hero box (same full height as v2's dark zone), white only
          starting where the white zone already begins (right before "The
          real stack underneath") -- not a 50/50 split, that was a
          misread of "upper half" as inside the hero rather than the hero
          itself. No gradient, one flat color for the whole 602px. */}
      <div
        className="relative overflow-hidden"
        style={{
          minHeight: "602px",
          backgroundColor: BLACK,
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
          {/* Grid scoped to the hero section only (not header, not tech
              strip) and sized/faded to match the original /landing v1
              treatment exactly: 64px squares (was 86px), 0.04 opacity
              (was 0.05), simple top-to-bottom fade so it thins out toward
              the bottom of the hero rather than covering the whole dark
              zone. */}
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

        {/* ---------- tech strip (moved inside the dark zone, matching the
            original /landing v1 layout at the user's request -- "soft
            white text" (white/60, white/70) since it now sits on black,
            not the neutral-500 gray that worked when this section lived
            in the white zone below). ---------- */}
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
