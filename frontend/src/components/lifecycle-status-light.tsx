import type { MarginCallLifecycleStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_META: Record<MarginCallLifecycleStatus, { label: string; colorClass: string }> = {
  evaluating: { label: "Evaluating", colorClass: "bg-status-info" },
  no_breach: { label: "No breach", colorClass: "bg-status-success" },
  awaiting_approval: { label: "Awaiting approval", colorClass: "bg-status-info" },
  awaiting_manager_approval: { label: "Awaiting 2nd sign-off", colorClass: "bg-status-info" },
  rejected: { label: "Rejected", colorClass: "bg-status-warning" },
  disputed: { label: "Disputed", colorClass: "bg-status-warning" },
  awaiting_sla_response: { label: "Awaiting response", colorClass: "bg-status-info" },
  sla_met: { label: "Resolved", colorClass: "bg-status-success" },
  escalated: { label: "Escalated", colorClass: "bg-status-danger" },
};

export function LifecycleStatusLight({
  status,
  className,
}: {
  status: MarginCallLifecycleStatus;
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
