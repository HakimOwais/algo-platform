# Architecture

## Service map

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI (uvicorn)                     │
│                                                         │
│  lifespan startup                                       │
│    ├── AngelOneMarketDataService  ← live NSE LTP        │
│    │   └── or MarketDataService  ← Gaussian sim         │
│    ├── PortfolioService           ← position tracking   │
│    ├── RiskEngine                 ← pre-trade guards    │
│    ├── PaperBroker / AngelOneBroker                     │
│    ├── OrderManager               ← order lifecycle     │
│    ├── StrategyEngine             ← signal generation   │
│    └── TradingOrchestrator        ← task supervision    │
│                                                         │
│  REST API  →  /api/...                                  │
│  WebSocket →  /ws/stream  (EventHub broadcast)          │
└─────────────────────────────────────────────────────────┘
         ↕                        ↕
    PostgreSQL 16            Redis 7 (future)
```

## Data flow

```
Angel One ltpData (REST, every 3 s during market hours)
  ↓
AngelOneMarketDataService.generate_once()
  → Bar persisted to DB
  → _recent_closes deque updated (maxlen=256)
  → EventHub.broadcast("market.bars")
  ↓
TradingOrchestrator._strategy_loop() (every 2 s, market hours only)
  ↓
StrategyEngine.run_once()
  1. EMA crossover (true EMA over full history)
  2. HMM regime filter
  3. HAR-RV volatility sizing (GARCH+EGARCH fallback)
  4. Fractional Kelly sizing (25%)
  5. Portfolio allocation blend (MV + RP + momentum) / 3
  6. Monte Carlo tail-risk guard (VaR/CVaR, 1500 paths)
  7. Kalman pairs context
  8. LightGBM ML confirmation / veto
  → DecisionLog persisted
  ↓
OrderManager.place_order()
  ↓
RiskEngine.evaluate_order()   ← kills order if any limit breached
  ↓
PaperBroker.place_order()     ← fills with realistic NSE costs
  ↓
PortfolioService              ← updates positions / P&L
  ↓
EventHub.broadcast("order.*") ← WebSocket push to frontend
```

## Market hours gating (Phase 1)

```
is_market_open() → True  only if Mon–Fri, 09:15–15:30 IST

AngelOneMarketDataService.generate_once()
  └── returns immediately if not market_open

TradingOrchestrator._strategy_loop()
  └── skips run_once() if live_feed AND not market_open

MarketDataService (sim)
  └── is_live_feed = False → always runs (no gate)
```

## Key hardcoded constants

| Location | Constant | Value | Meaning |
|---|---|---|---|
| `risk_engine.py` | `_BASE_CAPITAL` | ₹10,00,000 | Starting NAV for drawdown calculation |
| `strategy_engine.py` | `kelly_fraction` | 0.25 | 25% fractional Kelly cap |
| `strategy_engine.py` | `random_seed` (MC) | 13 | Reproducible Monte Carlo |
| `risk_engine.py` | `random_seed` (MC) | 17 | Separate seed from strategy |
| `paper_broker.py` | slippage | 2–15 bps | Market impact simulation |
| `paper_broker.py` | brokerage cap | ₹20 | Matches Zerodha/Upstox flat fee |
| `market_hours.py` | `_MARKET_OPEN` | 09:15 | NSE equity segment open |
| `market_hours.py` | `_MARKET_CLOSE` | 15:30 | NSE equity segment close |
| `angel_one_*` | refresh interval | 20 h | JWT refresh before 24-h expiry |

## Database schema

```
instruments   (id, symbol, exchange, tick_size, lot_size)
bars          (id, instrument_id, timestamp, interval, open, high, low, close, volume)
orders        (id, strategy_name, symbol, side, type, quantity, status, ...)
fills         (id, order_id, quantity, price, fee, filled_at)
positions     (id, symbol, quantity, avg_price, realized_pnl)
decision_logs (id, strategy_name, symbol, signal, confidence, payload JSON, created_at)
risk_events   (id, event_type, severity, detail JSON, created_at)
strategy_configs (id, name, parameters JSON, is_active, mode)
```

## Broker safety guard

`AngelOneBroker.place_order()` unconditionally returns `REJECTED` — this is intentional.
Enabling live execution requires:
1. Implementing session refresh + 2FA in the broker adapter
2. Storing and rotating the JWT token
3. Handling Angel One's order rejection codes (circuit breaker, margin, etc.)
4. Setting `DEFAULT_BROKER=angel_one` in `.env`

Do not bypass the safety guard without completing all four steps.
