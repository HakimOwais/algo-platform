# Phase 3 — Risk Architecture

**Status: Planned**

## 3.1 Smooth drawdown scalar (continuous, not step-function)

**Current problem:**
```python
if dd >= 0.20: scalar = 0.0   # STOP
elif dd >= 0.10: scalar = 0.5  # CAUTION
else: scalar = 1.0             # NORMAL
```

This creates two discontinuities:
- At 9.9% DD: full size. At 10.0001% DD: half size — instantaneous 50% position cut.
- At 19.9% DD: half size. At 20.0001% DD: zero — instantaneous full stop.

**Why this is dangerous mathematically:** Step functions create incentives to "game the boundary" and produce unstable position sizing near the thresholds. More importantly, they are not differentiable — you cannot reason about the rate of position reduction as drawdown worsens. A portfolio at 15% drawdown should have a clear, predictable exposure level.

**Planned fix — linear interpolation:**
```python
def compute_drawdown_scalar(peak_nav, current_nav, stop_threshold=0.20):
    dd = (peak_nav - current_nav) / peak_nav
    return max(0.0, 1.0 - dd / stop_threshold)
```

This gives:
- DD = 0%: scalar = 1.0
- DD = 10%: scalar = 0.5
- DD = 20%: scalar = 0.0 (hard stop)
- DD between 0–20%: smooth linear reduction

Same endpoints as before, continuous everywhere. Position size decreases predictably as losses accumulate.

---

## 3.2 Student-t Monte Carlo (replace Gaussian)

**Current problem:** Both the strategy-level and risk-level Monte Carlo VaR/CVaR simulations draw paths from a Gaussian distribution. This systematically underestimates tail risk.

**Mathematical justification:** NSE equity returns have:
- Excess kurtosis ≈ 5–8 (Gaussian = 0)
- 3σ event probability: Gaussian ≈ 0.27%, Student-t(ν=5) ≈ 1.8% — 6.6× higher
- 4σ event probability: Gaussian ≈ 0.006%, Student-t(ν=5) ≈ 0.5% — 83× higher

Using Gaussian Monte Carlo means your stated VaR at 95% confidence is really only providing ~85–88% protection in practice.

**Planned fix:**
```python
from scipy.stats import t as student_t

# Replace normal draws with Student-t draws
innovations = student_t.rvs(df=nu, size=(paths, horizon))
# Scale to match empirical volatility
innovations = innovations * std / student_t.std(df=nu)
```

Also add **historical simulation** as a parallel estimate: resample from the actual last 252 days of realized returns. Report the more conservative (higher) VaR of the two methods.

Target: ν = 5 (degrees of freedom), calibrated to match NSE empirical kurtosis ≈ 6.

---

## 3.3 Portfolio-level delta cap

**Current problem:** Each symbol is sized independently. The risk engine checks individual order limits but has no aggregate portfolio risk check. Five simultaneous BUY signals (all Nifty-correlated) create effective exposure of:

```
portfolio_delta ≈ Σ (position_size_i × beta_i_to_Nifty)
                ≈ 5 × single_position × avg_correlation
                ≈ 5 × single_position × 0.7
                = 3.5× single_position risk in Nifty terms
```

The risk engine treats these as independent when they are not.

**Planned fix:**
1. Maintain a `portfolio_beta` estimate: after each fill, compute `Σ (qty_i × price_i × beta_i)` for all open positions
2. Before placing each new order, estimate its contribution to `portfolio_beta`
3. If `(portfolio_beta + new_contribution) > portfolio_beta_limit`, scale down the new order quantity proportionally
4. Broadcast a `risk.beta_cap` event when this triggers

Beta-to-Nifty for each symbol can be approximated from the correlation of `_recent_closes` to a Nifty50 price feed (add `^NSEI` or use Nifty ETF token `NIFTYBEES:16654`).

---

## 3.4 CVaR as primary risk metric

**Current problem:** VaR is the primary gating metric:
```python
if var_amount > max_mc_var_inr: reject order
```

**Mathematical problem:** VaR is not sub-additive. If position A has VaR₉₅ = ₹1000 and position B has VaR₉₅ = ₹1000, the combined portfolio's VaR₉₅ can be more than ₹2000 under correlated stress. VaR tells you "you will not lose more than X in 95% of scenarios" but says nothing about the magnitude of the 5% worst scenarios.

CVaR (Conditional VaR / Expected Shortfall) is the average loss *given* you are already in the 5% tail. It is sub-additive, coherent, and captures tail severity rather than just tail probability.

**Planned fix:** Make CVaR the primary rejection criterion. Keep VaR as a secondary indicator.
```python
# Current
if var_amount > max_mc_var_inr: reject

# After
if cvar_amount > max_mc_cvar_inr: reject  # primary
if var_amount > max_mc_var_inr: warn      # secondary
```

CVaR is already computed by `monte_carlo_var_cvar_from_prices()` — this is a one-line change to the ordering of checks in `risk_engine.py`.

---

## 3.5 Stress testing against historical scenarios

**Current problem:** The Monte Carlo simulation generates synthetic paths from estimated return distributions. It cannot reproduce the specific correlation structures and volatility spikes of named market events.

**Planned fix:** Maintain a library of historical stress scenarios with known return series:

| Scenario | Period | NSE drawdown |
|---|---|---|
| COVID crash | Feb–Mar 2020 | −38% in 35 days |
| NBFC crisis | Sep–Oct 2018 | −15% in 6 weeks |
| Demonetization | Nov 2016 | −10% in 3 days |
| Global financial crisis | Jan–Mar 2009 | −35% in 3 months |

Before live deployment, run each strategy through these scenarios using the backtester (Phase 5) and verify that the risk engine would have triggered appropriate kill-switches.

---

## Acceptance criteria

- [ ] Drawdown scalar is monotonically decreasing and continuous across [0%, 20%]
- [ ] MC VaR with Student-t(ν=5) is ≥ 1.5× the Gaussian estimate at 95% confidence
- [ ] Portfolio beta cap prevents net Nifty exposure from exceeding 2× single position risk
- [ ] CVaR breach blocks more orders than VaR breach in backtests on stress scenarios
- [ ] All five historical stress scenarios result in kill-switch activation at or before peak drawdown
