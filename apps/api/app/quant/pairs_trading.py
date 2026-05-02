from collections.abc import Sequence
from dataclasses import dataclass
import math

_EPSILON = 1e-12


@dataclass(frozen=True)
class PairsSignal:
    hedge_ratio: float
    spread_mean: float
    spread_std: float
    zscore: float
    signal: str


def _clean(values: Sequence[float]) -> list[float]:
    cleaned: list[float] = []
    for value in values:
        number = float(value)
        if math.isfinite(number):
            cleaned.append(number)
    return cleaned


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    return max(sum((value - avg) ** 2 for value in values) / (len(values) - 1), 0.0)


def estimate_hedge_ratio(x_prices: Sequence[float], y_prices: Sequence[float]) -> float:
    x = _clean(x_prices)
    y = _clean(y_prices)
    if len(x) < 2 or len(y) < 2:
        return 1.0
    lookback = min(len(x), len(y))
    x = x[-lookback:]
    y = y[-lookback:]
    x_mean = _mean(x)
    y_mean = _mean(y)
    denominator = sum((value - x_mean) ** 2 for value in x)
    if denominator <= _EPSILON:
        return 1.0
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    return numerator / denominator


def pairs_spread_signal(
    x_prices: Sequence[float],
    y_prices: Sequence[float],
    lookback: int = 80,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
) -> PairsSignal | None:
    x = _clean(x_prices)
    y = _clean(y_prices)
    if len(x) < 5 or len(y) < 5:
        return None
    horizon = min(len(x), len(y), max(int(lookback), 5))
    x = x[-horizon:]
    y = y[-horizon:]
    beta = estimate_hedge_ratio(x, y)
    spread = [y_value - (beta * x_value) for x_value, y_value in zip(x, y)]

    spread_mean = _mean(spread)
    spread_std = math.sqrt(max(_variance(spread), 1e-8))
    zscore = (spread[-1] - spread_mean) / spread_std

    signal = "HOLD"
    if zscore >= abs(entry_z):
        signal = "SHORT_SPREAD"
    elif zscore <= -abs(entry_z):
        signal = "LONG_SPREAD"
    elif abs(zscore) <= abs(exit_z):
        signal = "EXIT"

    return PairsSignal(
        hedge_ratio=beta,
        spread_mean=spread_mean,
        spread_std=spread_std,
        zscore=zscore,
        signal=signal,
    )
