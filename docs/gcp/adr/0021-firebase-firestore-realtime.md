# ADR-0021: Firebase App Hosting for the frontend, Firestore for real-time call status

- **Status:** Accepted
- **Date:** 2026-10-07 (stories MM-145, MM-146)

## Context

The frontend (Next.js 16) runs on Vercel and calls the API on Cloud Run through a same-origin `/api/*` rewrite. Margin calls change status in several places that aren't the browser looking at them: another approver signs, a manager gives the second signature, a client taps Acknowledge on WhatsApp, the Cloud Tasks SLA timer escalates, the daily run raises or re-evaluates a call. Until now the Approvals page polled `GET /margin-calls` every 30 s and the dashboard every 10 s.

Polling has three costs here:

1. **It keeps waking the backend.** Every open screen calls the API every N seconds. Each call wakes a scaled-to-zero Cloud Run instance, which reads every checkpoint from Cloud SQL. Ten open screens at 10 s are 3,600 API calls an hour while nothing is happening.
2. **It is late.** A change shows up after up to 30 s, so two people looking at the same queue can act on a call that is already decided.
3. **Push from Cloud Run itself doesn't fit.** WebSockets or Server-Sent Events from the API would need one long-lived connection per browser. Cloud Run bills an instance for as long as a request is open, and scale to zero stops working while any screen is connected. Fan-out across instances would also need a broker.

The AI Builder Cup 2026 (deadline 18 October) also expects Firebase, Firestore, Cloud Run and Gemini in a prototype deployed on GCP. The frontend was the one user-facing part not on GCP.

## Decision

### 1. Firestore carries a small status doc per call (MM-146)

- **One doc per margin call:** `margin_call_status/{thread_id}`, with the fields `thread_id`, `counterparty_id`, `status`, `call_amount`, `currency`, `sla_deadline`, `updated_at` and `book`. There are no names, notice text or rationale.
- **Written after every orchestrator invocation.** The start, each resume and each re-evaluation leave the run at rest, either paused at a gate or ended. `src/realtime/publisher.py` copies the same `MarginCallSummary` the `/margin-calls` feed returns. It computes nothing (ADR-0005), and the pushed status can't drift from the feed.
- **Best effort and idempotent.** A failed write logs a warning (`realtime_publish_failed`) and never fails the call. Each write replaces the whole doc. An unchanged status is not written again, so there are no extra writes or pushes.
- **Off by default.** `REALTIME=none` keeps local runs and AWS unchanged. Terraform sets `REALTIME=firestore` on Cloud Run.
- **Postgres stays the source of truth.** Firestore is a notification channel. The browser treats a pushed change as "something changed" and refetches its rows from the API, where row-level security applies (ADR-0011). If Firestore loses a doc, nothing is lost.

### 2. Per-user scope through custom-token claims and security rules

- **The token.** `GET /realtime/token` requires a logged-in user (`require_user`). It turns the caller's row-level-security scope (`scope_for`) into the custom claims `{firm_wide: bool, cps: [...]}`. The approver, manager and auditor are firm-wide; an analyst gets their own counterparties.
- **Signing.** The token is signed as `mm-api-sa` through the IAM Credentials `signBlob` API, using google-auth's `iam.Signer`. There is no key file and no firebase-admin dependency. The account needs `roles/iam.serviceAccountTokenCreator` on itself only.
- **The rules.** `firebase/firestore.rules`, deployed by Terraform, allow a signed-in user to read a status doc only if its `counterparty_id` is in `cps` or the token is `firm_wide`. That is the same rule as Postgres's `app_can_see()`. No client may write anything, and everything else is denied.
- **Sessions.** The browser keeps the Firebase session in memory only. A second user signing in on the same browser can't inherit the first user's scope.
- **Fallback.** With no Firebase web config on the host, or a 503 from the token endpoint (`REALTIME=none`), the page keeps its old polling.

### 3. The frontend also runs on Firebase App Hosting (MM-145)

- **Same app, same backend.** App Hosting builds `frontend/` from GitHub (`main`, automatic rollouts) and serves it from a managed Cloud Run service that scales to zero, in us-central1.
- **Vercel stays up.** Both hosts serve the same app against the same Cloud Run API, and they differ only in env: `frontend/apphosting.yaml` against Vercel's project settings. Secrets (`AUTH_SECRET`, `AUTH_BACKEND_SECRET`) come from Secret Manager; App Hosting resolves `secret:` references. The Firebase web config comes from App Hosting's build-time `FIREBASE_WEBAPP_CONFIG`.
- **Why App Hosting.** It is the managed Next.js host on GCP: SSR, `proxy.ts` and rewrites with no Dockerfile to maintain. It is part of Firebase, deploys on git push like Vercel, and scales to zero.
- **Alternative considered.** Cloud Run with our own container would need a Dockerfile, a CD job and CDN setup for the same result.

## Consequences

- **Updates are instant.** Approving a call in one browser updates every other open Approvals page and dashboard within about a second. Between changes no API call is made, Cloud Run and Cloud SQL stay idle, and Firestore holds the idle listeners.
- **Cost stays at about $0.**
  - **Firestore:** inside the free quota (1 GiB, 50k reads, 20k writes a day). Writes are one per lifecycle step. Firm-wide listeners watch the 50 most recently changed docs, so each page load reads at most 50 docs.
  - **Firebase Auth:** custom-token sign-in is free.
  - **App Hosting:** Cloud Run at min 0 is in the free tier. Cloud Build builds one Next.js build (about 4–6 min) per push to `main`, within the 2,500 free minutes a month. Images sit in a Google-managed Artifact Registry repo: 0.5 GB free, then $0.10/GB-month. Egress has 10 GiB/month at no cost.
  - **Expected:** about $0–0.10 a month. `app_hosting_auto_rollout = false` cuts the build minutes if needed.
- **Honest caveat.** At demo scale, with a few users and a handful of calls a day, 30-second polling also works. Firestore's value is real-time updates for many users at zero idle cost. It shows when several people work the same queue, or when a client's WhatsApp acknowledgement should show up on the desk the moment it happens.
- **New moving parts.**
  - A Firestore database, security rules, an App Hosting backend, a Developer Connect GitHub connection, and two frontend secrets whose values are duplicated from the API's `auth_backend_secret` and NextAuth's secret.
  - App Hosting needs a one-time GitHub authorization in the browser that Terraform can't do. It is gated by `app_hosting_github_connected`.
  - Firebase Authentication must be initialized once in the console ("Get started"; no provider is needed for custom tokens).
- **Scope changes reach the browser late.** A change to an analyst's access rows reaches their Firebase claims at the next token, on the next page load. The API's own reads are scoped per request as before.
