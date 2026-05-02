from dataclasses import dataclass
import math
from typing import Literal

OptionType = Literal["call", "put"]
_EPSILON = 1e-12


@dataclass(frozen=True)
class BlackScholesResult:
    call_price: float
    put_price: float
    d1: float
    d2: float
    delta_call: float
    delta_put: float
    gamma: float
    vega: float
    theta_call: float
    theta_put: float
    rho_call: float
    rho_put: float


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes_price_greeks(
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    volatility: float,
    dividend_yield: float = 0.0,
) -> BlackScholesResult:
    spot = max(float(spot), _EPSILON)
    strike = max(float(strike), _EPSILON)
    maturity = max(float(time_to_expiry), 0.0)
    sigma = max(float(volatility), _EPSILON)
    rate = float(rate)
    dividend_yield = float(dividend_yield)

    if maturity <= _EPSILON:
        call_intrinsic = max(spot - strike, 0.0)
        put_intrinsic = max(strike - spot, 0.0)
        delta_call = 1.0 if spot > strike else 0.0
        delta_put = -1.0 if strike > spot else 0.0
        return BlackScholesResult(
            call_price=call_intrinsic,
            put_price=put_intrinsic,
            d1=0.0,
            d2=0.0,
            delta_call=delta_call,
            delta_put=delta_put,
            gamma=0.0,
            vega=0.0,
            theta_call=0.0,
            theta_put=0.0,
            rho_call=0.0,
            rho_put=0.0,
        )

    sqrt_t = math.sqrt(maturity)
    carry = rate - dividend_yield
    d1 = (math.log(spot / strike) + (carry + 0.5 * sigma * sigma) * maturity) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    discount_r = math.exp(-rate * maturity)
    discount_q = math.exp(-dividend_yield * maturity)
    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    nmd1 = _norm_cdf(-d1)
    nmd2 = _norm_cdf(-d2)
    pdf_d1 = _norm_pdf(d1)

    call_price = (spot * discount_q * nd1) - (strike * discount_r * nd2)
    put_price = (strike * discount_r * nmd2) - (spot * discount_q * nmd1)

    delta_call = discount_q * nd1
    delta_put = discount_q * (nd1 - 1.0)
    gamma = (discount_q * pdf_d1) / (spot * sigma * sqrt_t)
    vega = spot * discount_q * pdf_d1 * sqrt_t

    theta_call = (
        -((spot * discount_q * pdf_d1 * sigma) / (2.0 * sqrt_t))
        - (rate * strike * discount_r * nd2)
        + (dividend_yield * spot * discount_q * nd1)
    )
    theta_put = (
        -((spot * discount_q * pdf_d1 * sigma) / (2.0 * sqrt_t))
        + (rate * strike * discount_r * nmd2)
        - (dividend_yield * spot * discount_q * nmd1)
    )
    rho_call = strike * maturity * discount_r * nd2
    rho_put = -strike * maturity * discount_r * nmd2

    return BlackScholesResult(
        call_price=call_price,
        put_price=put_price,
        d1=d1,
        d2=d2,
        delta_call=delta_call,
        delta_put=delta_put,
        gamma=gamma,
        vega=vega,
        theta_call=theta_call,
        theta_put=theta_put,
        rho_call=rho_call,
        rho_put=rho_put,
    )


def implied_volatility_from_price(
    option_type: OptionType,
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    dividend_yield: float = 0.0,
    initial_volatility: float = 0.2,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> float:
    option_type = option_type.lower()  # type: ignore[assignment]
    if option_type not in {"call", "put"}:
        raise ValueError("option_type must be either 'call' or 'put'")

    market_price = max(float(market_price), 0.0)
    sigma = max(float(initial_volatility), 1e-4)

    for _ in range(max_iterations):
        result = black_scholes_price_greeks(
            spot=spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            rate=rate,
            volatility=sigma,
            dividend_yield=dividend_yield,
        )
        model_price = result.call_price if option_type == "call" else result.put_price
        diff = model_price - market_price
        if abs(diff) < tolerance:
            return sigma
        vega = max(result.vega, 1e-8)
        sigma = sigma - (diff / vega)
        sigma = min(max(sigma, 1e-4), 5.0)

    return sigma
