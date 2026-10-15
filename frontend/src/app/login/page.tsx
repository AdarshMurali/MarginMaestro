"use client";

import { Suspense, useEffect, useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";

import { LogoMarkV2 } from "@/components/logo-v2";
import { getHealth } from "@/lib/api";
import { MUTED, LINE, TEXT_RED } from "@/lib/brand";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Warm-up: the API on Cloud Run scales to zero, and booting it takes ~30 s.
  // Pinging it while the user types their password means the dashboard
  // usually finds it warm, at no cost (no always-on instance).
  useEffect(() => {
    getHealth().catch(() => {
      // Best effort only; the dashboard reports a real outage itself.
    });
  }, []);

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
    <div className="fade-up relative z-10 w-full max-w-sm rounded-2xl border p-6 shadow-sm" style={{ borderColor: LINE }}>
      <h1 className="text-lg font-bold">Sign in</h1>
      <p className="mt-1 text-sm" style={{ color: MUTED }}>
        Enter your credentials to reach the dashboard.
      </p>
      <form className="mt-6 flex flex-col gap-3" onSubmit={submit}>
        <input
          type="text"
          placeholder="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="rounded-lg border border-[#D4D4D4] px-4 py-2.5 text-sm text-[#0A0A0A] outline-none transition-colors focus:border-[#0A0A0A] focus:ring-2 focus:ring-[#0A0A0A]/10"
        />
        <input
          type="password"
          placeholder="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-lg border border-[#D4D4D4] px-4 py-2.5 text-sm text-[#0A0A0A] outline-none transition-colors focus:border-[#0A0A0A] focus:ring-2 focus:ring-[#0A0A0A]/10"
        />
        {error && (
          <p className="text-sm" style={{ color: TEXT_RED }}>
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !username || !password}
          className="mt-1 inline-flex min-h-11 items-center justify-center rounded-[10px] bg-[#0A0A0A] px-6 text-sm font-bold text-white transition-colors hover:bg-[#262626] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <main className="login relative flex min-h-full flex-1 flex-col items-center justify-center gap-8 bg-white px-6 py-16 text-[#0A0A0A]">
      <style>{`
        .login .fade-up {
          animation: loginFadeUp 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
        }
        @keyframes loginFadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .login .fade-up { animation: none; }
        }
      `}</style>

      <Link href="/" className="relative z-10 flex flex-col items-center gap-3 text-center">
        <div className="flex items-center gap-3">
          <LogoMarkV2 size={40} />
          <span className="text-2xl font-extrabold tracking-tight">
            Margin<span className="font-medium">Maestro</span>
          </span>
        </div>
        <span className="max-w-sm text-sm" style={{ color: MUTED }}>
          Stop reading documents. Start making decisions.
        </span>
      </Link>

      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>

      <div className="relative z-10 flex flex-col items-center gap-2 text-center">
        <p className="max-w-sm text-xs" style={{ color: MUTED }}>
          Demo accounts: approver / analyst1 / manager / auditor -- see the README for passwords.
        </p>
        <Link href="/" className="text-xs underline-offset-4 hover:underline" style={{ color: MUTED }}>
          &larr; Back to home
        </Link>
      </div>
    </main>
  );
}
