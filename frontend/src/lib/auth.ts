import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { SignJWT } from "jose";

import { API_BASE_URL } from "@/lib/env";

const BACKEND_TOKEN_TTL_SECONDS = 15 * 60;

function backendSecretKey(): Uint8Array {
  const secret = process.env.AUTH_BACKEND_SECRET;
  if (!secret) {
    throw new Error("AUTH_BACKEND_SECRET is not configured");
  }
  return new TextEncoder().encode(secret);
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
      },
      // The only place a plaintext password exists on the frontend --
      // forwarded once to the backend's /auth/verify and discarded.
      async authorize(credentials) {
        if (!credentials?.username || !credentials?.password) return null;

        const res = await fetch(`${API_BASE_URL}/auth/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: credentials.username,
            password: credentials.password,
          }),
        });
        if (!res.ok) return null;

        const body = (await res.json()) as { username: string; role: string };
        return { id: body.username, name: body.username, role: body.role };
      },
    }),
  ],
  callbacks: {
    // Whole app requires login (MM-57 decision): no session -> proxy.ts
    // redirects to /login. Without this callback NextAuth's default is to
    // let every request through unauthenticated.
    authorized({ auth: session }) {
      return !!session;
    },
    async jwt({ token, user }) {
      if (user) {
        token.role = (user as { role: string }).role;
      }
      return token;
    },
    async session({ session, token }) {
      const role = token.role as string;
      session.user.role = role;
      // Short-lived JWT the frontend attaches as a Bearer header on
      // mutating FastAPI calls -- separate from NextAuth's own opaque
      // session-cookie encryption, which the backend never sees.
      session.backendAccessToken = await new SignJWT({ role })
        .setProtectedHeader({ alg: "HS256" })
        .setSubject(token.sub ?? session.user.name ?? "unknown")
        .setIssuedAt()
        .setExpirationTime(`${BACKEND_TOKEN_TTL_SECONDS}s`)
        .sign(backendSecretKey());
      return session;
    },
  },
});
