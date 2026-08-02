import type { ExposureStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_META: Record<ExposureStatus, { label: string; colorClass: string }> = {
  healthy: { label: "Healthy", colorClass: "bg-status-success" },
  at_risk: { label: "At risk", colorClass: "bg-status-warning" },
  breached: { label: "Breached", colorClass: "bg-status-danger" },
  unavailable: { label: "Unavailable", colorClass: "bg-muted-foreground" },
};

export function StatusLight({
  status,
  className,
}: {
  status: ExposureStatus;
  className?: string;
}) {
  const meta = STATUS_META[status];
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className={cn("inline-block h-2.5 w-2.5 shrink-0 rounded-full", meta.colorClass)} />
      <span className="text-sm">{meta.label}</span>
    </span>
  );
}
