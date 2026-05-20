"""Shared numeric primitives for all quant modules.

Single source of truth for clean/mean/variance/covariance/quantile/safe_div.
Replaces five near-identical copies scattered across volatility_models,
monte_carlo, pairs_trading, portfolio_models, and har_rv.

Rules:
- stdlib only — no numpy, no pandas — so this is importable in any context.
- No side-effects, no logging, no IO.
- All inputs are plain Python sequences; outputs are plain Python scalars or lists.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

EPS: float = 1e-12


# ── cleaning ──────────────────────────────────────────────────────────────


def clean(values: Sequence[float]) -> list[float]:
    """Return a new list with only finite float values."""
    return [float(v) for v in values if math.isfinite(float(v))]


# ── basic statistics ───────────────────────────────────────────────────────


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def variance(values: Sequence[float], ddof: int = 1, floor: float = EPS) -> float:
    n = len(values)
    if n <= ddof:
        return floor
    mu = mean(values)
    return max(sum((v - mu) ** 2 for v in values) / (n - ddof), floor)


def covariance(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx, my = mean(x), mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / len(x)


# ── order statistics ───────────────────────────────────────────────────────


def quantile(values: Sequence[float], q: float) -> float:
    """Empirical quantile via nearest-rank. q in [0, 1]."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(q * (len(ordered) - 1))))
    return ordered[idx]


# ── arithmetic helpers ─────────────────────────────────────────────────────


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if abs(b) > EPS else default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
