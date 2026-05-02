"""Quantitative models and analytics utilities.

This package keeps statistical and mathematical models modular so they can be
reused by strategy, risk, and external API endpoints.
"""

from app.quant.black_scholes import (
    BlackScholesResult,
    black_scholes_price_greeks,
    implied_volatility_from_price,
)
from app.quant.monte_carlo import MonteCarloRiskResult, monte_carlo_var_cvar_from_prices
from app.quant.portfolio_models import (
    kelly_fraction,
    mean_variance_weights,
    risk_parity_weights_from_returns,
)
from app.quant.returns import log_returns
from app.quant.volatility_models import (
    ArchModelResult,
    GarchModelResult,
    annualize_volatility,
    estimate_arch_1,
    estimate_garch_1_1,
)

__all__ = [
    "ArchModelResult",
    "BlackScholesResult",
    "GarchModelResult",
    "MonteCarloRiskResult",
    "annualize_volatility",
    "black_scholes_price_greeks",
    "estimate_arch_1",
    "estimate_garch_1_1",
    "implied_volatility_from_price",
    "kelly_fraction",
    "log_returns",
    "mean_variance_weights",
    "monte_carlo_var_cvar_from_prices",
    "risk_parity_weights_from_returns",
]
