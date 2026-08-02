/** NEXT_PUBLIC_* vars are inlined at build time and shipped to the browser --
 * fine here since it's just the API's base URL, never a secret. */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";
