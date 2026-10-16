import Link from "next/link";

import { LogoMarkV2 } from "@/components/logo-v2";
import { BRAND_GREEN, MUTED, LINE, STATUS_AMBER, STATUS_GREEN, TEXT_AMBER } from "@/lib/brand";

// The lifecycle every margin call actually goes through -- shown here as
// the page's one bold visual, in the same rail idiom as the real in-app
// Agent Trace (components/agent-trace.tsx), so what a visitor sees here is
// what they'll see once they're signed in. Static on purpose: this is what
// the app always does, not a number that depends on a live backend being
// reachable (a previous version fetched /public/stats here and showed "--"
// whenever it wasn't).
const LIFECYCLE: { title: string; body: string; status: "done" | "running" }[] = [
  { title: "Price moves", body: "A market event reprices every book.", status: "done" },
  { title: "Exposure recomputed", body: "Code, not the model, computes VM and IM.", status: "done" },
  { title: "CSA checked", body: "Thresholds come from the real agreement, clause cited.", status: "done" },
  { title: "Human approves", body: "No call reaches a client until someone signs off.", status: "done" },
  { title: "Client notified", body: "A personalised notice carries the calculation and CSA terms.", status: "done" },
  { title: "SLA running", body: "A timer starts. No response in time escalates.", status: "running" },
];

const DIFFERENTIATORS = [
  { title: "Reads the agreement", body: "Thresholds come from each CSA, with the clause cited.", tech: "Gemini · RAG" },
  { title: "Calculates in code", body: "Every figure on a call is computed, never generated.", tech: "Python calc engine" },
  { title: "Waits for you", body: "No call reaches a client until a person approves it.", tech: "LangGraph · Cloud Run" },
];

export default function LandingPage() {
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

      {/* ---------- lifecycle ---------- */}
      <section id="how-it-works" className="border-t px-6 py-16" style={{ borderColor: LINE }}>
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
          <div className="max-w-xl">
            <h2 className="text-3xl font-extrabold leading-tight text-balance">
              From a price tick to a signed-off call
            </h2>
            <p className="mt-3 text-[15px]" style={{ color: MUTED }}>
              Every margin call follows the same six steps -- traced, not just logged.
            </p>
          </div>
          <ol className="flex overflow-x-auto pb-1">
            {LIFECYCLE.map((step, index) => {
              const isLast = index === LIFECYCLE.length - 1;
              const running = step.status === "running";
              return (
                <li key={step.title} className="flex min-w-[9.5rem] flex-1 flex-col">
                  <div className="flex items-center">
                    <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                      {running && (
                        <span
                          className="absolute inline-flex h-full w-full animate-ping rounded-full"
                          style={{ backgroundColor: STATUS_AMBER, opacity: 0.5 }}
                        />
                      )}
                      <span
                        className="relative h-3.5 w-3.5 rounded-full"
                        style={{ backgroundColor: running ? STATUS_AMBER : STATUS_GREEN }}
                      />
                    </span>
                    {!isLast && (
                      <span className="h-px flex-1" style={{ backgroundColor: STATUS_GREEN }} />
                    )}
                  </div>
                  <div className="flex flex-col gap-1 pt-3 pr-6">
                    <span className="text-sm font-bold">{step.title}</span>
                    <p className="text-xs leading-relaxed" style={{ color: MUTED }}>
                      {step.body}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      {/* ---------- differentiators ---------- */}
      <section className="border-t px-6 py-16" style={{ borderColor: LINE }}>
        <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-8 sm:grid-cols-3">
          {DIFFERENTIATORS.map((d) => (
            <div key={d.title} className="flex flex-col gap-1.5">
              <span className="text-lg font-extrabold">{d.title}</span>
              <span className="text-[14px]" style={{ color: "#3D3D3D" }}>
                {d.body}
              </span>
              <span className="font-mono text-xs" style={{ color: MUTED }}>
                {d.tech}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- closing CTA ---------- */}
      <section className="border-t px-6 py-16 text-center" style={{ borderColor: LINE }}>
        <h2 className="text-2xl font-extrabold text-balance sm:text-3xl">
          Ready to watch it decide?
        </h2>
        <Link
          href="/login"
          className="mt-6 inline-flex min-h-11 items-center rounded-[10px] bg-[#0A0A0A] px-7 text-sm font-bold text-white transition-colors hover:bg-[#262626]"
        >
          Sign in to the dashboard
        </Link>
      </section>

      <footer className="px-6 py-14" style={{ backgroundColor: "#0A0A0A" }}>
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-5 text-center">
          <LogoMarkV2 size={30} />
          <p className="max-w-sm text-sm" style={{ color: "#A3A3A3" }}>
            MarginMaestro -- a portfolio project. Data is real; scenarios are synthetic.
          </p>
          <p
            className="font-mono text-sm font-medium tracking-wide"
            style={{ color: BRAND_GREEN }}
          >
            LangGraph · Gemini on Vertex AI · Cloud SQL · pgvector · Pub/Sub · Firestore · Cloud Run
          </p>
        </div>
      </footer>
    </main>
  );
}
