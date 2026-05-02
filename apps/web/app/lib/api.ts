import type {
  BacktestRequest,
  BacktestResponse,
  DashboardSummary,
  DecisionRow,
  FillRow,
  MLModelStatus,
  MLPredictResponse,
  MLTrainRequest,
  MLTrainResponse,
  OrderRow,
  PositionRow,
  RiskStatus,
  StrategyRow
} from "@/app/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/stream";

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }
  return (await response.json()) as T;
}

export const api = {
  // ── Core dashboard ──────────────────────────────────────────────────────────
  summary: () => apiRequest<DashboardSummary>("/dashboard/summary"),
  orders: () => apiRequest<OrderRow[]>("/orders?limit=50"),
  fills: () => apiRequest<FillRow[]>("/fills?limit=50"),
  positions: () => apiRequest<PositionRow[]>("/positions"),
  strategies: () => apiRequest<StrategyRow[]>("/strategies"),
  decisions: () => apiRequest<DecisionRow[]>("/decisions?limit=20"),
  riskStatus: () => apiRequest<RiskStatus>("/risk/status"),

  placeOrder: (payload: { strategy_name: string; symbol: string; side: "BUY" | "SELL"; quantity: number }) =>
    apiRequest<OrderRow>("/orders", { method: "POST", body: JSON.stringify(payload) }),

  toggleKillSwitch: (engaged: boolean) =>
    apiRequest<{ status: string; engaged: boolean }>("/ops/kill-switch", {
      method: "POST",
      body: JSON.stringify({ engaged, message: "Operator action from dashboard" })
    }),

  pauseStrategy: (name: string) =>
    apiRequest<StrategyRow>(`/strategies/${name}/pause`, { method: "POST" }),

  resumeStrategy: (name: string) =>
    apiRequest<StrategyRow>(`/strategies/${name}/resume`, { method: "POST" }),

  deployStrategy: (name: string, payload: { parameters: Record<string, unknown> }) =>
    apiRequest<StrategyRow>(`/strategies/${name}/deploy`, {
      method: "POST",
      body: JSON.stringify(payload)
    }),

  // ── Backtest ────────────────────────────────────────────────────────────────
  runBacktest: (req: BacktestRequest) =>
    apiRequest<BacktestResponse>("/backtest/run", {
      method: "POST",
      body: JSON.stringify(req)
    }),

  // ── ML ──────────────────────────────────────────────────────────────────────
  mlStatus: () => apiRequest<MLModelStatus>("/ml/status"),

  mlTrain: (req: MLTrainRequest = {}) =>
    apiRequest<MLTrainResponse>("/ml/train", {
      method: "POST",
      body: JSON.stringify(req)
    }),

  mlPredict: (symbol: string) =>
    apiRequest<MLPredictResponse>(`/ml/predict/${symbol}`, { method: "POST" }),

  mlDeleteModel: () => apiRequest<{ status: string; message: string }>("/ml/model", { method: "DELETE" }),

  wsUrl: () => WS_URL
};
