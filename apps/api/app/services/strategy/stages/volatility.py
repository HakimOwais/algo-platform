"""Stage 2: Volatility forecast — HAR-RV preferred, GARCH+EGARCH blend fallback.

Writes vol_scale = target_vol / forecast_vol, clamped to [min_scale, max_scale].
"""
from __future__ import annotations

import math

from app.quant._numeric import clamp
from app.quant.har_rv import compute_daily_rv, estimate_egarch, estimate_har_rv
from app.quant.volatility_models import annualize_volatility, estimate_garch_1_1
from app.services.strategy.context import CycleContext, SignalContext


def apply_volatility(cycle: CycleContext, ctx: SignalContext) -> None:
    params = cycle.params
    bars_per_day = int(params.get("bars_per_day", 390))
    target_vol = float(params.get("target_vol_annual", 0.22))
    min_scale = float(params.get("min_position_scale", 0.35))
    max_scale = float(params.get("max_position_scale", 2.5))
    use_har = params.get("use_har_rv", True)

    daily_rv = compute_daily_rv(ctx.returns)
    har = estimate_har_rv(daily_rv, bars_per_day=bars_per_day) if use_har else None

    if har is not None:
        annual_vol = har.forecast_vol_annual
        ctx.diagnostics["volatility"] = {
            "model": "HAR-RV",
            "forecast_variance": round(har.forecast_variance, 10),
            "annualized": round(annual_vol, 6),
            "beta_daily": round(har.beta_daily, 6),
            "beta_weekly": round(har.beta_weekly, 6),
            "beta_monthly": round(har.beta_monthly, 6),
        }
    else:
        garch = estimate_garch_1_1(ctx.returns)
        egarch = estimate_egarch(ctx.returns, bars_per_day=bars_per_day)
        blended_var = 0.5 * garch.next_variance + 0.5 * egarch.next_variance
        annual_vol = annualize_volatility(
            math.sqrt(max(blended_var, 1e-12)), bars_per_day
        )
        ctx.diagnostics["volatility"] = {
            "model": "GARCH+EGARCH blend",
            "annualized": round(annual_vol, 6),
            "garch_alpha": round(garch.alpha, 6),
            "garch_beta": round(garch.beta, 6),
            "egarch_gamma": round(egarch.gamma, 6),
        }

    ctx.vol_scale = clamp(target_vol / max(annual_vol, 1e-6), min_scale, max_scale)
