from app.quant.black_scholes import black_scholes_price_greeks, implied_volatility_from_price
from app.quant.monte_carlo import monte_carlo_var_cvar_from_returns
from app.quant.portfolio_models import mean_variance_weights, risk_parity_weights_from_returns
from app.quant.volatility_models import estimate_arch_1, estimate_garch_1_1


def test_arch_and_garch_forecast_positive_variance() -> None:
    returns = [
        0.01,
        -0.008,
        0.006,
        -0.009,
        0.004,
        0.003,
        -0.007,
        0.005,
        -0.004,
        0.002,
    ] * 8
    arch = estimate_arch_1(returns)
    garch = estimate_garch_1_1(returns)

    assert arch.next_variance > 0
    assert garch.next_variance > 0
    assert garch.alpha >= 0
    assert garch.beta >= 0


def test_black_scholes_and_implied_vol_consistency() -> None:
    result = black_scholes_price_greeks(
        spot=100.0,
        strike=100.0,
        time_to_expiry=0.5,
        rate=0.06,
        volatility=0.25,
    )
    implied = implied_volatility_from_price(
        option_type="call",
        market_price=result.call_price,
        spot=100.0,
        strike=100.0,
        time_to_expiry=0.5,
        rate=0.06,
    )
    assert result.call_price > 0
    assert result.put_price > 0
    assert abs(implied - 0.25) < 1e-3


def test_monte_carlo_var_and_cvar_amounts() -> None:
    returns = [
        0.004,
        -0.005,
        0.003,
        -0.009,
        0.006,
        -0.004,
        0.005,
        -0.003,
    ] * 20
    metrics = monte_carlo_var_cvar_from_returns(
        returns=returns,
        notional=100_000,
        confidence=0.95,
        horizon_steps=10,
        paths=1000,
        random_seed=42,
    )
    assert metrics is not None
    assert metrics.var_amount >= 0
    assert metrics.cvar_amount >= metrics.var_amount


def test_portfolio_weights_are_normalized() -> None:
    returns_by_symbol = {
        "A": [0.001, 0.002, -0.001, 0.003, -0.002, 0.002, 0.001, -0.001, 0.002, 0.001] * 5,
        "B": [0.0005, -0.0002, 0.001, -0.0005, 0.0008, 0.0012, -0.0009, 0.0011, 0.0003, 0.0007] * 5,
        "C": [-0.0003, 0.0015, 0.0008, -0.0002, 0.001, -0.0001, 0.0006, 0.0004, -0.0005, 0.0009] * 5,
    }
    mv = mean_variance_weights(returns_by_symbol)
    rp = risk_parity_weights_from_returns(returns_by_symbol)
    assert abs(sum(abs(value) for value in mv.values()) - 1.0) < 1e-6
    assert abs(sum(rp.values()) - 1.0) < 1e-6
