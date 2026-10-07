import { getSession } from "next-auth/react";

import { API_BASE_URL } from "@/lib/env";

export interface HealthResponse {
  status: string;
}

export type ExposureStatus = "healthy" | "at_risk" | "breached" | "unavailable";

export interface PositionExposure {
  ticker: string;
  asset_class: string;
  quantity: number;
  price: number;
  mtm: number;
}

export interface CounterpartyExposure {
  counterparty_id: string;
  counterparty_name: string;
  positions: PositionExposure[];
  exposure: number | null;
  threshold: number | null;
  collateral_held: number | null;
  call_amount: number | null;
  status: ExposureStatus;
  currency: string;
  detail: string | null;
}

export interface ExposureBoardResponse {
  as_of: string;
  counterparties: CounterpartyExposure[];
}

export interface CounterpartySummary {
  counterparty_id: string;
  counterparty_name: string;
}

export interface CounterpartyListResponse {
  counterparties: CounterpartySummary[];
}

export interface PricePoint {
  date: string;
  price: number;
}

export interface PriceHistoryResponse {
  ticker: string;
  currency: string;
  points: PricePoint[];
}

export type MarginCallLifecycleStatus =
  | "evaluating"
  | "no_breach"
  | "awaiting_approval"
  | "awaiting_manager_approval"
  | "rejected"
  | "disputed"
  | "awaiting_sla_response"
  | "sla_met"
  | "escalated"
  | "below_materiality";

export interface MarginCallSummary {
  thread_id: string;
  correlation_id: string;
  counterparty_id: string;
  event_type: string;
  reason: string;
  occurred_at: string;
  status: MarginCallLifecycleStatus;
  call_amount: number | null;
  currency: string;
  approval_decision: string | null;
  sla_outcome: string | null;
  notification_sent_at: string | null;
  sla_deadline: string | null;
  rationale: string | null;
  updated_by: string[];
}

export interface MarginCallFeedResponse {
  as_of: string;
  margin_calls: MarginCallSummary[];
}

export interface MarginCallBucket {
  counterparty_id: string;
  counterparty_name: string;
  latest: MarginCallSummary;
  total_count: number;
}

export interface MarginCallBucketFeedResponse {
  as_of: string;
  buckets: MarginCallBucket[];
}

export type TraceStepStatus = "completed" | "in_progress";

export interface TraceStep {
  step: number;
  node: string;
  status: TraceStepStatus;
  completed_at: string | null;
  summary: string;
}

export interface MarginCallTraceResponse {
  thread_id: string;
  steps: TraceStep[];
}

// MM-106: every read endpoint requires the same short-lived backend JWT the
// mutating calls already use, so the backend (and Postgres row-level
// security) can scope rows to the logged-in user. The token lives 15 min
// (lib/auth.ts); re-read the session every 5 min rather than on every call.
const TOKEN_REUSE_MS = 5 * 60 * 1000;
let cachedToken: { value: string; fetchedAt: number } | null = null;

async function backendToken(): Promise<string | undefined> {
  if (cachedToken && Date.now() - cachedToken.fetchedAt < TOKEN_REUSE_MS) {
    return cachedToken.value;
  }
  const session = await getSession();
  const token = session?.backendAccessToken;
  cachedToken = token ? { value: token, fetchedAt: Date.now() } : null;
  return token;
}

async function getJson<T>(path: string, { auth = true }: { auth?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (auth) {
    const token = await backendToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE_URL}${path}`, { headers });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, token: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    // FastAPI error responses carry the real reason in a {"detail": "..."}
    // body (e.g. a 409 explaining exactly which step a margin call is
    // actually paused at) -- surfacing it here, not just the status code,
    // is what lets callers show that instead of a generic failure message.
    let detail: string | undefined;
    try {
      const payload = (await res.json()) as { detail?: string };
      detail = payload?.detail;
    } catch {
      // Response body wasn't JSON (or was empty) -- fall through to the
      // generic status-based message below.
    }
    throw new Error(detail ?? `POST ${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health", { auth: false });
}

export function getReady(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/ready", { auth: false });
}

// Public, unauthenticated totals for the landing page (MM-106) -- no
// counterparty-level data.
export interface PublicStatsResponse {
  counterparties: number;
  runs_evaluated: number;
  calls_raised: number;
}

export function getPublicStats(): Promise<PublicStatsResponse> {
  return getJson<PublicStatsResponse>("/public/stats", { auth: false });
}

export function getExposureBoard(): Promise<ExposureBoardResponse> {
  return getJson<ExposureBoardResponse>("/exposure");
}

export function getCounterparties(): Promise<CounterpartyListResponse> {
  return getJson<CounterpartyListResponse>("/counterparties");
}

export function getCounterpartyExposure(counterpartyId: string): Promise<CounterpartyExposure> {
  return getJson<CounterpartyExposure>(`/exposure/${encodeURIComponent(counterpartyId)}`);
}

export function getPriceHistory(ticker: string, days = 30): Promise<PriceHistoryResponse> {
  return getJson<PriceHistoryResponse>(
    `/prices/${encodeURIComponent(ticker)}/history?days=${days}`,
  );
}

export function getMarginCallFeed(): Promise<MarginCallFeedResponse> {
  return getJson<MarginCallFeedResponse>("/margin-calls");
}

export function getMarginCallBuckets(): Promise<MarginCallBucketFeedResponse> {
  return getJson<MarginCallBucketFeedResponse>("/margin-calls/buckets");
}

export function getMarginCallsForCounterparty(
  counterpartyId: string,
): Promise<MarginCallFeedResponse> {
  return getJson<MarginCallFeedResponse>(
    `/margin-calls/counterparty/${encodeURIComponent(counterpartyId)}`,
  );
}

export function getMarginCallTrace(threadId: string): Promise<MarginCallTraceResponse> {
  return getJson<MarginCallTraceResponse>(
    `/margin-calls/${encodeURIComponent(threadId)}/trace`,
  );
}

/** MM-146: a Firebase custom token for the real-time status listener. Its
 * claims carry the caller's counterparty scope; Firestore's security rules
 * enforce it, so the query below only has to match it. */
export interface RealtimeTokenResponse {
  token: string;
  collection: string;
  firm_wide: boolean;
  counterparty_ids: string[];
  expires_in: number;
}

export function getRealtimeToken(): Promise<RealtimeTokenResponse> {
  return getJson<RealtimeTokenResponse>("/realtime/token");
}

export type ApprovalDecision = "approved" | "rejected" | "adjusted";

export interface ApprovalResponse {
  thread_id: string;
  approval_decision: string | null;
  adjusted_call_amount: number | null;
}

export type ManagerApprovalDecision = "approved" | "rejected";

export interface ManagerApprovalResponse {
  thread_id: string;
  approval_decision: string | null;
  manager_decision: string | null;
}

export interface SlaResponse {
  thread_id: string;
  sla_outcome: string | null;
}

export function postApproval(
  token: string,
  threadId: string,
  decision: ApprovalDecision,
  adjustedCallAmount?: number,
): Promise<ApprovalResponse> {
  return postJson<ApprovalResponse>(
    `/margin-calls/${encodeURIComponent(threadId)}/approve`,
    token,
    { decision, adjusted_call_amount: adjustedCallAmount ?? null },
  );
}

export function postManagerApproval(
  token: string,
  threadId: string,
  decision: ManagerApprovalDecision,
): Promise<ManagerApprovalResponse> {
  return postJson<ManagerApprovalResponse>(
    `/margin-calls/${encodeURIComponent(threadId)}/manager-approve`,
    token,
    { decision },
  );
}

export function postRespond(token: string, threadId: string): Promise<SlaResponse> {
  return postJson<SlaResponse>(`/margin-calls/${encodeURIComponent(threadId)}/respond`, token);
}

export function postCheckSla(token: string, threadId: string): Promise<SlaResponse> {
  return postJson<SlaResponse>(`/margin-calls/${encodeURIComponent(threadId)}/check-sla`, token);
}

export type SimulateEventKind = "price_shock" | "vol_spike";

export interface SimulatedCounterpartyResult {
  counterparty_id: string;
  thread_id: string | null;
  breached: boolean | null;
  call_amount: number | null;
  error: string | null;
  action: "started" | "updated" | "unchanged" | null;
  detail: string | null;
}

export interface SimulateEventResponse {
  event_type: string;
  reason: string;
  affected_counterparties: SimulatedCounterpartyResult[];
}

export function postSimulateEvent(
  token: string,
  eventType: SimulateEventKind,
  ticker: string,
  pctChange: number,
): Promise<SimulateEventResponse> {
  return postJson<SimulateEventResponse>("/simulate", token, {
    event_type: eventType,
    ticker,
    pct_change: pctChange,
  });
}

export interface MarketUniverseResponse {
  tickers: string[];
}

export function getMarketUniverse(): Promise<MarketUniverseResponse> {
  return getJson<MarketUniverseResponse>("/market-universe");
}

// MM-129: "Ask the margin desk" -- one chat turn with the ADK agent on Agent
// Runtime, answered as the signed-in analyst (the API forwards the identity).
export interface DeskChatResponse {
  session_id: string;
  answer: string;
  tools_used: string[];
}

export function postDeskChat(
  token: string,
  message: string,
  sessionId: string | null,
): Promise<DeskChatResponse> {
  return postJson<DeskChatResponse>("/desk/chat", token, {
    message,
    session_id: sessionId,
  });
}

// MM-142: warehouse reports. The numbers are computed upstream (calc engine)
// and aggregated in BigQuery; this client only renders them.
export type ReportBook = "live" | "historical-sim";
export type ReportPeriod = "3m" | "1y" | "5y";

export interface ReportsStatusResponse {
  configured: boolean;
  books: ReportBook[];
  scoped: boolean;
}

export interface ReportMeta {
  book: ReportBook;
  period: ReportPeriod;
  start_date: string;
  end_date: string;
  generated_at: string;
  scoped: boolean;
}

export interface ExposurePoint {
  as_of_date: string;
  counterparties: number;
  exposure: number;
  threshold: number;
  headroom: number;
  breached: number;
  shortfalls: number;
}

export interface ExposureTrendReport {
  meta: ReportMeta;
  points: ExposurePoint[];
}

export interface CoverageBucket {
  bucket: string;
  counterparties: number;
  required_support: number;
  collateral_held: number;
}

export interface CounterpartyAdequacy {
  counterparty_id: string;
  tier: string;
  required_support: number;
  collateral_held: number;
  coverage_ratio: number | null;
  headroom: number;
}

export interface CollateralAdequacyReport {
  meta: ReportMeta;
  as_of_date: string | null;
  counterparties: number;
  required_support: number;
  collateral_held: number;
  buckets: CoverageBucket[];
  lowest_headroom: CounterpartyAdequacy[];
}

export interface ConcentrationRow {
  key: string;
  gross: number;
  net: number;
  counterparties: number;
}

export interface ConcentrationReport {
  meta: ReportMeta;
  as_of_date: string | null;
  by_sector: ConcentrationRow[];
  by_asset_class: ConcentrationRow[];
  top_tickers: ConcentrationRow[];
}

export interface MarginCallMonth {
  month: string;
  calls: number;
  amount: number;
  avg_approval_minutes: number | null;
  p90_approval_minutes: number | null;
  sla_met: number;
  sla_breached: number;
  escalations: number;
  open_calls: number;
}

export interface MarginCallPerformanceReport {
  meta: ReportMeta;
  months: MarginCallMonth[];
}

export interface StressDay {
  as_of_date: string;
  calls_raised: number;
  call_amount: number;
  breached: number;
  vix: number;
}

export interface StressMonth {
  month: string;
  calls_raised: number;
  call_amount: number;
  breach_days: number;
  avg_vix: number;
  max_vix: number;
}

export interface StressBacktestReport {
  meta: ReportMeta;
  top_days: StressDay[];
  months: StressMonth[];
}

export function getReportsStatus(): Promise<ReportsStatusResponse> {
  return getJson<ReportsStatusResponse>("/reports/status");
}

function reportPath(name: string, book: ReportBook, period: ReportPeriod): string {
  const query = new URLSearchParams({ book, period });
  return `/reports/${name}?${query.toString()}`;
}

export function getExposureTrend(book: ReportBook, period: ReportPeriod) {
  return getJson<ExposureTrendReport>(reportPath("exposure-trend", book, period));
}

export function getCollateralAdequacy(book: ReportBook, period: ReportPeriod) {
  return getJson<CollateralAdequacyReport>(reportPath("collateral-adequacy", book, period));
}

export function getConcentration(book: ReportBook, period: ReportPeriod) {
  return getJson<ConcentrationReport>(reportPath("concentration", book, period));
}

export function getMarginCallPerformance(book: ReportBook, period: ReportPeriod) {
  return getJson<MarginCallPerformanceReport>(
    reportPath("margin-call-performance", book, period),
  );
}

export function getStressBacktest(book: ReportBook, period: ReportPeriod) {
  return getJson<StressBacktestReport>(reportPath("stress-backtest", book, period));
}
