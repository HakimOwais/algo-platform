# Phase 2 — Signal Quality

**Status: Planned**

## 2.1 Replace Gaussian sim with GARCH(1,1) + Student-t

**Current problem:** `MarketDataService` generates prices with i.i.d. normal shocks (`random.gauss(0, 0.006)`). Real equity returns have two properties this violates:

- **Fat tails**: NSE intraday kurtosis ≈ 5–8 vs. 3 for Gaussian. The normal model underestimates 3σ+ moves by ~2–4×. Strategies tested on Gaussian simulation appear more profitable than they will be in reality because catastrophic moves are underrepresented.
- **Volatility clustering**: If today is volatile, tomorrow is likely volatile too. GARCH(1,1) captures this: `σ²[t] = ω + α·ε²[t-1] + β·σ²[t-1]`. The current model has no memory — each bar's volatility is independent of the previous one.

**Planned fix:**
```python
# GARCH(1,1) with Student-t innovations
omega, alpha, beta = 1e-6, 0.08, 0.90  # typical NSE intraday params
nu = 5  # degrees of freedom → kurtosis ≈ 6
variance = omega / (1 - alpha - beta)  # unconditional variance

shock = variance**0.5 * student_t(df=nu).rvs()
close = prev * (1 + drift + shock)
variance = omega + alpha * shock**2 + beta * variance  # update
```

Add a deterministic intraday volume curve (U-shaped: high at open/close, low at midday) to make volume-based ML features meaningful.

---

## 2.2 Multi-timeframe signal confirmation

**Current problem:** The EMA crossover fires on 1-minute bars. At the 1-minute level, market microstructure noise (bid-ask bounce, rounding) dominates true directional signal. The false positive rate is high.

**Standard solution:** The "cascade" approach — use a higher timeframe (15m or 60m) to establish trend direction, and a lower timeframe (1m or 3m) for entry timing. Only take EMA signals on 1m when they align with the higher-timeframe trend.

**Planned fix:**
- Aggregate 1m bars into 5m, 15m, 60m bars in `AngelOneMarketDataService`
- Compute regime and EMA direction on 15m bars
- In `StrategyEngine.run_once()`: add a `higher_tf_direction` check; skip signal if it opposes the 15m EMA direction

Typical improvement: 30–50% reduction in false crossovers (fewer whipsaws).

---

## 2.3 Stable portfolio optimizer (Ledoit-Wolf + Black-Litterman)

**Current problem:** The triple blend `(mv_weight + rp_weight + momentum_weight) / 3` has two issues:

1. **Mean-variance instability**: Small changes in expected return estimates cause large weight swings — the "error maximization" problem. This is why naive MV optimization often produces extreme concentrated allocations.
2. **Equal blending is arbitrary**: There is no theoretical justification for 1/3 weighting. The blend should reflect how much you trust each signal relative to its uncertainty.

**Planned fix:**

1. **Ledoit-Wolf shrinkage** on the covariance matrix before MV optimization. Pulls sample eigenvalues toward their grand mean, dramatically stabilizing weights without additional assumptions.

2. **Black-Litterman** for expected returns: start from market-cap implied equilibrium returns (neutral prior), then tilt toward the EMA + momentum signals (views). The posterior expected returns are a Bayesian blend — confident signals get more weight, uncertain signals revert toward equilibrium.

```python
# Shrinkage covariance
from sklearn.covariance import LedoitWolf
cov = LedoitWolf().fit(returns_matrix).covariance_

# BL posterior expected returns
tau = 0.05  # uncertainty in prior
pi = risk_aversion * cov @ w_market  # equilibrium returns
mu_bl = pi + tau * cov @ P.T @ inv(P @ tau * cov @ P.T + Omega) @ (q - P @ pi)
```

---

## 2.4 Stationary ML feature engineering

**Current problem:** `build_feature_vector()` uses raw OHLCV values. Raw prices are non-stationary (they have a trend/drift). A classifier trained on non-stationary features memorizes the level of prices during training rather than their dynamics. This causes severe out-of-sample degradation.

**Planned fix — replace raw values with stationary transforms:**

| Raw feature | Stationary replacement |
|---|---|
| `close` | log-return: `log(close[t] / close[t-1])` |
| `high, low` | normalized range: `(high - low) / close` |
| `volume` | Z-score vs. 20-day mean/std |
| — | RSI(14) — bounded [0,100] |
| — | Realized volatility (HAR-RV output — already computed) |
| — | Regime label from HMM (categorical) |
| — | Return autocorrelation at lag 1, 5, 10 |

All features should pass an Augmented Dickey-Fuller test for stationarity before being added to the feature set.

---

## 2.5 NSE holiday calendar

**Current problem:** `is_market_open()` only checks weekday and time — it has no awareness of NSE trading holidays (Republic Day, Diwali, etc.). The platform will attempt to poll and trade on exchange holidays.

**Planned fix:** Embed the NSE holiday calendar as a static lookup (updated annually) or fetch it from a public API at startup. Add holiday check to `is_market_open()`.

---

## 2.6 Angel One Smartstream WebSocket (deferred from Phase 1)

Replace REST `ltpData` polling with Angel One's newer Smartstream WebSocket API (separate package: `smartapi-python` >= 2.x or the official `smartapigw` package). Benefits:
- Tick-level data (not 3-second snapshots)
- HAR-RV estimates become more accurate with finer time resolution
- Eliminates polling overhead even during market hours

Implementation plan:
1. Authenticate and get feed token
2. Subscribe to LTP mode for all symbol tokens
3. On each tick: update `_latest_prices` (thread-safe via `asyncio.run_coroutine_threadsafe`)
4. Keep the 3-second bar generation loop but read from tick-updated cache instead of REST

---

## Acceptance criteria

- [ ] Simulated data passes kurtosis test: excess kurtosis ≥ 3.0
- [ ] Simulated data passes Engle ARCH test (volatility clustering present)
- [ ] Multi-timeframe confirmation reduces signal count by ≥ 20% in backtests (fewer whipsaws)
- [ ] MV portfolio weights are stable across 5% perturbation of input returns
- [ ] All ML features pass ADF stationarity test (p < 0.05)
- [ ] ML out-of-sample AUC ≥ 0.55 on real historical data
