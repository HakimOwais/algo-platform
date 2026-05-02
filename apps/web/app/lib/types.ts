export type OrderSide = "BUY" | "SELL";
export type OrderStatus =
  | "NEW"
  | "SENT"
  | "ACKED"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "CANCELLED"
  | "REJECTED"
  | "EXPIRED"
  | "ERROR";

export interface DashboardSummary {
  nav_estimate: number;
  realized_pnl: number;
  open_positions: number;
  open_orders: number;
  latest_prices: Record<string, number>;
  kill_switch: boolean;
}

export interface OrderRow {
  id: string;
  strategy_name: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  order_type: "MARKET" | "LIMIT";
  status: OrderStatus;
  broker_order_id: string | null;
  rejection_reason: string | null;
  requested_at: string;
}

export interface FillRow {
  id: string;
  order_id: string;
  symbol: string;
  quantity: number;
  price: number;
  fee: number;
  filled_at: string;
}

export interface PositionRow {
  id: number;
  symbol: string;
  quantity: number;
  avg_price: number;
  realized_pnl: number;
  updated_at: string;
}

export interface StrategyRow {
  id: number;
  name: string;
  version: string;
  is_active: boolean;
  mode: string;
  parameters: Record<string, unknown>;
  updated_at: string;
}

export interface DecisionRow {
  id: number;
  strategy_name: string;
  symbol: string;
  signal: string;
  confidence: number;
  reason: string;
  created_at: string;
  payload?: {
    regime?: { label?: string; trending_prob?: number; scalar?: number };
    ml?: { direction?: number; bull_prob?: number; confidence?: number };
    ml_veto?: boolean;
    volatility?: { annualized?: number; model?: string };
    scales?: { combined?: number };
  };
}

export interface DrawdownState {
  current: number;       // fraction, e.g. 0.12 = 12%
  position_scalar: number;
  label: "NORMAL" | "CAUTION" | "STOP";
}

export interface RiskStatus {
  kill_switch: boolean;
  peak_nav: number;
  current_nav_estimate: number;
  drawdown: DrawdownState;
  max_daily_loss_inr: number;
  max_position_notional_inr: number;
  max_open_orders: number;
  open_orders: number;
  realized_pnl: number;
  recent_events: Array<{
    event_type: string;
    severity: string;
    message: string;
    created_at: string;
  }>;
}

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
  timestamp?: string;
}

// ── ML types ─────────────────────────────────────────────────────────────────

export interface MLTrainRequest {
  symbols?: string[];
  forward_bars?: number;
  lookback?: number;
  threshold?: number;
  n_estimators?: number;
}

export interface MLTrainResponse {
  status: string;
  n_samples: number;
  n_features: number;
  mean_cv_auc: number;
  threshold: number;
  top_features: Record<string, number>;
  message: string;
}

export interface MLModelStatus {
  is_trained: boolean;
  n_features: number;
  threshold: number;
  model_path: string;
}

export interface MLPredictResponse {
  symbol: string;
  direction: -1 | 0 | 1;
  bull_prob: number;
  confidence: number;
  features_used: number;
  model_trained: boolean;
}

// ── Backtest types ────────────────────────────────────────────────────────────

export interface BacktestRequest {
  symbol: string;
  fast_window?: number;
  slow_window?: number;
  initial_capital?: number;
  trade_qty?: number;
  lookback?: number;
  slippage_bps?: number;
}

export interface BacktestResponse {
  symbol: string;
  total_return_pct: number;
  annualised_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  total_trades: number;
  avg_bars_held: number;
  avg_net_pnl: number;
  total_costs: number;
  final_nav: number;
  initial_capital: number;
  n_bars: number;
  trades: Array<{
    entry_bar: number;
    exit_bar: number;
    entry_price: number;
    exit_price: number;
    qty: number;
    gross_pnl: number;
    costs: number;
    net_pnl: number;
    bars_held: number;
  }>;
}
