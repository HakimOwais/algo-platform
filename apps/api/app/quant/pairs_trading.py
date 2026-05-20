from collections.abc import Sequence
from dataclasses import dataclass
import math

from app.quant._numeric import EPS, clean, mean, variance, covariance


@dataclass(frozen=True)
class PairsSignal:
    hedge_ratio: float
    spread_mean: float
    spread_std: float
    zscore: float
    signal: str


def estimate_hedge_ratio(x_prices: Sequence[float], y_prices: Sequence[float]) -> float:
    x = clean(x_prices)
    y = clean(y_prices)
    if len(x) < 2 or len(y) < 2:
        return 1.0
    lookback = min(len(x), len(y))
    x = x[-lookback:]
    y = y[-lookback:]
    denom = sum((v - mean(x)) ** 2 for v in x)
    if denom <= EPS:
        return 1.0
    return covariance(x, y) * len(x) / denom  # == Cov(x,y)/Var(x) with ddof=0


def pairs_spread_signal(
    x_prices: Sequence[float],
    y_prices: Sequence[float],
    lookback: int = 80,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
) -> PairsSignal | None:
    x = clean(x_prices)
    y = clean(y_prices)
    if len(x) < 5 or len(y) < 5:
        return None
    horizon = min(len(x), len(y), max(int(lookback), 5))
    x = x[-horizon:]
    y = y[-horizon:]
    beta = estimate_hedge_ratio(x, y)
    spread = [yv - beta * xv for xv, yv in zip(x, y)]

    sp_mean = mean(spread)
    sp_std = math.sqrt(max(variance(spread), 1e-8))
    zscore = (spread[-1] - sp_mean) / sp_std

    if zscore >= abs(entry_z):
        signal = "SHORT_SPREAD"
    elif zscore <= -abs(entry_z):
        signal = "LONG_SPREAD"
    elif abs(zscore) <= abs(exit_z):
        signal = "EXIT"
    else:
        signal = "HOLD"

    return PairsSignal(
        hedge_ratio=beta,
        spread_mean=sp_mean,
        spread_std=sp_std,
        zscore=zscore,
        signal=signal,
    )
