# Guidebook: Building a Full‑Fledged Algorithmic Trading Platform (India‑Ready, Frontend + Backend)

> Educational engineering guide, not investment advice. Trading involves substantial risk, and even “paper trading” can hide real‑world issues like slippage, partial fills, halts, and outages.

---

## 0) What you’re building (in one sentence)

A production platform that reliably turns **market data → signals → risk checks → orders → fills → P&L**, with **observability, auditability, and a UI** to control/monitor everything.

---

## 1) Platform goals and non‑goals

### Goals (must‑have)
- **Reproducible research → deployable strategy** pipeline (versioned configs + code).
- **Paper trading and live trading** share the same execution path (only the broker adapter changes).
- **Strong risk controls** (pre‑trade + post‑trade, kill switches, throttles).
- **Audit trail** (orders, modifications, cancellations, fills, positions, decisions).
- **Operational resilience** (retries, idempotency, state recovery, alerting).
- **Frontend dashboard** for operations, strategy management, and reporting.

### Non‑goals (initially)
- HFT / colocated ultra‑low latency (that’s a different architecture).
- Fully automated “set and forget” retail money machine (unrealistic, unsafe).

---

## 2) Reference architecture (services and data flow)

### Event flow
```mermaid
flowchart LR
  M[(Market Data)] --> D[Data Ingestion]
  D --> S[Signal Engine]
  S --> R[Risk Engine]
  R --> O[Order Manager (OMS)]
  O --> B[Broker Adapter (Angel One SmartAPI)]
  B --> F[(Fills/Trades)]
  F --> P[Portfolio & PnL]
  P --> UI[Frontend Dashboard]
  O --> UI
  R --> UI
  D --> TS[(Time‑Series Store)]
  O --> OL[(Order Ledger)]
  F --> OL
  P --> OL
```

### Core services (recommended decomposition)
1. **API Gateway / Backend API** (FastAPI/Node) — auth, admin, dashboards, control plane.
2. **Market Data Service** — subscribes to streams, normalizes ticks/bars, stores.
3. **Strategy Runtime** — runs strategies on a schedule or streaming basis.
4. **Risk Engine** — centralized “can we trade?” logic.
5. **OMS (Order Management System)** — creates orders, tracks states, reconciles fills.
6. **Broker Adapter** (Angel One SmartAPI) — the only place that talks to broker.
7. **Portfolio Service** — positions, exposure, P&L, fees, corporate actions (later).
8. **Monitoring/Alerting** — metrics, logs, traces, incident alerts.

---

## 3) Tech stack (pragmatic, full‑stack)

### Backend (Python‑first, common for quant)
- **Python 3.11+** (strategy + services)
- **FastAPI** (REST + WebSockets)
- **PostgreSQL** (orders, configs, users) + **TimescaleDB** (optional) for OHLCV/ticks
- **Redis** (caching, rate limits, short‑lived state, pub/sub)
- **Message bus**: start with Redis Streams or RabbitMQ; move to Kafka if needed
- **Celery/RQ/APScheduler** (jobs: EOD reports, data refresh, strategy schedules)
- **Observability**: Prometheus + Grafana, OpenTelemetry, Sentry

### Frontend (ops dashboard)
- **Next.js (React)** + TypeScript
- **WebSockets** for live updates (orders/fills/health)
- **Charts**: TradingView lightweight charts, ECharts, or Plotly
- **Auth**: session cookies or JWT (prefer cookie‑based for a web dashboard)

### Deployment (start simple, grow safely)
- Docker Compose → single VPS → Kubernetes (only when you truly need it)

---

## 4) Data layer (historical + live)

### Data types you need
- **Reference data**: instrument master (tokens), tick size, lot size, exchange, ISIN.
- **Market data**:
  - OHLCV bars (1m/5m/15m/day) for most strategies
  - optional ticks/L2 later
- **Corporate actions** (later): splits, dividends, symbol changes (important for equities).

### Minimal schema (conceptual)
- `instruments` (token, symbol, exchange, tick_size, lot_size, ...)
- `bars` (instrument_id, ts, o, h, l, c, v, interval)
- `ticks` (optional) (instrument_id, ts, ltp, bid, ask, ...)

### India specifics to bake in
- Market hours: **09:15–15:30 IST**, pre‑open **09:00–09:15**.
- Circuit filters/halts: strategies must tolerate missing ticks and “stuck” quotes.
- Liquidity: start with **NIFTY50 / highly liquid names** to reduce slippage.

---

## 5) Strategy layer (research → production)

### Strategy contract (recommended)
Each strategy should implement:
- `on_start(context)` — warmup, fetch params, load state
- `on_bar(bar)` or `on_tick(tick)` — compute signals
- `generate_orders(signal, portfolio_state)` — propose intent
- `on_fill(fill)` — update internal state
- `on_stop()` — shutdown cleanup

### Strategy lifecycle rules
- Strategy code is **immutable per version** (tagged release or git SHA).
- Strategy parameters live in DB as **versioned configs**.
- Every decision should be explainable with a **decision log**:
  - inputs (prices/indicators), output (signal), risk result, order created (or blocked).

### Common India‑fit strategy families (engineering‑friendly)
- **Trend / momentum** on liquid large caps and indices (15m / 1h / daily).
- **Mean reversion** on large caps during low‑vol regimes.
- **Opening range breakout** (intraday) with strict stops and time exits.

---

## 6) Risk engine (the “adult supervision”)

### Pre‑trade checks (block orders if violated)
- Max position per symbol (₹ exposure and % of NAV).
- Max sector exposure (optional early).
- Max daily loss (hard stop).
- Max drawdown from peak (kill switch).
- Order size sanity: price bands, max quantity, fat‑finger protection.
- Cooldowns after consecutive losses.
- Circuit/volatility guard: skip during abnormal spreads/halts.

### Post‑trade controls
- Reconcile fills vs OMS state.
- Detect “stuck” orders; cancel/replace rules.
- Continuous P&L and exposure monitoring.

---

## 7) OMS/Execution (the hardest part to get right)

### Order state machine (minimum)
`NEW → SENT → ACKED → PARTIALLY_FILLED → FILLED`
and terminal branches:
`CANCELLED`, `REJECTED`, `EXPIRED`, `ERROR`

### Engineering requirements
- **Idempotency keys** for order submits to avoid duplicates on retries.
- **Persistence first**: write intent to DB before sending to broker.
- **Reconciliation loop**: broker is source of truth; your state must converge to it.
- **Rate limiting**: broker/API throttles + self‑imposed order frequency limits.
- **Kill switch**: global cancel + stop strategy runtime.

### Paper trading
Paper trading must reuse the OMS and risk engine:
- Replace broker adapter with a **simulator adapter** that:
  - generates fills with configurable slippage/spread/latency
  - simulates partial fills and rejections
  - writes fills back through the same “fill ingestion” path

---

## 8) Backend API (control plane) — suggested endpoints

### Auth & users
- `POST /auth/login`
- `POST /auth/logout`
- `GET /me`

### Strategy management
- `GET /strategies` (list available strategy versions)
- `POST /strategies/{id}/deploy` (deploy config to runtime)
- `POST /strategies/{id}/pause`
- `POST /strategies/{id}/resume`

### Trading operations
- `GET /orders?status=...`
- `GET /fills`
- `GET /positions`
- `POST /ops/kill-switch` (halts runtime + cancels open orders)

### Monitoring
- `GET /health`
- `GET /metrics` (Prometheus scrape, restricted)
- WebSocket: `/ws/stream` (orders, fills, P&L, alerts)

---

## 9) Frontend (what a “proper” platform UI includes)

### Key screens
1. **Live Overview**
   - NAV, daily P&L, drawdown, exposure, open orders, fill latency, system health
2. **Strategies**
   - version, parameters, state (running/paused), last signal time, last trade, logs
3. **Orders & Fills**
   - searchable ledger; drill down into an order’s full lifecycle
4. **Risk Dashboard**
   - limits, breaches, recent blocks (and why), kill switch status
5. **Reports**
   - daily summary, monthly stats, strategy attribution, costs
6. **Admin**
   - API keys/secrets management (prefer vault), role‑based access

### UX principles (non‑negotiable)
- Every trade is explainable (“why did we trade?”).
- Every block is explainable (“why did we not trade?”).
- Fast “stop trading now” controls.

---

## 10) Logging, audit, and compliance (India context)

Even if you’re building for yourself, build as if you’ll be audited:
- Store **immutable** order/fill events (append‑only ledger).
- Store strategy decision logs with timestamps and inputs.
- Keep broker responses (ids, error codes) for traceability.
- Separate “control plane” permissions (deploy/pause/kill) from view‑only access.

> SEBI/broker policies can require approvals and broker‑side risk systems for algo usage; design to operate through broker APIs and maintain a full audit trail.

---

## 11) Security and secrets (do this early)
- Never store API secrets in Git.
- Use environment variables + a secrets manager (Vault/SSM) when possible.
- Encrypt sensitive data at rest (DB encryption features or disk encryption).
- Enforce RBAC in the dashboard.
- Add IP allowlists for admin endpoints if feasible.

---

## 12) Testing & validation (what “production‑ready” means)

### Unit tests
- indicator calculations, signal rules, position sizing, risk checks, cost models

### Simulation tests
- partial fills, disconnections, retry storms, stale quotes, order rejections

### Paper trading acceptance criteria (before live)
- 30–60 trading days with stable runtime (no manual restarts).
- Reconciliation shows no “ghost positions.”
- Live slippage vs modeled slippage is understood and bounded.
- Drawdown and daily loss limits behave exactly as designed.

---

## 13) A practical build roadmap (incremental, shippable)

### Phase 1 — Single‑machine MVP (2–4 weeks)
- Data ingestion (bars), basic strategy runtime, risk checks, paper broker adapter, minimal UI.

### Phase 2 — Real broker integration (4–8 weeks)
- Angel One SmartAPI adapter, OMS state machine, reconciliation, alerts, robust logging.

### Phase 3 — Multi‑strategy & ops hardening (8–12 weeks)
- Strategy registry/versioning, per‑strategy limits, better reporting, incident playbooks.

### Phase 4 — Scale & resilience (later)
- Separate services, message bus, HA DB, dedicated monitoring stack, disaster recovery.

---

## 14) Suggested repository structure (full‑stack)

```
algo-platform/
  apps/
    api/                # FastAPI backend (control plane)
    worker/             # strategy runtime + schedulers
    web/                # Next.js dashboard
  packages/
    core/               # indicators, signals, risk primitives, types
    broker-angelone/    # SmartAPI adapter
    broker-sim/         # paper broker adapter
  infra/
    docker/             # compose files, local observability
  docs/
    runbooks/           # “what to do when X breaks”
```

---

## 15) “Golden rules” that prevent most blow‑ups
- Never bypass the risk engine, even “temporarily.”
- Always reconcile positions from broker as source of truth.
- Prefer fewer strategies, higher quality validation.
- Treat operations as engineering: monitoring, alerts, and runbooks matter as much as alpha.

---

## Appendix A: India‑ready paper trading model (what to simulate)
- Slippage = function of volatility + spread + liquidity bucket.
- Brokerage/fees model (approximate) and realistic order types.
- Latency (randomized delays) and disconnections.
- Partial fills, order rejects, and exchange halts.

---

## Appendix B: Common failure modes (and how you design against them)
- **Duplicate orders** on retry → idempotency keys + persisted order intent.
- **Stale data** → timestamps + freshness checks + “no trade if stale.”
- **Strategy drift** → live vs backtest monitoring + regime detection + controlled pauses.
- **Silent failures** → heartbeat monitoring + alert if no ticks/bars or no decisions.

---

## Next step (if you want me to implement)

If you want, I can scaffold the actual full‑stack repo (FastAPI + Next.js + Postgres + Redis + paper broker adapter) in this workspace and include a working dashboard + WebSocket stream.

