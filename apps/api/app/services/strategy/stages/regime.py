"""Stage 1: Regime filter — 2-state Gaussian HMM.

Reduces position size to 50 % in the CHOPPY regime.
No I/O — pure function of CycleContext + SignalContext.
"""
from __future__ import annotations

from app.quant.regime import detect_regime
from app.services.strategy.context import CycleContext, SignalContext


def apply_regime(cycle: CycleContext, ctx: SignalContext) -> None:
    if not cycle.params.get("use_regime_filter", True):
        return
    if len(ctx.returns) < 30:
        return

    regime = detect_regime(ctx.returns)
    ctx.regime_scalar = regime.position_scalar
    ctx.diagnostics["regime"] = {
        "label": regime.regime_label,
        "trending_prob": round(regime.trending_prob, 4),
        "scalar": regime.position_scalar,
    }
