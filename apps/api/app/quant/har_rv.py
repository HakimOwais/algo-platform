"""HAR-RV (Corsi 2009) and EGARCH(1,1) volatility models — pure Python/numpy."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_EPS = 1e-12


@dataclass(frozen=True)
class HARRVResult:
    alpha: float
    beta_daily: float
    beta_weekly: float
    beta_monthly: float
    forecast_variance: float   # next-step realized variance
    forecast_vol_annual: float # annualised forecast volatility


@dataclass(frozen=True)
class EGARCHResult:
    omega: float
    alpha: float   # magnitude effect
    gamma: float   # asymmetry (leverage): γ < 0 → down-moves amplify vol
    beta: float    # persistence
    next_variance: float
    forecast_vol_annual: float


def _clean(values: Sequence[float]) -> list[float]:
    return [float(v) for v in values if math.isfinite(float(v))]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ols_4(X: list[tuple[float, float, float, float]], y: list[float]) -> tuple[float, float, float, float]:
    """OLS for a 4-column design matrix [1, x1, x2, x3] via normal equations."""
    n = len(y)
    if n < 5:
        return 0.0, 0.33, 0.33, 0.33

    # Accumulate X'X (4×4) and X'y (4×1)
    XtX = [[0.0] * 4 for _ in range(4)]
    Xty = [0.0] * 4
    for i in range(n):
        row = (1.0, X[i][0], X[i][1], X[i][2])
        for a in range(4):
            Xty[a] += row[a] * y[i]
            for b in range(4):
                XtX[a][b] += row[a] * row[b]

    # Gaussian elimination with partial pivoting
    aug = [XtX[r][:] + [Xty[r]] for r in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        if abs(aug[col][col]) < _EPS:
            continue
        for row in range(4):
            if row == col:
                continue
            factor = aug[row][col] / aug[col][col]
            for j in range(5):
                aug[row][j] -= factor * aug[col][j]

    coeffs = [aug[i][4] / aug[i][i] if abs(aug[i][i]) > _EPS else 0.0 for i in range(4)]
    return coeffs[0], coeffs[1], coeffs[2], coeffs[3]


def compute_daily_rv(returns: Sequence[float]) -> list[float]:
    """Squared returns as a proxy for daily realized variance."""
    arr = _clean(returns)
    return [r * r for r in arr]


def estimate_har_rv(
    daily_rv: Sequence[float],
    bars_per_day: int = 390,
    trading_days: int = 252,
) -> HARRVResult | None:
    """
    Fit HAR-RV: RV_t = α + β_d·RV_{t-1} + β_w·RV^w_{t-1} + β_m·RV^m_{t-1}
    Requires ≥ 30 daily RV observations.
    """
    rv = _clean(daily_rv)
    if len(rv) < 30:
        return None

    design: list[tuple[float, float, float]] = []
    targets: list[float] = []
    for t in range(22, len(rv)):
        rv_d = rv[t - 1]
        rv_w = _mean(rv[max(0, t - 5) : t])
        rv_m = _mean(rv[max(0, t - 22) : t])
        design.append((rv_d, rv_w, rv_m))
        targets.append(rv[t])

    if len(targets) < 5:
        return None

    alpha, b_d, b_w, b_m = _ols_4(design, targets)

    # Forecast
    rv_d = rv[-1]
    rv_w = _mean(rv[-5:])
    rv_m = _mean(rv[-22:])
    forecast_var = max(alpha + b_d * rv_d + b_w * rv_w + b_m * rv_m, _EPS)

    steps_per_year = max(bars_per_day * trading_days, 1)
    forecast_vol = math.sqrt(forecast_var) * math.sqrt(steps_per_year)

    return HARRVResult(
        alpha=alpha,
        beta_daily=b_d,
        beta_weekly=b_w,
        beta_monthly=b_m,
        forecast_variance=forecast_var,
        forecast_vol_annual=forecast_vol,
    )


def estimate_egarch(
    returns: Sequence[float],
    bars_per_day: int = 390,
    trading_days: int = 252,
) -> EGARCHResult:
    """
    EGARCH(1,1): ln h_t = ω + α(|z_{t-1}| − E|z|) + γ z_{t-1} + β ln h_{t-1}
    γ < 0 captures the leverage effect (bad news increases vol more than good news).
    Fitted via grid search minimising MSE on log-squared-return proxy.
    """
    arr = _clean(returns)
    steps_per_year = max(bars_per_day * trading_days, 1)

    if len(arr) < 10:
        sample_var = sum(r * r for r in arr) / max(len(arr), 1) if arr else _EPS
        return EGARCHResult(
            omega=math.log(max(sample_var, _EPS)),
            alpha=0.10, gamma=-0.05, beta=0.85,
            next_variance=sample_var,
            forecast_vol_annual=math.sqrt(sample_var) * math.sqrt(steps_per_year),
        )

    E_abs_z = math.sqrt(2.0 / math.pi)  # E[|z|] for N(0,1)
    sample_var = max(sum(r * r for r in arr) / len(arr), _EPS)
    log_sv = math.log(sample_var)

    alpha_grid = [0.05, 0.10, 0.15, 0.20]
    gamma_grid = [-0.15, -0.08, -0.02, 0.02]
    beta_grid  = [0.80, 0.88, 0.93, 0.97]

    best_score = math.inf
    best = (0.10, -0.05, 0.90)

    for a in alpha_grid:
        for g in gamma_grid:
            for b in beta_grid:
                if abs(b) >= 1.0:
                    continue
                omega = log_sv * (1.0 - b)
                log_h = log_sv
                score = 0.0
                valid = True
                for i in range(1, len(arr)):
                    z = arr[i - 1] / math.sqrt(max(math.exp(log_h), _EPS))
                    log_h = omega + a * (abs(z) - E_abs_z) + g * z + b * log_h
                    if not math.isfinite(log_h):
                        valid = False
                        break
                    log_r2 = math.log(max(arr[i] ** 2, _EPS))
                    score += (log_r2 - log_h) ** 2
                if valid:
                    score /= max(len(arr) - 1, 1)
                    if score < best_score:
                        best_score = score
                        best = (a, g, b)

    alpha, gamma, beta = best
    omega = log_sv * (1.0 - beta)

    # Final filter pass
    log_h = log_sv
    for r in arr:
        z = r / math.sqrt(max(math.exp(log_h), _EPS))
        log_h = omega + alpha * (abs(z) - E_abs_z) + gamma * z + beta * log_h

    next_var = max(math.exp(log_h), _EPS)
    return EGARCHResult(
        omega=omega,
        alpha=alpha,
        gamma=gamma,
        beta=beta,
        next_variance=next_var,
        forecast_vol_annual=math.sqrt(next_var) * math.sqrt(steps_per_year),
    )
