import type { NextConfig } from "next";

// MM-146: the Firebase web config for the real-time listener (public, not a
// secret). Set NEXT_PUBLIC_FIREBASE_* explicitly (Vercel, local), or let
// Firebase App Hosting supply it: App Hosting sets FIREBASE_WEBAPP_CONFIG (a
// JSON object) at build time for the backend's web app. Absent both, the
// frontend keeps polling.
function firebaseWebEnv(): Record<string, string> {
  let fromAppHosting: Record<string, string> = {};
  try {
    fromAppHosting = JSON.parse(process.env.FIREBASE_WEBAPP_CONFIG ?? "{}");
  } catch {
    fromAppHosting = {};
  }
  // `||`, not `??`: an explicitly empty value (.env.example) also falls back.
  const pick = (explicit: string | undefined, key: string) =>
    explicit || fromAppHosting[key] || "";
  return {
    NEXT_PUBLIC_FIREBASE_API_KEY: pick(process.env.NEXT_PUBLIC_FIREBASE_API_KEY, "apiKey"),
    NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN: pick(
      process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
      "authDomain",
    ),
    NEXT_PUBLIC_FIREBASE_PROJECT_ID: pick(process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID, "projectId"),
    NEXT_PUBLIC_FIREBASE_APP_ID: pick(process.env.NEXT_PUBLIC_FIREBASE_APP_ID, "appId"),
  };
}

const nextConfig: NextConfig = {
  env: firebaseWebEnv(),
  // Deployed on Vercel (HTTPS) against a backend that's currently HTTP-only
  // (no domain/cert yet -- see docs/ROADMAP.md Phase 10). A browser page
  // served over HTTPS can't fetch a plain http:// URL directly (blocked as
  // mixed content), so client-side calls go to this same origin's /api/*
  // instead (see NEXT_PUBLIC_API_BASE_URL=/api in Vercel's env vars) and get
  // proxied here, server-side, where mixed-content rules don't apply.
  //
  // Uses the `fallback` rewrite phase specifically (not a plain array,
  // which becomes `afterFiles`) -- `fallback` rewrites are only checked
  // *after* dynamic routes, so /api/auth/[...nextauth]'s real route handler
  // still wins for NextAuth's own paths; only otherwise-unmatched /api/*
  // requests (the backend calls) fall through to this proxy. Confirmed
  // against this Next.js version's own bundled rewrites.md before writing
  // this -- an `afterFiles`/plain-array rewrite would have shadowed
  // NextAuth's dynamic route instead of losing to it.
  async rewrites() {
    const backendUrl = process.env.BACKEND_API_URL;
    if (!backendUrl) return { fallback: [] };
    return {
      fallback: [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }],
    };
  },
};

export default nextConfig;
