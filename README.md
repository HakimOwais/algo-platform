# Algo Trading Platform (End-to-End Template)

This repository implements a full-stack algorithmic trading platform template based on the guidebook:

- Backend control plane (`FastAPI`, async `SQLAlchemy`)
- Strategy runtime + market data simulation
- Central risk engine + kill switch
- OMS + broker adapter abstraction (`paper` default)
- Portfolio, fills, decision logs, audit-friendly ledgers
- Frontend operations dashboard (`Next.js`) with WebSocket + REST
- Docker Compose infra (`Postgres`, `Redis`, `API`, `Web`)

## Architecture and Design Documentation

For full high-level and low-level project documentation (system design, component internals, working flows, and improvement roadmap), see:

- [Project Documentation](./docs/PROJECT_DOCUMENTATION.md)
- [Quant Models Instruction Guide](./docs/QUANT_MODELS_INSTRUCTION_GUIDE.md)

## What is implemented

### Backend (`apps/api`)
- Live services:
  - `MarketDataService`: generates synthetic NSE-like bars for configured symbols.
  - `StrategyEngine`: EMA crossover strategy runner with decision logs.
  - `RiskEngine`: quantity/notional/open-order/daily-loss checks + kill switch.
  - `OrderManager`: idempotent order path, broker execution, fill persistence.
  - `PortfolioService`: position and realized PnL updates.
  - `TradingOrchestrator`: starts/stops market + strategy loops.
  - Quant model modules (modular):
    - `ARCH(1)` + `GARCH(1,1)` volatility forecast
    - Monte Carlo `VaR/CVaR` tail-risk analytics
    - Black-Scholes pricing + Greeks + implied volatility
    - Mean-variance and risk-parity allocation helpers
    - Pairs spread/z-score utility
- REST endpoints:
  - `GET /health`
  - `POST /auth/login`
  - `GET /strategies`
  - `POST /strategies/{name}/deploy|pause|resume`
  - `POST /orders`
  - `GET /orders`
  - `GET /fills`
  - `GET /positions`
  - `GET /decisions`
  - `GET /risk/status`
  - `POST /ops/kill-switch`
  - `GET /dashboard/summary`
  - `POST /quant/options/black-scholes`
  - `POST /quant/options/implied-vol`
  - `POST /quant/portfolio/weights`
- Streaming:
  - `WS /ws/stream` for bars, signals, order updates, risk events.

### Frontend (`apps/web`)
- Operations dashboard with:
  - NAV/PnL/open positions/open orders cards
  - Orders and positions tables
  - Recent fills, decision log, stream events
  - Strategy pause/resume controls
  - Risk kill-switch controls
  - Manual order panel
- Polling + WebSocket to keep UI in sync.

## Quick start (Docker)

1. From repo root:
   ```bash
   cp .env.example .env
   ```
2. Start all services:
   ```bash
   docker compose up --build
   ```
3. Open:
   - Frontend: `http://localhost:3000`
   - Backend docs: `http://localhost:8000/docs`

## Local start (without Docker)

### Backend
```bash
cd apps/api
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd apps/web
npm install
npm run dev
```

## Smoke checks

```bash
cd apps/api
python -m compileall app
python -m pytest tests/test_paper_broker.py tests/test_settings.py -q -p no:cacheprovider
```

## Configuration

Use `.env` values from `.env.example`. Important keys:

- `DEFAULT_BROKER=paper` (safe default)
- `SYMBOL_UNIVERSE=RELIANCE,TCS,INFY,...`
- `MAX_DAILY_LOSS_INR`, `MAX_POSITION_NOTIONAL_INR`
- `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_WS_URL`

## Angel One adapter note

The `AngelOneBroker` adapter file is wired in architecture but intentionally rejects orders by default until a production-safe auth/session refresh flow is implemented. Paper execution is fully operational and shares the same OMS/risk path.

## Safety

- This is an engineering platform template, not financial advice.
- Keep live credentials out of source control.
- Use paper mode and validate behavior before any real trading.
