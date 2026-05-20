"""Stage 3: Allocation weight — equal blend of MV, risk-parity, and momentum.

Writes alloc_scale = (mv_w + rp_w + mo_w) / 3 * n_syms, clamped to [0.5, 1.5].
"""
from __future__ import annotations

from app.quant._numeric import clamp
from app.services.strategy.context import CycleContext, SignalContext


def apply_allocation(cycle: CycleContext, ctx: SignalContext) -> None:
    n_syms = max(len(cycle.price_history), 1)
    equal = 1.0 / n_syms

    mv_w = cycle.mv_weights.get(ctx.symbol, equal)
    rp_w = cycle.rp_weights.get(ctx.symbol, equal)
    mo_w = (
        cycle.cs_momentum.get(ctx.symbol, equal)
        if cycle.cs_momentum
        else equal
    )

    alloc_weight = (mv_w + rp_w + mo_w) / 3.0
    ctx.alloc_scale = clamp(alloc_weight * n_syms, 0.5, 1.5)
    ctx.diagnostics["allocation"] = {
        "mv_weight": round(mv_w, 6),
        "rp_weight": round(rp_w, 6),
        "momentum_weight": round(mo_w, 6),
    }
