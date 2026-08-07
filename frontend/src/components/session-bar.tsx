"use client";

import { signOut, useSession } from "next-auth/react";

export function SessionBar() {
  const { data: session, status } = useSession();

  if (status !== "authenticated") return null;

  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-white/55">
        Signed in as <span className="font-mono text-white">{session.user.name}</span> (
        {session.user.role})
      </span>
      <button
        onClick={() => signOut({ callbackUrl: "/login" })}
        className="rounded-full border border-white/20 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-white/10"
      >
        Sign out
      </button>
    </div>
  );
}
