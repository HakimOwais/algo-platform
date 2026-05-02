"""Technical signal computation — pure Python/numpy, no external TA libraries."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_EPS = 1e-12


def _clean(values: Sequence[float]) -> list[float]:
    return [float(v) for v in values if math.isfinite(float(v))]


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    arr = _clean(closes)
    if len(arr) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(arr)):
        diff = arr[i] - arr[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    # Wilder smoothing
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, lo in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + lo) / period
    if avg_loss < _EPS:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@dataclass(frozen=True)
class MACDResult:
    macd: float
    signal: float
    histogram: float


def macd(
    closes: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> MACDResult | None:
    arr = _clean(closes)
    if len(arr) < slow + signal_period:
        return None

    def _ema(data: list[float], n: int) -> list[float]:
        k = 2.0 / (n + 1)
        out = [data[0]]
        for v in data[1:]:
            out.append(v * k + out[-1] * (1.0 - k))
        return out

    fast_ema = _ema(arr, fast)
    slow_ema = _ema(arr, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = _ema(macd_line, signal_period)
    hist = macd_line[-1] - signal_line[-1]
    return MACDResult(macd=macd_line[-1], signal=signal_line[-1], histogram=hist)


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    h = _clean(highs)
    lo = _clean(lows)
    c = _clean(closes)
    n = min(len(h), len(lo), len(c))
    if n < period + 1:
        return None
    h, lo, c = h[-n:], lo[-n:], c[-n:]
    true_ranges: list[float] = []
    for i in range(1, n):
        tr = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        true_ranges.append(tr)
    atr_val = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


@dataclass(frozen=True)
class BollingerBands:
    upper: float
    middle: float
    lower: float
    pct_b: float  # 0 = at lower band, 1 = at upper band


def bollinger_bands(
    closes: Sequence[float],
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerBands | None:
    arr = _clean(closes)
    if len(arr) < period:
        return None
    window = arr[-period:]
    mean = sum(window) / period
    variance = sum((v - mean) ** 2 for v in window) / period
    std = math.sqrt(max(variance, _EPS))
    upper = mean + num_std * std
    lower = mean - num_std * std
    band_width = upper - lower
    pct_b = (arr[-1] - lower) / max(band_width, _EPS)
    return BollingerBands(upper=upper, middle=mean, lower=lower, pct_b=pct_b)


@dataclass(frozen=True)
class ADXResult:
    adx: float
    plus_di: float
    minus_di: float


def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> ADXResult | None:
    h = _clean(highs)
    lo = _clean(lows)
    c = _clean(closes)
    n = min(len(h), len(lo), len(c))
    if n < period * 2 + 1:
        return None
    h, lo, c = h[-n:], lo[-n:], c[-n:]

    plus_dm_vals: list[float] = []
    minus_dm_vals: list[float] = []
    tr_vals: list[float] = []
    for i in range(1, n):
        up = h[i] - h[i - 1]
        down = lo[i - 1] - lo[i]
        plus_dm_vals.append(up if up > down and up > 0 else 0.0)
        minus_dm_vals.append(down if down > up and down > 0 else 0.0)
        tr = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        tr_vals.append(tr)

    def _wilder(data: list[float], n: int) -> list[float]:
        result = [sum(data[:n])]
        for v in data[n:]:
            result.append(result[-1] - result[-1] / n + v)
        return result

    atr_smooth = _wilder(tr_vals, period)
    plus_smooth = _wilder(plus_dm_vals, period)
    minus_smooth = _wilder(minus_dm_vals, period)

    dx_list: list[float] = []
    for a, p, m in zip(atr_smooth, plus_smooth, minus_smooth):
        p_di = 100.0 * p / max(a, _EPS)
        m_di = 100.0 * m / max(a, _EPS)
        denom = p_di + m_di
        dx_list.append(100.0 * abs(p_di - m_di) / max(denom, _EPS))

    if len(dx_list) < period:
        return None

    adx_val = sum(dx_list[:period]) / period
    for dx_val in dx_list[period:]:
        adx_val = (adx_val * (period - 1) + dx_val) / period

    plus_di_final = 100.0 * plus_smooth[-1] / max(atr_smooth[-1], _EPS)
    minus_di_final = 100.0 * minus_smooth[-1] / max(atr_smooth[-1], _EPS)
    return ADXResult(adx=adx_val, plus_di=plus_di_final, minus_di=minus_di_final)


def volume_zscore(volumes: Sequence[float], period: int = 20) -> float | None:
    arr = _clean(volumes)
    if len(arr) < period + 1:
        return None
    window = arr[-period - 1 : -1]
    mean = sum(window) / period
    variance = sum((v - mean) ** 2 for v in window) / max(period - 1, 1)
    std = math.sqrt(max(variance, _EPS))
    return (arr[-1] - mean) / std


def rate_of_change(closes: Sequence[float], period: int = 10) -> float | None:
    arr = _clean(closes)
    if len(arr) < period + 1:
        return None
    prev = arr[-(period + 1)]
    return (arr[-1] - prev) / max(abs(prev), _EPS)


def bar_range_ratio(high: float, low: float, close: float) -> float:
    """Where the close sits within the bar: 0 = at low, 1 = at high."""
    spread = high - low
    if spread < _EPS:
        return 0.5
    return max(0.0, min(1.0, (close - low) / spread))


@dataclass(frozen=True)
class SignalBundle:
    rsi_14: float | None
    macd_hist: float | None
    macd_signal_cross: float | None
    bb_pct_b: float | None
    atr_ratio: float | None
    adx_14: float | None
    plus_di: float | None
    minus_di: float | None
    volume_z: float | None
    roc_10: float | None
    close_position: float


def compute_signal_bundle(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
) -> SignalBundle:
    rsi_val = rsi(closes)
    macd_r = macd(closes)
    bb = bollinger_bands(closes)
    atr_val = atr(highs, lows, closes)
    adx_r = adx(highs, lows, closes)
    vol_z = volume_zscore(volumes)
    roc_val = rate_of_change(closes)

    close_pos = (
        bar_range_ratio(highs[-1], lows[-1], closes[-1])
        if (highs and lows and closes)
        else 0.5
    )
    atr_ratio = (
        atr_val / max(closes[-1], _EPS)
        if (atr_val is not None and closes and closes[-1] > _EPS)
        else None
    )
    macd_cross = (macd_r.macd - macd_r.signal) if macd_r is not None else None

    return SignalBundle(
        rsi_14=rsi_val,
        macd_hist=macd_r.histogram if macd_r else None,
        macd_signal_cross=macd_cross,
        bb_pct_b=bb.pct_b if bb else None,
        atr_ratio=atr_ratio,
        adx_14=adx_r.adx if adx_r else None,
        plus_di=adx_r.plus_di if adx_r else None,
        minus_di=adx_r.minus_di if adx_r else None,
        volume_z=vol_z,
        roc_10=roc_val,
        close_position=close_pos,
    )
