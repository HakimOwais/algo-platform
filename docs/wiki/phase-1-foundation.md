# Phase 1 — Foundation

**Status: Completed**

## Changes

### 1.1 Fix EMA bug — `strategy_engine.py`

**Problem:** The "EMA crossover" was computing `fmean(closes[-N:])` — a simple moving average over the last N bars. Every bar gets equal weight. A true EMA weights recent bars exponentially: `EMA[t] = α × price[t] + (1−α) × EMA[t−1]` where `α = 2/(N+1)`. Using an SMA on a slice of the last N bars:
- Reacts slower to trend changes (higher α inertia)
- Produces more whipsaws (false crossovers)
- Cannot distinguish momentum strength — all bars in the window count equally

**Fix:** Added `StrategyEngine._ema(prices, window)` which iterates over the **full** price history, not a slice. Computing over the full history ensures the exponential decay is correct — slicing the last N bars and averaging them is mathematically equivalent to a simple average regardless of what you call it.

```python
@staticmethod
def _ema(prices: list[float], window: int) -> float:
    alpha = 2.0 / (window + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = alpha * price + (1.0 - alpha) * ema
    return ema
```

**Impact:** Crossover signals now fire at the correct moment (when exponentially-weighted fast average crosses slow average). The first few bars after a new trend have higher weight, which is precisely what makes EMA better than SMA for signal generation.

---

### 1.2 Angel One session refresh — `angel_one_market_data_service.py`

**Problem:** Angel One JWT tokens expire after approximately 24 hours. The platform authenticated once at startup and stored no refresh mechanism. After one day the `ltpData` calls silently return `status: False`, prices stop updating, and the strategy fires on stale data indefinitely.

**Fix:** Two additions:

1. `_refresh_session()` — calls `client.generateToken(refreshToken)` to extend the JWT without TOTP re-entry. Falls back to full re-authentication (`_authenticate()`) if the refresh token itself has expired.

2. `_session_refresh_loop()` — an `asyncio.Task` started in `run()` that sleeps 20 hours between refreshes. 20 hours was chosen to give a 4-hour safety margin before the 24-hour hard expiry.

```python
async def _session_refresh_loop(self) -> None:
    while self._running:
        await asyncio.sleep(20 * 3600)
        await loop.run_in_executor(None, self._refresh_session)
```

The task is cancelled cleanly in `stop()`.

---

### 1.3 Market hours gate — `angel_one_market_data_service.py`, `orchestrator.py`

**Problem (data layer):** Angel One returns the previous session's closing LTP when the market is closed. Every 3-second poll between 15:30 and 09:15 adds an identical price to the `_recent_closes` deque. After an overnight gap, the deque contains 8–16 hours of flat identical prices. When the market reopens:
- The EMA computed over those values is anchored to yesterday's close
- Realized volatility appears near-zero (no price movement)
- The HMM regime detector sees a flat series and may output incorrect regime labels
- The first real tick triggers a large apparent EMA divergence, generating a false crossover signal

**Problem (strategy layer):** Even if the data layer were gated, the orchestrator's strategy loop would keep firing `run_once()` every 2 seconds through the night, reading stale cached prices and potentially generating false signals.

**Fix — data layer:** `generate_once()` returns immediately if `is_market_open()` returns False. Additionally, `_clear_stale_history_if_new_day()` flushes all `_recent_closes` deques on the first poll of each new IST trading day, so the EMA and vol models start fresh.

**Fix — strategy layer:** `TradingOrchestrator._strategy_loop()` checks `is_market_open()` before calling `run_once()` — but only when `market_data_service.is_live_feed` is True. Simulated mode (`MarketDataService`) sets `is_live_feed = False` so it continues to run 24/7 for unrestricted offline testing.

```python
# orchestrator.py
if not self._market_data_service.is_live_feed or is_market_open():
    await self._strategy_engine.run_once()
```

**`market_hours.py`** is the single source of truth for IST session times:
```
NSE equity session: Mon–Fri, 09:15–15:30 IST
```
No holiday calendar is implemented yet — this is tracked as a Phase 2 enhancement.

---

### 1.4 WebSocket upgrade — deferred to Phase 2

The `SmartWebSocket` class in `smartapi-python==1.5.5` was assessed and found unsuitable for production use:
- Uses a deprecated Angel One endpoint (`wsfeeds.angelbroking.com`)
- Data is base64-encoded + zlib-compressed, requiring custom parsing
- Contains `print()` debug statements throughout (no structured logging)
- Auto-reconnect in `__on_error` calls `connect()` recursively, risking stack overflow on repeated failures

The market hours gate in Phase 1 eliminates the main cost of REST polling (wasted API calls when the market is closed). The upgrade to Angel One's newer Smartstream WebSocket API is tracked in Phase 2.

---

## Files changed

| File | Change |
|---|---|
| `apps/api/app/core/market_hours.py` | **Created** — IST market hours utility |
| `apps/api/app/services/strategy_engine.py` | `_ema()` static method added; crossover calculation fixed |
| `apps/api/app/services/angel_one_market_data_service.py` | Session refresh loop, market hours gate, stale history clear |
| `apps/api/app/services/market_data_service.py` | `is_live_feed = False` class attribute added |
| `apps/api/app/services/orchestrator.py` | Strategy loop gated to market hours for live feed |
| `apps/api/requirements.txt` | `logzero==1.7.0`, `websocket-client==1.9.0` added (undeclared `smartapi-python` deps) |
