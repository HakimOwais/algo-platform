# Quant Models Instruction Guide

## 1. Purpose

This guide explains how to:

1. Enable and tune quantitative models in this project
2. Verify that models are actually influencing orders
3. Troubleshoot cases where the dashboard appears "not engaging"

This is written for local development on Windows/PowerShell and Docker Compose.

## 2. What Is Implemented

The platform currently includes these model families:

1. Volatility Models:
   - `ARCH(1)`
   - `GARCH(1,1)`
2. Tail-Risk Models:
   - Monte Carlo `VaR/CVaR`
3. Option Analytics:
   - Black-Scholes pricing
   - Greeks
   - Implied volatility
4. Position/Allocation Models:
   - Mean-variance allocation
   - Risk parity allocation
   - Kelly fraction sizing
5. Relative-Value Context:
   - Pairs spread z-score signal

Primary model integration points:

1. Strategy sizing and decision payloads:
   - `apps/api/app/services/strategy_engine.py`
2. Pre-trade Monte Carlo risk gate:
   - `apps/api/app/services/risk_engine.py`
3. Quant APIs:
   - `apps/api/app/api/routes/quant.py`

## 3. Why the Dashboard Looks Basic

Your current dashboard intentionally shows a compact summary:

1. It shows signal rows, but not full quant payload internals.
2. It shows order/fill/risk summaries, not raw model state at each tick.
3. Quant details are available via backend APIs and `decision_logs.payload`.

So if UI looks simple, it does not mean models are unused.

## 4. Start the Platform

From repo root:

```powershell
docker compose up --build
```

Open:

1. Web dashboard: `http://localhost:3000`
2. API docs: `http://localhost:8000/docs`

## 5. Confirm Quant Configuration Is Loaded

In your `.env`, ensure these keys are set:

```env
ENABLE_MONTE_CARLO_RISK=true
MC_CONFIDENCE=0.95
MC_HORIZON_STEPS=20
MC_PATHS=2000
MAX_MC_VAR_INR=2500
MAX_MC_CVAR_INR=4000
MIN_RISK_HISTORY_BARS=60
```

Check runtime risk config:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/risk/status" -Method Get | ConvertTo-Json -Depth 6
```

You should see:

1. `enable_monte_carlo_risk: true`
2. `mc_confidence`, `mc_horizon_steps`, `mc_paths`
3. `max_mc_var_inr`, `max_mc_cvar_inr`

## 6. Verify Models Are Affecting Orders

## 6.1 Check Strategy Decision Payload (most important)

Run:

```powershell
$decisions = Invoke-RestMethod -Uri "http://localhost:8000/decisions?limit=5" -Method Get
$decisions | ConvertTo-Json -Depth 12
```

Inspect `payload` inside each decision. You should see sections like:

1. `volatility.arch`
2. `volatility.garch`
3. `monte_carlo.var_amount`, `cvar_amount`
4. `allocation.mean_variance_weight`, `risk_parity_weight`
5. `kelly.fraction`
6. `dynamic_quantity` (this is the direct order-size effect)

If those fields are present, the quant stack is active in strategy execution.

## 6.2 Check Dynamic Quantity in Executed Orders

Strategy seed has `trade_quantity` (base lot). Model-adjusted quantity may differ.

Run:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/orders?limit=20" -Method Get | ConvertTo-Json -Depth 8
```

Compare:

1. `strategy parameter trade_quantity` (base)
2. actual `order.quantity` in orders

If quantities vary around the base value, model-based sizing is active.

## 6.3 Check Monte Carlo Risk Rejections

If tail risk breaches threshold, orders are rejected with reason:

1. `Monte Carlo VaR threshold breached`
2. `Monte Carlo CVaR threshold breached`

Run:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/orders?limit=50" -Method Get | ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri "http://localhost:8000/risk/status" -Method Get | ConvertTo-Json -Depth 8
```

Also inspect `risk_status.recent_events` for:

1. `MC_VAR_BREACH`
2. `MC_CVAR_BREACH`

## 7. Call Quant APIs Directly (Proof of Mathematical Engines)

## 7.1 Black-Scholes + Greeks

```powershell
$body = @{
  spot = 2450
  strike = 2500
  time_to_expiry = 0.12
  rate = 0.06
  volatility = 0.22
  dividend_yield = 0.00
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/quant/options/black-scholes" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 6
```

Expected fields:

1. `call_price`, `put_price`
2. `delta_call`, `gamma`, `vega`, `theta_call`, `rho_call`

## 7.2 Implied Volatility

```powershell
$body = @{
  option_type = "call"
  market_price = 120
  spot = 2450
  strike = 2500
  time_to_expiry = 0.12
  rate = 0.06
  dividend_yield = 0.00
  initial_volatility = 0.25
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/quant/options/implied-vol" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 6
```

Expected field:

1. `implied_volatility`

## 7.3 Portfolio Weights (Mean-Variance + Risk Parity)

```powershell
$body = @{
  returns_by_symbol = @{
    RELIANCE = @(0.002,-0.001,0.0015,-0.0005,0.0021,0.0012,-0.0008,0.0011,0.0009,-0.001)
    TCS      = @(0.001,0.0004,-0.0007,0.0013,0.0008,-0.0002,0.0009,0.0011,-0.0004,0.0006)
    INFY     = @(0.0015,-0.0003,0.0012,0.0005,-0.0006,0.0010,0.0013,-0.0007,0.0008,0.0009)
  }
  risk_aversion = 3.0
  long_only = $true
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Uri "http://localhost:8000/quant/portfolio/weights" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 8
```

Expected fields:

1. `mean_variance_weights`
2. `risk_parity_weights`

## 8. Tuning Guide (Practical Defaults)

## 8.1 If Too Many Rejections

Relax risk thresholds:

1. Increase `MAX_MC_VAR_INR`
2. Increase `MAX_MC_CVAR_INR`
3. Decrease `MC_HORIZON_STEPS`

Then restart API.

## 8.2 If Position Size Is Too Small

In strategy parameters (`/strategies/ema_cross/deploy`):

1. Increase `target_vol_annual`
2. Increase `max_position_scale`
3. Increase `risk_budget_per_order_inr`
4. Increase `max_trade_quantity`

## 8.3 If Position Size Is Too Aggressive

1. Decrease `target_vol_annual`
2. Decrease `max_position_scale`
3. Decrease `risk_budget_per_order_inr`
4. Decrease `max_trade_quantity`

## 9. Example: Update Strategy Quant Parameters

```powershell
$body = @{
  parameters = @{
    fast_window = 8
    slow_window = 21
    trade_quantity = 5
    lookback_bars = 120
    target_vol_annual = 0.20
    min_position_scale = 0.30
    max_position_scale = 2.00
    max_trade_quantity = 100
    risk_budget_per_order_inr = 1400.0
    use_garch_sizing = $true
    use_monte_carlo_guard = $true
    enable_pairs_context = $true
    mc_confidence = 0.95
    mc_horizon_steps = 12
    mc_paths = 1500
  }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/strategies/ema_cross/deploy" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 6
```

## 10. Troubleshooting Matrix

## 10.1 No Quant Fields in Decisions

Possible causes:

1. Strategy has not generated a fresh state change yet
2. Strategy is paused
3. You are reading old decisions from before quant integration

Actions:

1. `POST /strategies/ema_cross/resume`
2. Wait for fresh events and fetch latest decisions again

## 10.2 Orders Are Always Rejected

Possible causes:

1. Kill switch active
2. Daily loss threshold already breached
3. Monte Carlo thresholds too tight

Actions:

1. Check `/risk/status`
2. Release kill switch if appropriate
3. Adjust risk thresholds
4. Restart with clean paper state for a fresh run

## 10.3 Dashboard Still Looks "Not Engaging"

Current UI behavior:

1. It does not render full quant payload details by default.

Use these for full visibility:

1. `/decisions` for model internals
2. `/orders` for sizing/rejection outcomes
3. `/risk/status` for risk-state and breach events

Optional UI enhancement (recommended next):

1. Add a "Quant Diagnostics" panel that shows latest:
   - GARCH variance
   - annualized vol
   - Monte Carlo VaR/CVaR
   - dynamic quantity vs base quantity

## 11. Validation Checklist

Use this checklist after each deployment:

1. `GET /health` returns `ok`
2. `GET /risk/status` shows Monte Carlo config fields
3. `GET /decisions` shows quant payload sections
4. `GET /orders` shows dynamic quantities and sensible statuses
5. Quant endpoints return valid outputs

If all five pass, your platform is actively using the mathematical models in execution flow.
