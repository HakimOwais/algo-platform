from collections.abc import Sequence
from dataclasses import dataclass
import math

from app.quant._numeric import EPS, clean, mean, variance, covariance


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


def estimate_arch_1(returns: Sequence[float]) -> ArchModelResult:
    arr = clean(returns)
    sample_var = variance(arr)

    if len(arr) < 3:
        alpha = 0.1
        omega = sample_var * (1.0 - alpha)
        return ArchModelResult(
            omega=omega,
            alpha=alpha,
            unconditional_variance=sample_var,
            next_variance=sample_var,
        )

    x = [v * v for v in arr[:-1]]
    y = [v * v for v in arr[1:]]
    x_var = variance(x, ddof=0)
    alpha = covariance(x, y) / x_var if x_var > EPS else 0.1
    alpha = min(max(alpha, 0.0), 0.98)
    omega = max(mean(y) - (alpha * mean(x)), EPS)
    unconditional = max(omega / max(1.0 - alpha, EPS), EPS)
    next_variance = max(omega + alpha * (arr[-1] ** 2), EPS)
    return ArchModelResult(
        omega=omega,
        alpha=alpha,
        unconditional_variance=unconditional,
        next_variance=next_variance,
    )


def estimate_garch_1_1(returns: Sequence[float]) -> GarchModelResult:
    arr = clean(returns)
    sample_var = variance(arr)

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
    squared = [v * v for v in arr]

    best_score = math.inf
    best: tuple[float, float, float, float] | None = None
    for alpha in alpha_grid:
        for beta in beta_grid:
            if alpha + beta >= 0.995:
                continue
            omega = max(sample_var * (1.0 - alpha - beta), EPS)
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
            score = mean(residual)
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
    next_variance = max(omega + alpha * squared[-1] + beta * filtered_variance, EPS)
    unconditional = max(omega / max(1.0 - alpha - beta, EPS), EPS)
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
