import { cn } from "@/lib/utils";

/** The brand mark alone: a rounded tile with a bold "M" stroke, styled as a
 * margin/threshold line crossing a chart. Kept to a single glyph (not a
 * literal doubled "MM") at icon size -- two interlocked letterforms turn to
 * mush at 16-24px, so the "MM" idea lives in the wordmark's two-tone
 * treatment instead (see Logo below). */
export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
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
      <rect width="32" height="32" rx="7" className="fill-card" />
      <path
        d="M8 23V9L16 17L24 9V23"
        className="stroke-primary"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

interface LogoProps {
  size?: number;
  showTagline?: boolean;
  className?: string;
}

/** Full lockup: mark + wordmark, "Margin" in the foreground color and
 * "Maestro" in the brand gold -- the "MM" idea reads through the two-tone
 * split rather than a doubled glyph. */
export function Logo({ size = 32, showTagline = false, className }: LogoProps) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <LogoMark size={size} />
      <div className="flex flex-col leading-tight">
        <span className="font-heading text-lg font-semibold tracking-tight">
          <span className="text-foreground">Margin</span>
          <span className="text-primary">Maestro</span>
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
