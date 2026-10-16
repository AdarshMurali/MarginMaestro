export { auth as proxy } from "@/lib/auth";

// Whole app requires login (confirmed design decision, MM-57), except:
// - "/" itself: the public landing page -- this is where users land first
//   and get the option to sign in, so it can't require a session already.
// - /login and NextAuth's own API routes.
// - /api/public, /api/health, /api/ready: the landing page's live stats
//   (and health checks) call these through the same-origin `/api/*` rewrite
//   (MM-103's mixed-content fix) with no session yet -- without this
//   exemption the proxy redirects them to /login before the rewrite ever
//   reaches the backend's actually-unauthenticated endpoints, and the
//   landing page's stats silently show "--" (found live, MM-147 follow-up).
// Every other route redirects to /login via NextAuth's `auth` wrapper,
// which redirects automatically when `pages.signIn` is configured and
// there is no session.
//
// The earlier /landing, /landing-v3, /landing-apple/-mono/-v4/-aurum and
// /logo-preview design-exploration routes (2026-08-03 .. 2026-09-17) were
// removed once the White Paper theme (MM-147, 2026-10-15) picked a winner;
// "/" and /login carry that theme directly now.
export const config = {
  matcher: [
    "/((?!api/auth|api/public|api/health|api/ready|_next/static|_next/image|favicon.ico|$).*)",
  ],
};
