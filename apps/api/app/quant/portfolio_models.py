from collections.abc import Mapping, Sequence
import math

_EPSILON = 1e-12


def _sanitize_series(values: Sequence[float]) -> list[float]:
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


def mean_variance_weights(
    returns_by_symbol: Mapping[str, Sequence[float]],
    risk_aversion: float = 3.0,
    ridge: float = 1e-6,
    long_only: bool = True,
) -> dict[str, float]:
    _ = ridge  # kept for signature compatibility
    raw_scores: dict[str, float] = {}
    for symbol, series in returns_by_symbol.items():
        cleaned = _sanitize_series(series)
        if len(cleaned) < 5:
            continue
        expected = _mean(cleaned)
        variance = max(_variance(cleaned), 1e-8)
        score = expected / max(float(risk_aversion), _EPSILON) / variance
        if long_only:
            score = max(score, 0.0)
        raw_scores[symbol] = score

    if not raw_scores:
        return {}

    total = sum(abs(value) for value in raw_scores.values())
    if total <= _EPSILON:
        equal = 1.0 / len(raw_scores)
        return {symbol: equal for symbol in raw_scores}
    return {symbol: value / total for symbol, value in raw_scores.items()}


def risk_parity_weights_from_volatility(volatility_by_symbol: Mapping[str, float]) -> dict[str, float]:
    inverse_vol: dict[str, float] = {}
    for symbol, volatility in volatility_by_symbol.items():
        vol = max(abs(float(volatility)), 1e-6)
        inverse_vol[symbol] = 1.0 / vol
    total = sum(inverse_vol.values())
    if total <= _EPSILON:
        return {}
    return {symbol: weight / total for symbol, weight in inverse_vol.items()}


def risk_parity_weights_from_returns(
    returns_by_symbol: Mapping[str, Sequence[float]],
    min_observations: int = 20,
) -> dict[str, float]:
    volatility_by_symbol: dict[str, float] = {}
    for symbol, series in returns_by_symbol.items():
        cleaned = _sanitize_series(series)
        if len(cleaned) < min_observations:
            continue
        volatility_by_symbol[symbol] = math.sqrt(max(_variance(cleaned), 1e-8))
    return risk_parity_weights_from_volatility(volatility_by_symbol)


def kelly_fraction(
    expected_return: float,
    variance: float,
    floor: float = -1.0,
    leverage_cap: float = 1.5,
) -> float:
    if variance <= _EPSILON:
        return 0.0
    raw = float(expected_return) / float(variance)
    return max(floor, min(raw, leverage_cap))
