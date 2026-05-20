from collections.abc import Mapping, Sequence
import math

from app.quant._numeric import EPS, clean, mean, variance


def mean_variance_weights(
    returns_by_symbol: Mapping[str, Sequence[float]],
    risk_aversion: float = 3.0,
    ridge: float = 1e-6,  # reserved for future full-covariance implementation
    long_only: bool = True,
) -> dict[str, float]:
    raw_scores: dict[str, float] = {}
    for symbol, series in returns_by_symbol.items():
        arr = clean(series)
        if len(arr) < 5:
            continue
        mu = mean(arr)
        var = max(variance(arr), 1e-8)
        score = mu / max(float(risk_aversion), EPS) / var
        if long_only:
            score = max(score, 0.0)
        raw_scores[symbol] = score

    if not raw_scores:
        return {}

    total = sum(abs(v) for v in raw_scores.values())
    if total <= EPS:
        equal = 1.0 / len(raw_scores)
        return {s: equal for s in raw_scores}
    return {s: v / total for s, v in raw_scores.items()}


def risk_parity_weights_from_volatility(
    volatility_by_symbol: Mapping[str, float],
) -> dict[str, float]:
    inv_vol = {s: 1.0 / max(abs(float(v)), 1e-6) for s, v in volatility_by_symbol.items()}
    total = sum(inv_vol.values())
    if total <= EPS:
        return {}
    return {s: w / total for s, w in inv_vol.items()}


def risk_parity_weights_from_returns(
    returns_by_symbol: Mapping[str, Sequence[float]],
    min_observations: int = 20,
) -> dict[str, float]:
    vol_by_symbol: dict[str, float] = {}
    for symbol, series in returns_by_symbol.items():
        arr = clean(series)
        if len(arr) < min_observations:
            continue
        vol_by_symbol[symbol] = math.sqrt(max(variance(arr), 1e-8))
    return risk_parity_weights_from_volatility(vol_by_symbol)


def kelly_fraction(
    expected_return: float,
    variance_: float,
    floor: float = -1.0,
    leverage_cap: float = 1.5,
) -> float:
    if variance_ <= EPS:
        return 0.0
    raw = float(expected_return) / float(variance_)
    return max(floor, min(raw, leverage_cap))
