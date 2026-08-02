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
