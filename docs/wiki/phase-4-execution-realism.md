# Phase 4 — Execution Realism

**Status: Planned**

## 4.1 Square-root market impact model

**Current problem:**
```python
slippage = random.uniform(0.0002, 0.0015)  # 2–15 bps, flat
fill_price = market_price * (1 + slippage)
```

This model has zero dependence on order size relative to market volume. A 1-share order and a 1000-share order pay the same slippage in bps terms. In reality, large orders move the market — the fill price worsens as you consume liquidity.

**The Almgren-Chriss square-root law (empirically validated across exchanges, asset classes, and decades):**
```
impact_bps = η × σ_daily × √(Q / ADV)
```
Where:
- `Q` = order size in shares
- `ADV` = average daily volume (20-day rolling)
- `σ_daily` = daily return volatility
- `η` ≈ 0.1–0.5 (market-specific constant; NSE mid-cap: ~0.3)

**Why this matters:**
- For a 5-share order on RELIANCE (ADV ≈ 5M shares): impact ≈ 0.3 × 1.5% × √(5/5M) ≈ 0.1 bps → negligible
- For a 500-share order: impact ≈ 0.3 × 1.5% × √(500/5M) ≈ 1.4 bps → material
- For a 5000-share order: impact ≈ 0.3 × 1.5% × √(5000/5M) ≈ 4.5 bps → significant

The current flat-random model makes large orders appear deceptively cheap, causing strategy P&L to look better in paper trading than it will in live trading.

**Planned implementation:**
```python
def _compute_slippage_bps(quantity: int, adv: float, daily_vol: float) -> float:
    participation_rate = quantity / max(adv, 1)
    impact = 0.3 * daily_vol * math.sqrt(participation_rate)
    # Add fixed spread component (1–3 bps for NSE liquid stocks)
    spread = random.uniform(0.0001, 0.0003)
    return impact + spread

# ADV tracked via 20-day rolling volume average in AngelOneMarketDataService
```

---

## 4.2 Limit orders

**Current problem:** All paper orders are filled at `market_price ± slippage`. The platform has no limit order concept. In practice, algorithmic traders use limit orders for 70–90% of executions to capture (rather than pay) the bid-ask spread.

**Why it matters (compounding math):**
```
NSE bid-ask spread on liquid stocks: ~3–5 bps
Position size: ₹50,000
Per round-trip saving (limit vs. market): ₹50,000 × 5bps × 2 = ₹50
Over 500 round-trips per year: ₹25,000 saved
On a ₹10L account: 2.5% annual alpha from execution alone
```

**Planned implementation:**
1. Add `order_type: LIMIT | MARKET` to order parameters
2. In `PaperBroker`, implement a fill model for limit orders:
   - Track the limit price per order
   - On each subsequent `generate_once()` tick, check if `price ≤ limit` (BUY) or `price ≥ limit` (SELL)
   - Fill with probability: `P(fill) = Φ((limit - mid) / spread)` — orders deeper in the spread fill more reliably
   - Unfilled limit orders expire after a configurable timeout (default: end of session)
3. `StrategyEngine` places limit orders at `EMA_mid ± (spread × 0.5)` instead of market orders

---

## 4.3 TWAP / VWAP execution (large order slicing)

**Current problem:** The strategy places entire order quantities in a single fill. For the order sizes the current strategy generates (5–200 shares) this is fine. But as the platform scales, larger orders need to be broken into smaller child orders to minimize market impact.

**Planned implementation (for orders > 0.01% of ADV):**
- **TWAP**: split the order into N equal slices, execute one slice every T seconds
- **VWAP**: weight slice sizes by the predicted volume at each time interval (U-shaped intraday volume curve)
- Track parent-child order relationship in the `orders` table

This is low priority for the current trading size but critical before scaling position sizes.

---

## 4.4 Order book simulation (bid-ask spread)

**Current problem:** The platform has no concept of a bid-ask spread. All fills happen at a single "market price." In reality, you buy at the ask (above mid) and sell at the bid (below mid).

**Planned implementation:**
- Model the spread as `spread_bps = f(liquidity_tier, time_of_day, volatility)`
- Liquid Nifty50 stocks: 1–3 bps at mid-session, 5–10 bps at open/close
- `fill_price_buy = mid × (1 + spread/2 + impact)`
- `fill_price_sell = mid × (1 - spread/2 - impact)`

---

## Acceptance criteria

- [ ] Paper P&L for 500-share orders is ≥ 3× more pessimistic than the current flat-slippage model
- [ ] Limit orders fill at or better than the limit price in 95% of cases where the price crosses the limit
- [ ] TWAP execution reduces market impact by ≥ 40% vs. single-fill for orders > 0.05% ADV
- [ ] Order book simulation: buy fills consistently above mid, sell fills consistently below mid
