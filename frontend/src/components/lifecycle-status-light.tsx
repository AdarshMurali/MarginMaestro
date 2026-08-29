import type { MarginCallLifecycleStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

// Fixed pill width (not just a dot + variable-length text) so a short label
// ("Evaluating") and a long one ("Awaiting 2nd sign-off") occupy the same
// footprint -- found live: inconsistent status-label width was throwing off
// column alignment for everything after it in a list row. Tint + dot color
// stays tied to the same four-state semantic (success/warning/danger/info)
// used everywhere else; only "meaningful outcome" states (success/warning/
// danger) get color weight, in-progress states stay neutral on purpose.
const STATUS_META: Record<
  MarginCallLifecycleStatus,
  { label: string; dotClass: string; pillClass: string }
> = {
  evaluating: {
    label: "Evaluating",
    dotClass: "bg-status-info",
    pillClass: "bg-neutral-100 text-neutral-600",
  },
  no_breach: {
    label: "No breach",
    dotClass: "bg-status-success",
    pillClass: "bg-status-success/20 text-[#20463B]",
  },
  awaiting_approval: {
    label: "Awaiting approval",
    dotClass: "bg-status-info",
    pillClass: "bg-neutral-100 text-neutral-600",
  },
  awaiting_manager_approval: {
    label: "Awaiting 2nd sign-off",
    dotClass: "bg-status-info",
    pillClass: "bg-neutral-100 text-neutral-600",
  },
  rejected: {
    label: "Rejected",
    dotClass: "bg-status-warning",
    pillClass: "bg-status-warning/10 text-status-warning",
  },
  disputed: {
    label: "Disputed",
    dotClass: "bg-status-warning",
    pillClass: "bg-status-warning/10 text-status-warning",
  },
  awaiting_sla_response: {
    label: "Awaiting response",
    dotClass: "bg-status-info",
    pillClass: "bg-neutral-100 text-neutral-600",
  },
  sla_met: {
    label: "Resolved",
    dotClass: "bg-status-success",
    pillClass: "bg-status-success/20 text-[#20463B]",
  },
  escalated: {
    label: "Escalated",
    dotClass: "bg-status-danger",
    pillClass: "bg-status-danger/10 text-status-danger",
  },
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
    <span
      className={cn(
        "inline-flex w-[10.5rem] shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        meta.pillClass,
        className,
      )}
    >
      <span className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", meta.dotClass)} />
      <span className="truncate">{meta.label}</span>
    </span>
  );
}
