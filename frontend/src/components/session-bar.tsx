"use client";

import { signOut, useSession } from "next-auth/react";

export function SessionBar() {
  const { data: session, status } = useSession();

  if (status !== "authenticated") return null;

  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-[#5C5C5C]">
        Signed in as <span className="font-mono font-medium text-[#0A0A0A]">{session.user.name}</span>{" "}
        ({session.user.role})
      </span>
      <button
        onClick={() => signOut({ callbackUrl: "/login" })}
        className="min-h-9 rounded-lg border border-[#D4D4D4] px-3 text-xs font-semibold text-[#0A0A0A] transition-colors hover:bg-[#F7F7F7]"
      >
        Sign out
      </button>
    </div>
  );
}
