import { cn } from "@/lib/utils";

// Exact palette given by the user (2026-08-03) for the landing-v2 exploration
// -- reused here since this mark is meant to sit alongside that design, not
// the app's default gold token. Light green (not dark green) is the accent,
// matching AlertLogoMark in landing-v2/page.tsx.
const BLACK = "#090909";
const LIGHT_GREEN = "#D3F770";

/**
 * ALTERNATE brand mark -- exploration only, not wired into NavShell/Logo.
 * Concept: a "margin call" is literally a phone call, so the mark is a
 * handset (Material "call" glyph, Apache-2.0) paired with a dollar badge.
 * One wave arc sits inside the same circle as the "$" -- not wrapping it
 * from outside, not duplicated -- matching the reference sketch in
 * Screenshot 2026-08-05 085741.png, where the wave lines live inside the
 * bubble alongside the dollar sign. Lives alongside `logo.tsx` (the "M"
 * chevron mark) purely so the two can be compared -- see /logo-preview.
 */
export function LogoMarkV2({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="MarginMaestro"
    >
      <rect width="32" height="32" rx="7" fill={BLACK} />

      {/* handset (Material Icons "call" glyph, scaled/translated into the
          lower-left of the tile) */}
      <g transform="translate(4.5,5) scale(0.72)">
        <path
          d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"
          fill={LIGHT_GREEN}
        />
      </g>

      {/* dollar badge, upper-right -- a single circle holding both the "$"
          and the one wave arc, nested inside it */}
      <circle cx="23" cy="10" r="6.5" fill={LIGHT_GREEN} />
      <text
        x="21.7"
        y="13"
        textAnchor="middle"
        fontSize="8"
        fontWeight="700"
        fill={BLACK}
        style={{ fontFamily: "var(--font-geist-sans, sans-serif)" }}
      >
        $
      </text>
      <path
        d="M25.57 6.94A4 4 0 0 1 25.57 13.06"
        stroke={BLACK}
        strokeWidth="1.1"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

interface LogoV2Props {
  size?: number;
  showTagline?: boolean;
  className?: string;
}

/** Full lockup for the alternate mark, mirroring Logo's layout/API so it
 * drops in for side-by-side comparison. */
export function LogoV2({ size = 32, showTagline = false, className }: LogoV2Props) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <LogoMarkV2 size={size} />
      <div className="flex flex-col leading-tight">
        <span className="font-heading text-lg font-semibold tracking-tight">
          <span className="text-foreground">Margin</span>
          <span style={{ color: LIGHT_GREEN }}>Maestro</span>
        </span>
        {showTagline ? (
          <span className="text-xs text-muted-foreground">
            Stop reading documents. Start making decisions.
          </span>
        ) : null}
      </div>
    </div>
  );
}
