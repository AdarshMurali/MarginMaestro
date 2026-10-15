"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";

import { LogoMarkV2 } from "@/components/logo-v2";
import { SessionBar } from "@/components/session-bar";
import { TickerTape } from "@/components/ticker-tape";
import { cn } from "@/lib/utils";

const TABS: { href: string; label: string; isActive: (pathname: string) => boolean }[] = [
  { href: "/dashboard", label: "Home", isActive: (p) => p === "/dashboard" },
  { href: "/exposure", label: "Exposure", isActive: (p) => p.startsWith("/exposure") },
  {
    href: "/margin-calls",
    label: "Margin calls",
    isActive: (p) => p === "/margin-calls",
  },
  { href: "/approvals", label: "Approvals & SLA", isActive: (p) => p === "/approvals" },
  {
    href: "/agent-trace",
    label: "Agent trace",
    isActive: (p) => p === "/agent-trace" || p.endsWith("/trace"),
  },
  { href: "/simulate", label: "Simulate", isActive: (p) => p === "/simulate" },
  { href: "/desk", label: "Ask the desk", isActive: (p) => p === "/desk" },
  { href: "/reports", label: "Reports", isActive: (p) => p === "/reports" },
];

const NO_CHROME_ROUTES = new Set(["/", "/login"]);

/** Persistent nav shell (MM-58; White Paper theme 2026-10-15) -- wraps every
 * authenticated page with a white top bar (brand mark, tabs, session) and a
 * black scrolling ticker tape. Renders only `children` on "/" (public
 * landing page, own header) and /login (own centered layout), or before a
 * session exists. */
export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { status } = useSession();

  if (NO_CHROME_ROUTES.has(pathname) || status !== "authenticated") {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-full flex-1 flex-col bg-white">
      <header className="border-b border-[#E5E5E5] bg-white">
        <div className="mx-auto flex min-h-16 w-full max-w-[1360px] flex-wrap items-center gap-x-7 gap-y-2 px-6 py-2">
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <LogoMarkV2 size={30} />
            <span className="text-base font-extrabold tracking-tight text-[#0A0A0A]">
              Margin<span className="font-medium">Maestro</span>
            </span>
          </Link>
          <nav aria-label="Primary" className="flex flex-wrap items-center gap-1">
            {TABS.map((tab) => {
              const active = tab.isActive(pathname);
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex min-h-10 items-center rounded-lg px-3 text-sm font-semibold transition-colors",
                    active
                      ? "bg-[#F2F2F2] text-[#0A0A0A]"
                      : "text-[#5C5C5C] hover:bg-[#F7F7F7] hover:text-[#0A0A0A]",
                  )}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex-1" />
          <SessionBar />
        </div>
      </header>
      <TickerTape />
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}
