"""Stage 4: Monte Carlo tail-risk guard.

Scales down tail_scale when MC VaR exceeds the risk budget.
Clamped to [0.25, 1.25] so it never completely silences a signal.
"""
from __future__ import annotations

from app.quant._numeric import clamp
from app.quant.monte_carlo import monte_carlo_var_cvar_from_prices
from app.services.strategy.context import CycleContext, SignalContext


def apply_tail_risk(cycle: CycleContext, ctx: SignalContext) -> None:
    if not cycle.params.get("use_monte_carlo_guard", True):
        return

    mc_conf = float(cycle.params.get("mc_confidence", 0.95))
    mc_steps = int(cycle.params.get("mc_horizon_steps", 12))
    mc_paths = int(cycle.params.get("mc_paths", 1500))
    risk_budget = float(cycle.params.get("risk_budget_per_order_inr", 1200.0))
    base_lot = int(cycle.params.get("trade_quantity", 5))

    mc = monte_carlo_var_cvar_from_prices(
        prices=ctx.closes,
        notional=ctx.closes[-1] * max(base_lot, 1),
        confidence=mc_conf,
        horizon_steps=mc_steps,
        paths=mc_paths,
        random_seed=13,
    )

    ctx.diagnostics["monte_carlo"] = {
        "var": round(mc.var_amount, 2) if mc else None,
        "cvar": round(mc.cvar_amount, 2) if mc else None,
    }

    if mc and mc.var_amount > 0:
        ctx.tail_scale = clamp(risk_budget / mc.var_amount, 0.25, 1.25)
