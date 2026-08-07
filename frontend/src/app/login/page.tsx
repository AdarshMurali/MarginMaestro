"use client";

import { Suspense, useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { LogoMarkV2 } from "@/components/logo-v2";
import { BLACK, LIGHT_GREEN, WHITE, HERO_GRADIENT } from "@/lib/brand";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const result = await signIn("credentials", {
      username,
      password,
      redirect: false,
    });
    setBusy(false);
    if (result?.error) {
      setError("Invalid username or password.");
      return;
    }
    router.push(searchParams.get("callbackUrl") ?? "/dashboard");
  };

  return (
    <div
      className="fade-up relative z-10 w-full max-w-sm rounded-2xl p-6 shadow-2xl shadow-black/40"
      style={{ backgroundColor: WHITE, color: BLACK }}
    >
      <h1 className="text-lg font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-neutral-500">Enter your credentials to reach the dashboard.</p>
      <form className="mt-6 flex flex-col gap-3" onSubmit={submit}>
        <input
          type="text"
          placeholder="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="rounded-lg border border-neutral-200 px-4 py-2.5 text-sm text-black outline-none transition-colors focus:border-[#D3F770] focus:ring-2 focus:ring-[#D3F770]/40"
        />
        <input
          type="password"
          placeholder="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-lg border border-neutral-200 px-4 py-2.5 text-sm text-black outline-none transition-colors focus:border-[#D3F770] focus:ring-2 focus:ring-[#D3F770]/40"
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy || !username || !password}
          className="mt-1 rounded-full px-6 py-2.5 text-sm font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          style={{ backgroundColor: LIGHT_GREEN, color: BLACK }}
        >
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <main
      className="login-v2 relative flex min-h-full flex-1 flex-col items-center justify-center gap-8 overflow-hidden px-6 py-16"
      style={{ background: HERO_GRADIENT }}
    >
      <style>{`
        .login-v2 .fade-up {
          animation: loginFadeUp 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
        }
        @keyframes loginFadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .login-v2 .fade-up { animation: none; }
        }
      `}</style>

      {/* Same 64px/0.04-opacity grid as the landing hero, top-to-bottom fade */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(255,255,255,0.04) 0px, rgba(255,255,255,0.04) 1px, transparent 1px, transparent 64px)," +
            "repeating-linear-gradient(90deg, rgba(255,255,255,0.04) 0px, rgba(255,255,255,0.04) 1px, transparent 1px, transparent 64px)",
          maskImage: "linear-gradient(to bottom, black, transparent)",
        }}
      />

      <Link href="/" className="relative z-10 flex flex-col items-center gap-3 text-center">
        <div className="flex items-center gap-3">
          <LogoMarkV2 size={40} />
          <span className="text-2xl font-semibold tracking-tight">
            <span style={{ color: WHITE }}>Margin</span>
            <span style={{ color: LIGHT_GREEN }}>Maestro</span>
          </span>
        </div>
        <span className="max-w-sm text-sm text-white/70">
          Stop reading documents. Start making decisions.
        </span>
      </Link>

      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>

      <div className="relative z-10 flex flex-col items-center gap-2 text-center">
        <p className="max-w-sm text-xs text-white/50">
          Demo accounts: approver / viewer -- ask the team for credentials.
        </p>
        <Link href="/" className="text-xs text-white/50 underline-offset-4 hover:text-white/80 hover:underline">
          &larr; Back to home
        </Link>
      </div>
    </main>
  );
}
