"use client";

import { signOut, useSession } from "next-auth/react";

import { Button } from "@/components/ui/button";

export function SessionBar() {
  const { data: session, status } = useSession();

  if (status !== "authenticated") return null;

  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span>
        Signed in as <span className="font-mono">{session.user.name}</span> (
        {session.user.role})
      </span>
      <Button size="sm" variant="outline" onClick={() => signOut({ callbackUrl: "/login" })}>
        Sign out
      </Button>
    </div>
  );
}
