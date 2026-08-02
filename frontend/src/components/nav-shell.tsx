"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";

import { LogoMark } from "@/components/logo";
import { SessionBar } from "@/components/session-bar";
import { cn } from "@/lib/utils";

const TABS: { href: string; label: string; isActive: (pathname: string) => boolean }[] = [
  { href: "/", label: "Home", isActive: (p) => p === "/" },
  { href: "/exposure", label: "Positions & Exposure", isActive: (p) => p === "/exposure" },
  {
    href: "/margin-calls",
    label: "Margin Calls",
    isActive: (p) => p === "/margin-calls",
  },
  {
    href: "/agent-trace",
    label: "Agent Trace",
    isActive: (p) => p === "/agent-trace" || p.endsWith("/trace"),
  },
  { href: "/approvals", label: "Approvals & SLA", isActive: (p) => p === "/approvals" },
  { href: "/simulate", label: "Simulate Event", isActive: (p) => p === "/simulate" },
];

/** Persistent nav shell (MM-58) -- wraps every authenticated page with the
 * brand mark, the six Phase 8 tabs, and the session bar. Renders nothing but
 * `children` on /login or before a session exists, since that page has its
 * own centered layout and nothing to navigate to yet. */
export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { status } = useSession();

  if (pathname === "/login" || status !== "authenticated") {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="flex flex-col gap-3 border-b border-border px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2">
            <LogoMark size={24} />
            <span className="font-heading text-sm font-semibold tracking-tight">
              <span className="text-foreground">Margin</span>
              <span className="text-primary">Maestro</span>
            </span>
          </Link>
          <nav className="flex flex-wrap items-center gap-1">
            {TABS.map((tab) => (
              <Link
                key={tab.href}
                href={tab.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  tab.isActive(pathname)
                    ? "bg-card text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </Link>
            ))}
          </nav>
        </div>
        <SessionBar />
      </header>
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}
