"""
Kalman Filter for dynamic hedge ratio estimation in pairs trading.

The static OLS hedge ratio in pairs_trading.py breaks down over time as the
relationship between two assets drifts. This Kalman Filter treats the hedge
ratio as a latent state that evolves as a random walk — it adapts continuously
as the cointegration relationship changes.

State vector: θ = [β (hedge ratio), α (intercept)]
Observation:  y_t = β_t · x_t + α_t + ε_t
Transition:   θ_t = θ_{t-1} + w_t   (random walk in state space)
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_EPS = 1e-12


@dataclass(frozen=True)
class KalmanPairsResult:
    hedge_ratio: float
    intercept: float
    spread: float
    spread_mean: float
    spread_std: float
    zscore: float
    signal: str       # LONG_SPREAD | SHORT_SPREAD | EXIT | HOLD
    kalman_gain: float


def kalman_hedge_ratio(
    x_prices: Sequence[float],
    y_prices: Sequence[float],
    delta: float = 1e-4,
    measurement_noise: float = 1e-2,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
) -> KalmanPairsResult | None:
    """
    Estimate a time-varying hedge ratio using a Kalman Filter.

    delta:             process noise variance — controls how fast β can change.
                       Larger → faster adaptation but noisier estimates.
    measurement_noise: observation noise variance R.
    entry_z:           z-score threshold to enter a spread trade.
    exit_z:            z-score threshold to exit.
    """
    x = [float(v) for v in x_prices if math.isfinite(float(v))]
    y = [float(v) for v in y_prices if math.isfinite(float(v))]
    n = min(len(x), len(y))
    if n < 10:
        return None
    x, y = x[-n:], y[-n:]

    # State: θ = [β, α]
    theta = [1.0, 0.0]

    # State covariance P (2×2)
    P = [[1.0, 0.0], [0.0, 1.0]]

    # Process noise Q = delta * I
    Q = delta

    R = measurement_noise

    spreads: list[float] = []
    last_gain = 0.0

    for t in range(n):
        H = [x[t], 1.0]  # observation vector

        # Predict: P_pred = P + Q*I
        P[0][0] += Q
        P[1][1] += Q

        # Innovation
        y_pred = H[0] * theta[0] + H[1] * theta[1]
        innov = y[t] - y_pred

        # Innovation covariance: S = H P H' + R
        HP0 = H[0] * P[0][0] + H[1] * P[1][0]
        HP1 = H[0] * P[0][1] + H[1] * P[1][1]
        S = HP0 * H[0] + HP1 * H[1] + R
        if abs(S) < _EPS:
            spreads.append(y[t] - theta[0] * x[t] - theta[1])
            continue

        # Kalman gain: K = P H' / S  (2×1)
        K0 = (P[0][0] * H[0] + P[0][1] * H[1]) / S
        K1 = (P[1][0] * H[0] + P[1][1] * H[1]) / S
        last_gain = K0

        # Update state
        theta[0] += K0 * innov
        theta[1] += K1 * innov

        # Update covariance: P = (I - K H) P
        KH00 = K0 * H[0];  KH01 = K0 * H[1]
        KH10 = K1 * H[0];  KH11 = K1 * H[1]
        p00 = (1.0 - KH00) * P[0][0] - KH01 * P[1][0]
        p01 = (1.0 - KH00) * P[0][1] - KH01 * P[1][1]
        p10 = -KH10 * P[0][0] + (1.0 - KH11) * P[1][0]
        p11 = -KH10 * P[0][1] + (1.0 - KH11) * P[1][1]
        P = [[p00, p01], [p10, p11]]

        spread = y[t] - theta[0] * x[t] - theta[1]
        spreads.append(spread)

    if len(spreads) < 10:
        return None

    spread_mean = sum(spreads) / len(spreads)
    spread_var = sum((s - spread_mean) ** 2 for s in spreads) / max(len(spreads) - 1, 1)
    spread_std = math.sqrt(max(spread_var, _EPS))
    current_spread = spreads[-1]
    zscore = (current_spread - spread_mean) / spread_std

    if zscore >= entry_z:
        signal = "SHORT_SPREAD"
    elif zscore <= -entry_z:
        signal = "LONG_SPREAD"
    elif abs(zscore) <= exit_z:
        signal = "EXIT"
    else:
        signal = "HOLD"

    return KalmanPairsResult(
        hedge_ratio=theta[0],
        intercept=theta[1],
        spread=current_spread,
        spread_mean=spread_mean,
        spread_std=spread_std,
        zscore=zscore,
        signal=signal,
        kalman_gain=last_gain,
    )
