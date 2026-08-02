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
