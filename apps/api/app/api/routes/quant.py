from collections.abc import Sequence
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.quant.black_scholes import black_scholes_price_greeks, implied_volatility_from_price
from app.quant.portfolio_models import mean_variance_weights, risk_parity_weights_from_returns

router = APIRouter(prefix="/quant", tags=["quant"])


class BlackScholesRequest(BaseModel):
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    time_to_expiry: float = Field(gt=0, description="Time to expiry in years")
    rate: float = 0.0
    volatility: float = Field(gt=0, description="Annualized volatility (decimal)")
    dividend_yield: float = 0.0


class BlackScholesResponse(BaseModel):
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


class ImpliedVolRequest(BaseModel):
    option_type: Literal["call", "put"]
    market_price: float = Field(ge=0)
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    time_to_expiry: float = Field(gt=0)
    rate: float = 0.0
    dividend_yield: float = 0.0
    initial_volatility: float = Field(default=0.2, gt=0)


class ImpliedVolResponse(BaseModel):
    implied_volatility: float


class PortfolioWeightsRequest(BaseModel):
    returns_by_symbol: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Dictionary of symbol -> return series (prefer log returns).",
    )
    risk_aversion: float = Field(default=3.0, gt=0)
    long_only: bool = True


class PortfolioWeightsResponse(BaseModel):
    mean_variance_weights: dict[str, float]
    risk_parity_weights: dict[str, float]


@router.post("/options/black-scholes", response_model=BlackScholesResponse)
async def black_scholes_endpoint(payload: BlackScholesRequest) -> BlackScholesResponse:
    result = black_scholes_price_greeks(
        spot=payload.spot,
        strike=payload.strike,
        time_to_expiry=payload.time_to_expiry,
        rate=payload.rate,
        volatility=payload.volatility,
        dividend_yield=payload.dividend_yield,
    )
    return BlackScholesResponse(
        call_price=result.call_price,
        put_price=result.put_price,
        d1=result.d1,
        d2=result.d2,
        delta_call=result.delta_call,
        delta_put=result.delta_put,
        gamma=result.gamma,
        vega=result.vega,
        theta_call=result.theta_call,
        theta_put=result.theta_put,
        rho_call=result.rho_call,
        rho_put=result.rho_put,
    )


@router.post("/options/implied-vol", response_model=ImpliedVolResponse)
async def implied_vol_endpoint(payload: ImpliedVolRequest) -> ImpliedVolResponse:
    value = implied_volatility_from_price(
        option_type=payload.option_type,
        market_price=payload.market_price,
        spot=payload.spot,
        strike=payload.strike,
        time_to_expiry=payload.time_to_expiry,
        rate=payload.rate,
        dividend_yield=payload.dividend_yield,
        initial_volatility=payload.initial_volatility,
    )
    return ImpliedVolResponse(implied_volatility=value)


@router.post("/portfolio/weights", response_model=PortfolioWeightsResponse)
async def portfolio_weights_endpoint(payload: PortfolioWeightsRequest) -> PortfolioWeightsResponse:
    cleaned: dict[str, Sequence[float]] = {
        symbol: series
        for symbol, series in payload.returns_by_symbol.items()
        if len(series) >= 2
    }
    return PortfolioWeightsResponse(
        mean_variance_weights=mean_variance_weights(
            returns_by_symbol=cleaned,
            risk_aversion=payload.risk_aversion,
            long_only=payload.long_only,
        ),
        risk_parity_weights=risk_parity_weights_from_returns(cleaned),
    )
