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
  | "rejected"
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
    throw new Error(`POST ${path} failed: ${res.status} ${res.statusText}`);
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

export function getPriceHistory(ticker: string, days = 30): Promise<PriceHistoryResponse> {
  return getJson<PriceHistoryResponse>(
    `/prices/${encodeURIComponent(ticker)}/history?days=${days}`,
  );
}

export function getMarginCallFeed(): Promise<MarginCallFeedResponse> {
  return getJson<MarginCallFeedResponse>("/margin-calls");
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

export function postRespond(token: string, threadId: string): Promise<SlaResponse> {
  return postJson<SlaResponse>(`/margin-calls/${encodeURIComponent(threadId)}/respond`, token);
}

export function postCheckSla(token: string, threadId: string): Promise<SlaResponse> {
  return postJson<SlaResponse>(`/margin-calls/${encodeURIComponent(threadId)}/check-sla`, token);
}

export type SimulateScenario = "price_shock" | "vol_spike";

export interface SimulatedCounterpartyResult {
  counterparty_id: string;
  thread_id: string | null;
  breached: boolean | null;
  call_amount: number | null;
  error: string | null;
}

export interface SimulateEventResponse {
  scenario: string;
  reason: string;
  affected_counterparties: SimulatedCounterpartyResult[];
}

export function postSimulateEvent(
  token: string,
  scenario: SimulateScenario,
): Promise<SimulateEventResponse> {
  return postJson<SimulateEventResponse>("/simulate", token, { scenario });
}
