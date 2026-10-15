import { cn } from "@/lib/utils";

import { BRAND_GREEN, INK } from "@/lib/brand";

/**
 * Brand mark: "Call & Dollar" -- a margin call is a phone call about money.
 * Handset plus a $ badge with one wave arc inside it, recoloured for the
 * White Paper theme (2026-10-15): near-black tile, brand green glyphs.
 * Drawn on a 64-unit grid so it stays crisp from favicon size up.
 */
export function LogoMarkV2({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="MarginMaestro"
    >
      <rect width="64" height="64" rx="15" fill={INK} />
      {/* handset (Material Icons "call" glyph, Apache-2.0), lower left */}
      <g transform="translate(9,15) scale(1.55)">
        <path
          d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"
          fill={BRAND_GREEN}
        />
      </g>
      {/* dollar badge, upper right, holding the $ and one wave arc */}
      <circle cx="45" cy="19" r="11" fill={BRAND_GREEN} />
      <text
        x="43"
        y="24.5"
        textAnchor="middle"
        fontSize="14"
        fontWeight="800"
        fill={INK}
        style={{ fontFamily: "var(--font-sans, sans-serif)" }}
      >
        $
      </text>
      <path
        d="M49.5 12.5a8 8 0 0 1 0 13"
        stroke={INK}
        strokeWidth="2"
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
          <span className="font-medium">Maestro</span>
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
