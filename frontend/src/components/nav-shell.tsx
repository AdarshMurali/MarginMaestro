"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";

import { LogoMarkV2 } from "@/components/logo-v2";
import { SessionBar } from "@/components/session-bar";
import { BLACK, LIGHT_GREEN, WHITE } from "@/lib/brand";
import { cn } from "@/lib/utils";

const TABS: { href: string; label: string; isActive: (pathname: string) => boolean }[] = [
  { href: "/dashboard", label: "Home", isActive: (p) => p === "/dashboard" },
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

const NO_CHROME_ROUTES = new Set(["/", "/login", "/landing", "/landing-v3", "/logo-preview"]);

/** Persistent nav shell (MM-58) -- wraps every authenticated page with the
 * brand mark, the six Phase 8 tabs, and the session bar. Renders nothing but
 * `children` on "/" (public landing page, promoted from landing-v2 on
 * 2026-08-06 -- has its own header, no session yet), /login (own centered
 * layout, no session yet), /landing* (earlier standalone design-exploration
 * routes, 2026-08-03), or /logo-preview (standalone logo comparison page,
 * 2026-08-05), or before a session exists. */
export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { status } = useSession();

  if (NO_CHROME_ROUTES.has(pathname) || status !== "authenticated") {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header
        className="flex flex-col gap-3 border-b border-white/10 px-6 py-3 sm:flex-row sm:items-center sm:justify-between"
        style={{ backgroundColor: BLACK }}
      >
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="flex items-center gap-2">
            <LogoMarkV2 size={24} />
            <span className="font-heading text-sm font-semibold tracking-tight">
              <span style={{ color: WHITE }}>Margin</span>
              <span style={{ color: LIGHT_GREEN }}>Maestro</span>
            </span>
          </Link>
          <nav className="flex flex-wrap items-center gap-1">
            {TABS.map((tab) => (
              <Link
                key={tab.href}
                href={tab.href}
                className={cn(
                  "rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                  tab.isActive(pathname) ? "bg-white/10" : "text-white/55 hover:text-white",
                )}
                style={tab.isActive(pathname) ? { color: LIGHT_GREEN } : undefined}
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
