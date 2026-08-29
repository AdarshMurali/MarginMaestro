"use client";

import { motion } from "framer-motion";

import type { TraceStep } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

const item = {
  hidden: { opacity: 0, x: 16 },
  show: { opacity: 1, x: 0 },
};

// Horizontal, not vertical (found live: a vertical list makes an 8-step run
// require scrolling to see the whole lifecycle at once). Cards sit
// side by side, connected by a rail through each dot -- the rail segment
// right of a completed step's dot turns the same green as the dot, so the
// line itself reads as a progress bar, not just a divider. Cards grow
// (flex-1) to fill whatever width the page has, so a typical run shows its
// whole lifecycle with no scrolling at all; a min-width floor is the only
// thing that still triggers horizontal scroll, and only for a run with
// enough steps that even a wide window can't fit them at a readable size.
export function AgentTrace({ steps }: { steps: TraceStep[] }) {
  return (
    <div className="overflow-x-auto pb-1">
      <motion.ol
        variants={container}
        initial="hidden"
        animate="show"
        className="flex min-w-full"
      >
        {steps.map((step, index) => {
          const isLast = index === steps.length - 1;
          const completed = step.status === "completed";
          return (
            <motion.li
              key={step.step}
              variants={item}
              className="flex min-w-[9.5rem] flex-1 flex-col"
            >

              <div className="flex items-center">
                <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                  {!completed && (
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-info/50" />
                  )}
                  <span
                    className={cn(
                      "relative h-3.5 w-3.5 rounded-full",
                      completed ? "bg-status-success" : "bg-status-info",
                    )}
                  />
                </span>
                {!isLast && (
                  <span
                    className={cn("h-px flex-1", completed ? "bg-status-success" : "bg-neutral-200")}
                  />
                )}
              </div>
              <div className="flex flex-col gap-1 pt-3 pr-6">
                <span className="text-[10px] font-semibold tracking-[0.12em] text-neutral-400 uppercase">
                  Step {step.step + 1}
                </span>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm font-medium text-black">{step.node}</span>
                  {step.status === "in_progress" && (
                    <span className="text-[11px] font-medium text-status-info">in progress</span>
                  )}
                </div>
                <p className="text-xs leading-relaxed text-neutral-500">{step.summary}</p>
                {step.completed_at && (
                  <span className="font-mono text-[11px] text-neutral-400">
                    {formatDateTime(step.completed_at)}
                  </span>
                )}
              </div>
            </motion.li>
          );
        })}
      </motion.ol>
    </div>
  );
}
