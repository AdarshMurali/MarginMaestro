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
  | "escalated";

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

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`);
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
  return getJson<HealthResponse>("/health");
}

export function getReady(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/ready");
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
