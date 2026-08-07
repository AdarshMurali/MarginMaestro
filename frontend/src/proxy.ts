export { auth as proxy } from "@/lib/auth";

// Whole app requires login (confirmed design decision, MM-57), except:
// - "/" itself: the public landing page (promoted from landing-v2,
//   2026-08-06) -- this is where users land first and get the option to
//   sign in, so it can't require a session already.
// - /login and NextAuth's own API routes.
// - /landing, /landing-v3, /logo-preview: earlier standalone
//   design-exploration routes (2026-08-03/05), same reasoning as "/".
// Every other route redirects to /login via NextAuth's `auth` wrapper,
// which redirects automatically when `pages.signIn` is configured and
// there is no session.
export const config = {
  matcher: ["/((?!api/auth|landing|logo-preview|_next/static|_next/image|favicon.ico|$).*)"],
};
