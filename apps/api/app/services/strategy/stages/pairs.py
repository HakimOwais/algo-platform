"""Stage 6: Kalman pairs context.

Uses the anchor symbol (first in the universe) as the reference leg.
When the Kalman spread signal contradicts the EMA signal, tail_scale is
discounted by 25 % to reflect the conflicting directional evidence.
"""
from __future__ import annotations

from app.quant.pairs_kalman import kalman_hedge_ratio
from app.services.strategy.context import CycleContext, SignalContext


def apply_pairs(cycle: CycleContext, ctx: SignalContext) -> None:
    if not cycle.params.get("use_kalman_pairs", True):
        return

    anchor = cycle.anchor_symbol
    if not anchor or anchor == ctx.symbol:
        return

    anchor_prices = cycle.price_history.get(anchor)
    if not anchor_prices:
        return

    kp = kalman_hedge_ratio(anchor_prices, ctx.closes)
    if kp is None:
        return

    ctx.diagnostics["pairs_kalman"] = {
        "anchor": anchor,
        "hedge_ratio": round(kp.hedge_ratio, 6),
        "zscore": round(kp.zscore, 6),
        "signal": kp.signal,
        "kalman_gain": round(kp.kalman_gain, 8),
    }

    # Contradicting signal → reduce tail exposure by 25 %
    if (ctx.signal_state > 0 and kp.signal == "SHORT_SPREAD") or (
        ctx.signal_state < 0 and kp.signal == "LONG_SPREAD"
    ):
        ctx.tail_scale *= 0.75
