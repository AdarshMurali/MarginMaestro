"use client";

import { Suspense, useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";

import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

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
    router.push(searchParams.get("callbackUrl") ?? "/");
  };

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">Sign in</CardTitle>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <Input
            type="text"
            placeholder="Username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <Input
            type="password"
            placeholder="Password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="text-sm text-status-danger">{error}</p>}
          <Button type="submit" disabled={busy || !username || !password}>
            {busy ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-full flex-1 flex-col items-center justify-center gap-8 px-6 py-16">
      <Logo size={40} showTagline className="text-center" />

      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>

      <p className="max-w-sm text-center text-xs text-muted-foreground">
        Demo accounts: approver / viewer -- ask the team for credentials.
      </p>
    </main>
  );
}
