"""Stage 5: Fractional Kelly position sizing.

Uses 25 % Kelly (configurable) to bound leverage and reduce ruin probability.
kelly_scale is offset by +0.5 so a zero-Kelly signal still trades at half size.
"""
from __future__ import annotations

from app.quant._numeric import clamp, mean, variance
from app.services.risk_engine import fractional_kelly
from app.services.strategy.context import CycleContext, SignalContext


def apply_kelly(cycle: CycleContext, ctx: SignalContext) -> None:
    fraction = float(cycle.params.get("kelly_fraction", 0.25))

    if ctx.returns:
        mu = mean(ctx.returns)
        var = variance(ctx.returns)
    else:
        mu = 0.0
        var = 1e-6

    kelly = fractional_kelly(expected_return=mu, variance=var, fraction=fraction, cap=1.5)
    ctx.kelly_scale = clamp(max(kelly, 0.0) + 0.5, 0.25, 1.5)
    ctx.diagnostics["kelly"] = {
        "mu": round(mu, 8),
        "variance": round(var, 10),
        "kelly_fraction": round(kelly, 6),
        "kelly_scale": round(ctx.kelly_scale, 6),
    }
