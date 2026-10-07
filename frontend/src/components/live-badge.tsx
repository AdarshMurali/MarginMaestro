import { cn } from "@/lib/utils";

/** MM-146: whether the page is on Firestore's live push or the polling fallback. */
export function LiveBadge({ live, pollSeconds }: { live: boolean; pollSeconds: number }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-neutral-500"
      title={
        live
          ? "Status changes are pushed to this page the moment they happen."
          : `Refreshing every ${pollSeconds}s.`
      }
    >
      <span
        className={cn("h-2 w-2 rounded-full", live ? "bg-[#16a34a]" : "bg-neutral-300")}
        aria-hidden
      />
      {live ? "Live" : `Auto-refresh ${pollSeconds}s`}
    </span>
  );
}
