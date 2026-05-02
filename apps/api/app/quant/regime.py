"""
2-state Gaussian Hidden Markov Model for market regime detection.

State 0 = low-volatility trending regime  → trend-following signals have edge
State 1 = high-volatility choppy regime   → reduce position sizes, prefer mean-reversion

Implemented in pure Python (no hmmlearn dependency).
Uses Baum-Welch EM for parameter estimation and forward-algorithm for inference.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_EPS = 1e-12
_K = 2  # number of hidden states


@dataclass(frozen=True)
class RegimeResult:
    current_regime: int      # 0 = trending, 1 = choppy/high-vol
    trending_prob: float     # P(state=0 | observations)
    regime_label: str        # "TRENDING" or "CHOPPY"
    position_scalar: float   # multiply base position size by this


def _normal_pdf(x: float, mu: float, sigma: float) -> float:
    if sigma < _EPS:
        return 1.0 if abs(x - mu) < _EPS else _EPS
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * math.sqrt(2.0 * math.pi))


class _GaussianHMM:
    """2-state Gaussian HMM with Baum-Welch EM."""

    def __init__(self) -> None:
        # Transition matrix rows: from-state, cols: to-state
        self.trans = [[0.95, 0.05], [0.10, 0.90]]
        self.means = [0.0, 0.0]
        self.stds = [0.008, 0.020]
        self.init = [0.6, 0.4]
        self._fitted = False

    # ------------------------------------------------------------------
    def fit(self, obs: list[float], n_iter: int = 25) -> None:
        T = len(obs)
        if T < 20:
            return

        # Initialise means and stds from data
        sorted_abs = sorted(abs(r) for r in obs)
        mid = sorted_abs[len(sorted_abs) // 2]
        self.stds = [max(mid * 0.6, _EPS), max(mid * 1.8, _EPS)]
        self.means = [0.0, 0.0]

        for _ in range(n_iter):
            # --- Forward ---
            alpha = [[0.0] * _K for _ in range(T)]
            scale = [0.0] * T
            for k in range(_K):
                alpha[0][k] = self.init[k] * _normal_pdf(obs[0], self.means[k], self.stds[k])
            scale[0] = sum(alpha[0]) or _EPS
            alpha[0] = [v / scale[0] for v in alpha[0]]

            for t in range(1, T):
                for j in range(_K):
                    alpha[t][j] = (
                        _normal_pdf(obs[t], self.means[j], self.stds[j])
                        * sum(alpha[t - 1][i] * self.trans[i][j] for i in range(_K))
                    )
                scale[t] = sum(alpha[t]) or _EPS
                alpha[t] = [v / scale[t] for v in alpha[t]]

            # --- Backward ---
            beta = [[1.0] * _K for _ in range(T)]
            for t in range(T - 2, -1, -1):
                for i in range(_K):
                    beta[t][i] = sum(
                        self.trans[i][j]
                        * _normal_pdf(obs[t + 1], self.means[j], self.stds[j])
                        * beta[t + 1][j]
                        for j in range(_K)
                    )
                total = sum(beta[t]) or _EPS
                beta[t] = [v / total for v in beta[t]]

            # --- Gamma (state occupancy) ---
            gamma = [[0.0] * _K for _ in range(T)]
            for t in range(T):
                total = sum(alpha[t][k] * beta[t][k] for k in range(_K)) or _EPS
                for k in range(_K):
                    gamma[t][k] = alpha[t][k] * beta[t][k] / total

            # --- Xi (transition occupancy) ---
            xi: list[list[list[float]]] = [
                [[0.0] * _K for _ in range(_K)] for _ in range(T - 1)
            ]
            for t in range(T - 1):
                total = 0.0
                for i in range(_K):
                    for j in range(_K):
                        xi[t][i][j] = (
                            alpha[t][i]
                            * self.trans[i][j]
                            * _normal_pdf(obs[t + 1], self.means[j], self.stds[j])
                            * beta[t + 1][j]
                        )
                        total += xi[t][i][j]
                if total > _EPS:
                    for i in range(_K):
                        for j in range(_K):
                            xi[t][i][j] /= total

            # --- M-step: update parameters ---
            self.init = [gamma[0][k] for k in range(_K)]

            for i in range(_K):
                denom = sum(gamma[t][i] for t in range(T - 1)) or _EPS
                for j in range(_K):
                    self.trans[i][j] = max(
                        sum(xi[t][i][j] for t in range(T - 1)), _EPS
                    ) / denom
                row_sum = sum(self.trans[i]) or _EPS
                self.trans[i] = [v / row_sum for v in self.trans[i]]

            for k in range(_K):
                denom = sum(gamma[t][k] for t in range(T)) or _EPS
                self.means[k] = sum(gamma[t][k] * obs[t] for t in range(T)) / denom
                self.stds[k] = math.sqrt(
                    max(
                        sum(gamma[t][k] * (obs[t] - self.means[k]) ** 2 for t in range(T))
                        / denom,
                        _EPS,
                    )
                )

        # Ensure state 0 is always the low-vol state
        if self.stds[0] > self.stds[1]:
            self.means = [self.means[1], self.means[0]]
            self.stds = [self.stds[1], self.stds[0]]
            self.trans = [
                [self.trans[1][1], self.trans[1][0]],
                [self.trans[0][1], self.trans[0][0]],
            ]
            self.init = [self.init[1], self.init[0]]

        self._fitted = True

    # ------------------------------------------------------------------
    def predict_last(self, obs: list[float]) -> RegimeResult:
        """Run forward algorithm and return regime probabilities for the last observation."""
        if not obs or not self._fitted:
            return RegimeResult(0, 0.6, "TRENDING", 1.0)

        probs = [
            self.init[k] * _normal_pdf(obs[0], self.means[k], self.stds[k])
            for k in range(_K)
        ]
        total = sum(probs) or _EPS
        probs = [p / total for p in probs]

        for t in range(1, len(obs)):
            new_probs = [0.0] * _K
            for j in range(_K):
                emit = _normal_pdf(obs[t], self.means[j], self.stds[j])
                new_probs[j] = emit * sum(probs[i] * self.trans[i][j] for i in range(_K))
            total = sum(new_probs) or _EPS
            probs = [p / total for p in new_probs]

        current = 0 if probs[0] >= probs[1] else 1
        trending_prob = probs[0]
        label = "TRENDING" if current == 0 else "CHOPPY"
        # Position scalar: full size in trending regime, half in choppy
        scalar = 1.0 if current == 0 else 0.5
        return RegimeResult(current, trending_prob, label, scalar)


def detect_regime(
    returns: Sequence[float],
    fit_window: int = 120,
    n_iter: int = 20,
) -> RegimeResult:
    """
    Detect the current market regime from a return series.

    Fits a 2-state Gaussian HMM on the most recent `fit_window` returns
    and returns the regime for the final observation.
    Returns TRENDING with scalar=1.0 as a safe default when data is insufficient.
    """
    arr = [float(r) for r in returns if math.isfinite(float(r))]
    if len(arr) < 30:
        return RegimeResult(0, 0.6, "TRENDING", 1.0)

    fit_data = arr[-min(fit_window, len(arr)):]
    model = _GaussianHMM()
    model.fit(fit_data, n_iter=n_iter)
    return model.predict_last(fit_data)
