# Phase 5 — Infrastructure

**Status: Planned**

## 5.1 Event-driven backtester

**Current gap:** There is no way to test a strategy on historical NSE data before running it live. All validation is either forward-running (paper) or on simulated Gaussian data (which underestimates tails and has no real correlations).

**Why this matters:** A strategy that looks profitable in paper trading may be overfitting to the specific market conditions that happened to occur after deployment. Backtesting on diverse historical periods (different regimes, stress events) is the only way to build confidence that the edge is genuine rather than coincidental.

**Key design principle:** The backtester must be event-driven, feeding bars to the strategy engine exactly as real-time bars would be — otherwise it is trivially easy to introduce look-ahead bias (using future data to make current decisions).

**Planned implementation:**

```python
class Backtester:
    def __init__(self, strategy_engine, paper_broker, risk_engine, start_date, end_date):
        ...
    
    async def run(self, historical_bars: list[Bar]) -> BacktestResult:
        for bar in historical_bars:  # bars are sorted by timestamp
            # Feed bar to market data service (simulates live tick)
            await self._market_data.on_bar(bar)
            # Run strategy exactly as live
            await self._strategy_engine.run_once()
            # Simulate fills using bar's OHLCV (realistic: cannot fill below low or above high)
            await self._settle_pending_orders(bar)
        return self._compile_results()
```

Data source: Angel One historical candle API (`getCandleData`) for NSE equities going back several years.

**Output metrics:**
- Total return, annualized return
- Sharpe ratio (annualized)
- Calmar ratio (return / max drawdown)
- Maximum drawdown and drawdown duration
- Win rate, average win/loss ratio
- Turnover (estimated transaction costs)
- Number of trades

---

## 5.2 Performance attribution

**Current gap:** P&L is tracked at the portfolio level. When the strategy makes or loses money, there is no way to know which component caused it.

**Example of why this matters:**
- The EMA crossover might be consistently wrong (losing ₹2000/week)
- But the ML veto might be saving the day (preventing ₹3000/week of losses)
- Net result: ₹1000/week gain, but the EMA signal is actually harmful

Without attribution, you would never know to remove the EMA signal and let the ML model trade directly.

**Planned implementation:** A `PerformanceAttributor` service that tracks:

| Dimension | Tracked |
|---|---|
| Symbol | P&L per symbol (which stocks are profitable) |
| Signal layer | Did the ML veto add or subtract value? Did the regime filter help? |
| Time of day | Are morning signals better than afternoon signals? |
| Market regime | Does the strategy outperform in trending vs. choppy regimes? |
| Drawdown level | Does performance degrade near the drawdown scalar threshold? |

Stored in a `PerformanceAttribution` table, queryable from the frontend dashboard.

---

## 5.3 Walk-forward parameter optimization

**Current problem:** Parameters like `fast_window=8`, `slow_window=21` are hardcoded defaults. If you tune them manually on historical data, you will overfit — the optimal in-sample parameters are almost never optimal out-of-sample.

**The bias-variance tradeoff applied to parameter tuning:**
```
In-sample optimal parameters → high in-sample SR → low out-of-sample SR
The difference is the "optimization bias" — larger when the parameter space is large
```

**Planned fix — anchored walk-forward optimization:**

```
Anchor   [-------- train (252 days) --------] [test (21 days)]
Step 1   [train]                               [test]
Step 2   [---- train (273 days) -----------] [test]
Step 3   [------ train (294 days) ---------] [test]
...
```

1. For each training window, run a grid search (or Bayesian optimization) over the parameter space
2. Record the optimal parameters
3. Apply those parameters to the next 21-day out-of-sample period
4. Evaluate performance only on out-of-sample periods (honest estimate)
5. Track **parameter stability** — if optimal parameters shift dramatically every 21 days, the strategy has a short half-life and is likely overfitting

**Implementation:** Use `StrategyConfig.parameters` JSON field to store the current parameters. The optimizer updates this field at the end of each 21-day period.

---

## 5.4 Monitoring and alerting

**Current gap:** There is no automated monitoring. Issues (session expiry, price feed stale, risk limit breaches) only surface in logs, which require manual inspection.

**Planned additions:**
- Health check endpoint: `GET /health` returns feed status, last price timestamp, open positions, P&L
- Alerting on:
  - Price feed silent for > 30s during market hours
  - JWT refresh failure
  - Kill switch activation
  - Daily loss limit breach
  - Any `ERROR` level log
- Alert channels: Telegram bot (simplest), or email via SMTP

---

## 5.5 A/B testing framework for strategies

**Current state:** Only one strategy (`ema_cross_v2`) is active. `StrategyConfig` already supports multiple strategies via the `is_active` flag, but there is no allocation or performance comparison framework.

**Planned additions:**
- Run multiple strategies simultaneously with separate capital allocations
- Track performance per strategy in `PerformanceAttribution`
- Champion/challenger framework: new strategies run at 10% allocation; promoted to 50% if out-of-sample SR > current champion after 63 days (one quarter)

---

## Acceptance criteria

- [ ] Backtester produces identical P&L to live paper trading when fed the same historical bars (determinism check)
- [ ] Walk-forward optimization: out-of-sample SR is within 20% of in-sample SR (overfitting control)
- [ ] Performance attribution identifies at least one signal layer that subtracts value (proves the system can find problems)
- [ ] Health check endpoint returns stale feed alert within 60s of feed going silent
- [ ] A/B framework prevents total allocation from exceeding 100% of capital
