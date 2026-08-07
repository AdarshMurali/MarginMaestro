import { Logo, LogoMark } from "@/components/logo";
import { LogoV2, LogoMarkV2 } from "@/components/logo-v2";

const SIZES = [24, 32, 48, 96];

function Swatch({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-border bg-card p-6">
      <div className="flex items-end gap-6">{children}</div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

export default function LogoPreviewPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-12 px-6 py-16">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Logo comparison</h1>
        <p className="text-sm text-muted-foreground">
          Current mark (&ldquo;M&rdquo; chevron) vs. the alternate &ldquo;margin call&rdquo; mark
          (handset + dollar badge), inspired by the reference sketch. Nothing here is wired up
          yet -- this page exists only to compare the two side by side.
        </p>
      </header>

      <section className="space-y-4">
        <h2 className="text-sm font-medium text-muted-foreground">Mark only, at size</h2>
        <div className="grid grid-cols-2 gap-4">
          <Swatch label="Current -- LogoMark">
            {SIZES.map((s) => (
              <LogoMark key={s} size={s} />
            ))}
          </Swatch>
          <Swatch label="Alternate -- LogoMarkV2">
            {SIZES.map((s) => (
              <LogoMarkV2 key={s} size={s} />
            ))}
          </Swatch>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="text-sm font-medium text-muted-foreground">Full lockup</h2>
        <div className="grid grid-cols-1 gap-4">
          <Swatch label="Current -- Logo">
            <Logo size={40} showTagline />
          </Swatch>
          <Swatch label="Alternate -- LogoV2">
            <LogoV2 size={40} showTagline />
          </Swatch>
        </div>
      </section>
    </div>
  );
}
