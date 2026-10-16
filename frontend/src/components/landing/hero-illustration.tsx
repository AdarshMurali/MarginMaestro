import { INK, MUTED, STATUS_GREEN, STATUS_RED, TEXT_RED } from "@/lib/brand";

/**
 * Landing-page hero illustration (MM-147): one margin call told in three
 * beats -- exposure climbs through the CSA threshold, a call is drafted with
 * the clause cited, and a person approves it. Pure SVG + CSS (classes in
 * globals.css, `mm-` prefix); it plays once on load and shows its final
 * frame for people who prefer reduced motion. Illustrative, not live data.
 */
export function HeroIllustration() {
  return (
    <figure className="relative w-full max-w-[540px]" aria-label="Illustration of a margin call being raised and approved">
      <div className="rounded-2xl border border-[#E5E5E5] bg-white p-5 shadow-[0_24px_60px_-28px_rgba(0,0,0,0.25)]">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-semibold text-[#0A0A0A]">Lindqvist Partners · exposure</span>
          <span className="rounded-full bg-[#F4F4F4] px-2 py-0.5 font-medium" style={{ color: MUTED }}>
            Illustration
          </span>
        </div>

        <svg viewBox="0 0 520 280" className="mt-3 block h-auto w-full" role="img" aria-hidden>
          {/* grid */}
          {[60, 110, 160, 210, 250].map((y) => (
            <line key={y} x1="40" x2="500" y1={y} y2={y} stroke="#F0F0F0" strokeWidth="1" />
          ))}
          {/* over-threshold zone */}
          <rect x="40" y="30" width="460" height="80" fill="#FDF0F0" />
          {/* CSA threshold */}
          <line x1="40" x2="500" y1="110" y2="110" stroke={INK} strokeWidth="1.5" strokeDasharray="5 5" />
          <text x="44" y="102" fontSize="11" fontWeight="700" fill={INK}>
            CSA threshold · $4.5M
          </text>
          {/* exposure line, drawn on load */}
          <polyline
            className="mm-draw"
            pathLength={1}
            points="40,236 105,214 160,222 225,182 285,170 340,132 400,92 460,70 500,58"
            fill="none"
            stroke={INK}
            strokeWidth="3"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {/* breach point */}
          <circle className="mm-ping" cx="364" cy="110" r="14" fill={STATUS_RED} opacity="0.25" />
          <circle className="mm-pop" style={{ animationDelay: "1.5s" }} cx="364" cy="110" r="6" fill={STATUS_RED} stroke="#fff" strokeWidth="2.5" />
          <text className="mm-pop" style={{ animationDelay: "1.6s" }} x="376" y="132" fontSize="11" fontWeight="700" fill={TEXT_RED}>
            breach 09:42
          </text>
          {/* axis labels */}
          <text x="40" y="270" fontSize="10" fill={MUTED}>
            Mon
          </text>
          <text x="470" y="270" fontSize="10" fill={MUTED}>
            Today
          </text>
        </svg>
      </div>

      {/* beat 2: the call is drafted, clause cited */}
      <div
        className="mm-pop relative mt-3 w-full sm:absolute sm:-bottom-6 sm:mt-0 sm:w-[250px] rounded-xl border border-[#E5E5E5] bg-white p-4 shadow-[0_18px_40px_-20px_rgba(0,0,0,0.3)] sm:-left-8"
        style={{ animationDelay: "2s" }}
      >
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em]" style={{ color: MUTED }}>
          Margin call drafted
        </div>
        <div className="mt-1 font-mono text-2xl font-semibold tracking-tight">$620,000</div>
        <div className="mt-1 text-xs" style={{ color: MUTED }}>
          Threshold from CSA §11(a), clause cited
        </div>
      </div>

      {/* beat 3: a person approves; the notice goes out */}
      <div
        className="mm-pop relative mt-2 flex items-center sm:absolute sm:-right-6 sm:-top-5 sm:mt-0 gap-2.5 rounded-xl bg-[#0A0A0A] px-3.5 py-2.5 text-white shadow-[0_18px_40px_-18px_rgba(0,0,0,0.45)]"
        style={{ animationDelay: "3.1s" }}
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full" style={{ backgroundColor: STATUS_GREEN }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M5 12l5 5L20 7" />
          </svg>
        </span>
        <span className="text-xs leading-tight">
          <span className="block font-semibold">Approved by the desk</span>
          <span className="flex items-center gap-1 text-[#BDBDBD]">
            {/* eslint-disable-next-line @next/next/no-img-element -- static brand SVG */}
            <img src="/logos/whatsapp.svg" alt="" width={12} height={12} />
            notice sent to client
          </span>
        </span>
      </div>
    </figure>
  );
}
