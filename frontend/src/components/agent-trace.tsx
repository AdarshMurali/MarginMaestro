"use client";

import { motion } from "framer-motion";

import type { TraceStep } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.12 } },
};

const item = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0 },
};

export function AgentTrace({ steps }: { steps: TraceStep[] }) {
  return (
    <motion.ol variants={container} initial="hidden" animate="show" className="flex flex-col">
      {steps.map((step, index) => (
        <motion.li
          key={step.step}
          variants={item}
          className="relative flex gap-4 pb-8 last:pb-0"
        >
          {index < steps.length - 1 && (
            <span className="absolute top-4 left-[7px] h-full w-px bg-neutral-200" />
          )}
          <span
            className={cn(
              "relative z-10 mt-1 h-4 w-4 shrink-0 rounded-full border-2 border-white",
              step.status === "completed" ? "bg-status-success" : "animate-pulse bg-status-info",
            )}
          />
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="font-medium text-black">{step.node}</span>
              {step.status === "in_progress" && (
                <span className="text-xs text-status-info">in progress</span>
              )}
            </div>
            <p className="text-sm text-neutral-500">{step.summary}</p>
            {step.completed_at && (
              <span className="font-mono text-xs text-neutral-500">
                {formatDateTime(step.completed_at)}
              </span>
            )}
          </div>
        </motion.li>
      ))}
    </motion.ol>
  );
}
