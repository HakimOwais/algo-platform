"""
Cross-sectional momentum — rank assets by 12-1 month return, long top quantile.
Based on Jegadeesh & Titman (1993); confirmed on NSE equities in academic literature.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

_EPS = 1e-12


def cross_sectional_momentum(
    price_history: Mapping[str, Sequence[float]],
    formation_bars: int = 252,
    skip_bars: int = 21,
    top_fraction: float = 0.4,
) -> dict[str, float]:
    """
    Compute cross-sectional momentum allocation weights.

    formation_bars: lookback for the momentum signal (≈ 12 months of daily bars)
    skip_bars:      skip the most recent bars to avoid short-term reversal (≈ 1 month)
    top_fraction:   fraction of the universe to go long (default: top 40%)

    Returns dict of symbol → weight (only long positions; 0 means no position).
    Weights sum to 1.0 across the selected symbols.
    """
    scores: dict[str, float] = {}
    for symbol, prices in price_history.items():
        arr = [float(p) for p in prices if math.isfinite(float(p)) and float(p) > 0]
        min_len = formation_bars + skip_bars + 1
        if len(arr) < min_len:
            continue
        p_start = arr[-(formation_bars + skip_bars)]
        p_end = arr[-(skip_bars + 1)]
        if p_start < _EPS:
            continue
        scores[symbol] = (p_end / p_start) - 1.0

    if not scores:
        return {}

    sorted_syms = sorted(scores, key=lambda s: scores[s], reverse=True)
    n = len(sorted_syms)
    top_count = max(1, round(n * top_fraction))
    top_syms = sorted_syms[:top_count]

    # Only go long symbols with positive momentum
    raw: dict[str, float] = {s: max(scores[s], 0.0) for s in top_syms}
    total = sum(raw.values())
    if total < _EPS:
        # All negative — equal weight the top selection
        equal = 1.0 / max(len(top_syms), 1)
        return {s: equal for s in top_syms}

    return {s: v / total for s, v in raw.items()}


def momentum_score(prices: Sequence[float], formation_bars: int = 252, skip_bars: int = 21) -> float | None:
    """Single-asset momentum score: 12-1 month return. Returns None if insufficient data."""
    arr = [float(p) for p in prices if math.isfinite(float(p)) and float(p) > 0]
    if len(arr) < formation_bars + skip_bars + 1:
        return None
    p_start = arr[-(formation_bars + skip_bars)]
    p_end = arr[-(skip_bars + 1)]
    if p_start < _EPS:
        return None
    return (p_end / p_start) - 1.0


def short_term_reversal_score(prices: Sequence[float], lookback: int = 5) -> float | None:
    """
    Short-term mean-reversion signal: negative recent return predicts positive forward return.
    Returns the negative of the recent return (higher = more oversold = buy signal).
    """
    arr = [float(p) for p in prices if math.isfinite(float(p)) and float(p) > 0]
    if len(arr) < lookback + 1:
        return None
    p_start = arr[-(lookback + 1)]
    p_end = arr[-1]
    if p_start < _EPS:
        return None
    recent_ret = (p_end / p_start) - 1.0
    return -recent_ret  # positive value = oversold = mean-reversion buy
