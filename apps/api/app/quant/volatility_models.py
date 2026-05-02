from collections.abc import Sequence
from dataclasses import dataclass
import math

_EPSILON = 1e-12


@dataclass(frozen=True)
class ArchModelResult:
    omega: float
    alpha: float
    unconditional_variance: float
    next_variance: float


@dataclass(frozen=True)
class GarchModelResult:
    omega: float
    alpha: float
    beta: float
    unconditional_variance: float
    filtered_variance: float
    next_variance: float


def _sanitize(values: Sequence[float]) -> list[float]:
    output: list[float] = []
    for value in values:
        number = float(value)
        if math.isfinite(number):
            output.append(number)
    return output


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _variance(values: Sequence[float], ddof: int = 1) -> float:
    if len(values) <= ddof:
        return _EPSILON
    avg = _mean(values)
    return max(sum((value - avg) ** 2 for value in values) / (len(values) - ddof), _EPSILON)


def _covariance(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    x_mean = _mean(x)
    y_mean = _mean(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    return numerator / len(x)


def estimate_arch_1(returns: Sequence[float]) -> ArchModelResult:
    arr = _sanitize(returns)
    sample_var = _variance(arr)

    if len(arr) < 3:
        alpha = 0.1
        omega = sample_var * (1.0 - alpha)
        return ArchModelResult(
            omega=omega,
            alpha=alpha,
            unconditional_variance=sample_var,
            next_variance=sample_var,
        )

    x = [value * value for value in arr[:-1]]
    y = [value * value for value in arr[1:]]
    x_var = _variance(x, ddof=0)
    if x_var <= _EPSILON:
        alpha = 0.1
    else:
        alpha = _covariance(x, y) / x_var
    alpha = min(max(alpha, 0.0), 0.98)
    omega = max(_mean(y) - (alpha * _mean(x)), _EPSILON)
    unconditional = max(omega / max(1.0 - alpha, _EPSILON), _EPSILON)
    next_variance = max(omega + alpha * (arr[-1] ** 2), _EPSILON)
    return ArchModelResult(
        omega=omega,
        alpha=alpha,
        unconditional_variance=unconditional,
        next_variance=next_variance,
    )


def estimate_garch_1_1(returns: Sequence[float]) -> GarchModelResult:
    arr = _sanitize(returns)
    sample_var = _variance(arr)

    if len(arr) < 6:
        arch = estimate_arch_1(arr)
        return GarchModelResult(
            omega=arch.omega,
            alpha=arch.alpha,
            beta=0.0,
            unconditional_variance=arch.unconditional_variance,
            filtered_variance=arch.next_variance,
            next_variance=arch.next_variance,
        )

    alpha_grid = [0.02 + (0.33 * i / 14.0) for i in range(15)]
    beta_grid = [0.55 + (0.42 * i / 21.0) for i in range(22)]
    squared = [value * value for value in arr]

    best_score = math.inf
    best: tuple[float, float, float, float] | None = None
    for alpha in alpha_grid:
        for beta in beta_grid:
            if alpha + beta >= 0.995:
                continue
            omega = max(sample_var * (1.0 - alpha - beta), _EPSILON)
            h: list[float] = [sample_var]
            valid = True
            for idx in range(1, len(arr)):
                next_h = omega + alpha * squared[idx - 1] + beta * h[idx - 1]
                if not math.isfinite(next_h) or next_h <= 0:
                    valid = False
                    break
                h.append(next_h)
            if not valid:
                continue

            residual = [(squared[idx] - h[idx]) ** 2 for idx in range(1, len(arr))]
            score = _mean(residual)
            if score < best_score:
                best_score = score
                best = (omega, alpha, beta, h[-1])

    if best is None:
        arch = estimate_arch_1(arr)
        return GarchModelResult(
            omega=arch.omega,
            alpha=arch.alpha,
            beta=0.0,
            unconditional_variance=arch.unconditional_variance,
            filtered_variance=arch.next_variance,
            next_variance=arch.next_variance,
        )

    omega, alpha, beta, filtered_variance = best
    next_variance = max(omega + alpha * squared[-1] + beta * filtered_variance, _EPSILON)
    unconditional = max(omega / max(1.0 - alpha - beta, _EPSILON), _EPSILON)
    return GarchModelResult(
        omega=omega,
        alpha=alpha,
        beta=beta,
        unconditional_variance=unconditional,
        filtered_variance=filtered_variance,
        next_variance=next_variance,
    )


def annualize_volatility(
    volatility_per_step: float,
    bars_per_day: int = 390,
    trading_days_per_year: int = 252,
) -> float:
    steps_per_year = max(1, bars_per_day * trading_days_per_year)
    return max(float(volatility_per_step), 0.0) * math.sqrt(steps_per_year)
