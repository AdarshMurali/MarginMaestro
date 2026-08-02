export { auth as proxy } from "@/lib/auth";

// Whole app requires login (confirmed design decision, MM-57): every route
// redirects to /login until authenticated, except /login itself and
// NextAuth's own API routes. NextAuth's `auth` wrapper redirects
// automatically when `pages.signIn` is configured and there is no session.
export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"],
};
