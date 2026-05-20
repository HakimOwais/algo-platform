# Algo Platform — Developer Wiki

This wiki documents the architecture, improvement roadmap, and operational details of the algo-trading platform.

## Contents

| Document | Description |
|---|---|
| [Architecture](architecture.md) | End-to-end data flow, service map, key design decisions |
| [Phase 1 — Foundation](phase-1-foundation.md) | **Completed** — EMA fix, session refresh, market hours gate |
| [Phase 2 — Signal Quality](phase-2-signal-quality.md) | GARCH sim, multi-timeframe, stable portfolio optimizer, ML features |
| [Phase 3 — Risk Architecture](phase-3-risk-architecture.md) | Student-t MC, smooth drawdown scalar, portfolio delta cap |
| [Phase 4 — Execution Realism](phase-4-execution-realism.md) | Square-root market impact, limit orders |
| [Phase 5 — Infrastructure](phase-5-infrastructure.md) | Backtester, performance attribution, walk-forward optimization |

## Quick-start

```bash
# Start all services
docker-compose up -d

# Tail API logs
docker logs algo-api -f

# Rebuild API image (after requirements.txt changes)
docker-compose build api && docker-compose down api && docker-compose up -d api
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ANGEL_ONE_API_KEY` | — | Enables live NSE feed when set with other Angel One creds |
| `ANGEL_ONE_CLIENT_CODE` | — | Angel One client ID |
| `ANGEL_ONE_PIN` | — | Angel One trading PIN |
| `ANGEL_ONE_TOTP_SECRET` | — | Base32 TOTP key from Angel One API Management |
| `ANGEL_ONE_SYMBOL_TOKENS` | — | `SYMBOL:TOKEN,...` mapping (e.g. `RELIANCE:2885,TCS:11536`) |
| `ANGEL_ONE_POLL_INTERVAL` | `3` | Seconds between LTP polls during market hours |
| `DEFAULT_BROKER` | `paper` | `paper` = simulated fills; `angel_one` = live (disabled by safety guard) |
| `SYMBOL_UNIVERSE` | `RELIANCE,TCS,...` | Comma-separated NSE symbols to trade |
| `MAX_DAILY_LOSS_INR` | `5000` | Triggers auto kill-switch |
| `MAX_MC_VAR_INR` | `2500` | Monte Carlo VaR limit per order |

## Dependency notes

`smartapi-python` 1.5.5 has two undeclared runtime dependencies. Both are pinned in `requirements.txt`:

```
logzero==1.7.0
websocket-client==1.9.0
```

Do not remove these — they will silently break the live feed.
