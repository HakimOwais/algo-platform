"""Feature engineering pipeline — produces a fixed-length numeric vector for the ML model."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from collections.abc import Sequence

from app.quant.returns import log_returns
from app.quant.signals import compute_signal_bundle

_EPS = 1e-12


def _safe(v: float | None, default: float = 0.0) -> float:
    if v is None:
        return default
    f = float(v)
    return f if math.isfinite(f) else default


@dataclass
class FeatureVector:
    # Multi-horizon returns
    ret_1: float
    ret_5: float
    ret_20: float
    # Realized variance proxies
    rv_5: float
    rv_20: float
    vol_ratio: float       # rv_5 / rv_20 — vol-of-vol regime proxy
    # Momentum / trend
    rsi_14: float          # normalised 0-1
    macd_hist: float
    macd_cross: float      # MACD - signal line
    roc_10: float
    # Mean-reversion
    bb_pct_b: float        # 0 = at lower band, 1 = at upper band
    # Volatility / risk
    atr_ratio: float       # ATR / close
    adx_14: float          # normalised 0-1
    plus_di: float         # normalised 0-1
    minus_di: float        # normalised 0-1
    di_diff: float         # plus_di - minus_di
    trend_strength: float  # adx * sign(di_diff) — positive = bullish trend
    # Microstructure
    volume_z: float
    bar_range: float       # (H - L) / C
    close_position: float  # where close sits within bar range
    # Calendar (all normalised 0-1)
    hour_of_day: float
    day_of_week: float
    minutes_from_open: float

    def to_list(self) -> list[float]:
        return [float(v) for v in asdict(self).values()]

    @classmethod
    def feature_names(cls) -> list[str]:
        return list(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]

    @classmethod
    def n_features(cls) -> int:
        return len(cls.__dataclass_fields__)  # type: ignore[attr-defined]


def build_feature_vector(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    timestamp_hour: int = 10,
    timestamp_minute: int = 15,
    timestamp_weekday: int = 0,  # 0 = Monday
) -> FeatureVector | None:
    """
    Build a normalised feature vector from recent OHLCV bars.
    Returns None if there is insufficient data (< 30 bars).
    """
    if len(closes) < 30:
        return None

    rets = log_returns(closes)
    if len(rets) < 20:
        return None

    # --- Return features ---
    ret_1 = _safe(rets[-1] if rets else None)
    ret_5 = sum(rets[-5:]) if len(rets) >= 5 else ret_1
    ret_20 = sum(rets[-20:]) if len(rets) >= 20 else ret_1

    # --- Realized variance (squared-return proxy) ---
    sq = [r * r for r in rets]
    rv_5 = sum(sq[-5:]) / 5 if len(sq) >= 5 else sq[-1] if sq else _EPS
    rv_20 = sum(sq[-20:]) / 20 if len(sq) >= 20 else rv_5
    vol_ratio = rv_5 / max(rv_20, _EPS)

    # --- Technical signals ---
    sb = compute_signal_bundle(closes, highs, lows, volumes)

    rsi_v      = _safe(sb.rsi_14, 50.0) / 100.0
    macd_h     = _safe(sb.macd_hist)
    macd_c     = _safe(sb.macd_signal_cross)
    bb_pb      = _safe(sb.bb_pct_b, 0.5)
    atr_r      = _safe(sb.atr_ratio, 0.01)
    adx_v      = _safe(sb.adx_14, 20.0) / 100.0
    plus_di    = _safe(sb.plus_di, 25.0) / 100.0
    minus_di   = _safe(sb.minus_di, 25.0) / 100.0
    di_diff    = plus_di - minus_di
    vol_z      = _safe(sb.volume_z)
    close_pos  = _safe(sb.close_position, 0.5)
    roc_v      = _safe(sb.roc_10)
    bar_rng    = (highs[-1] - lows[-1]) / max(closes[-1], _EPS) if closes else 0.01
    trend_str  = adx_v * (1.0 if di_diff >= 0 else -1.0)

    # --- Calendar features (normalised 0-1) ---
    # NSE opens 09:15, closes 15:30 → 375 trading minutes
    minutes_since_open = max(0, timestamp_hour * 60 + timestamp_minute - 555)
    norm_intraday = min(minutes_since_open / 375.0, 1.0)
    hour_norm = max(0.0, min(1.0, (timestamp_hour - 9) / 6.0))
    day_norm = timestamp_weekday / 4.0  # 0=Mon … 1=Fri

    return FeatureVector(
        ret_1=ret_1, ret_5=ret_5, ret_20=ret_20,
        rv_5=rv_5, rv_20=rv_20, vol_ratio=vol_ratio,
        rsi_14=rsi_v, macd_hist=macd_h, macd_cross=macd_c,
        roc_10=roc_v,
        bb_pct_b=bb_pb,
        atr_ratio=atr_r, adx_14=adx_v,
        plus_di=plus_di, minus_di=minus_di, di_diff=di_diff,
        trend_strength=trend_str,
        volume_z=vol_z, bar_range=bar_rng, close_position=close_pos,
        hour_of_day=hour_norm, day_of_week=day_norm,
        minutes_from_open=norm_intraday,
    )


def build_training_dataset(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    forward_bars: int = 5,
    lookback: int = 60,
) -> tuple[list[list[float]], list[int]]:
    """
    Build a supervised dataset for the ML classifier.
    Label = 1 if close[t + forward_bars] > close[t], else 0.
    Uses point-in-time features (no look-ahead).
    """
    n = min(len(closes), len(highs), len(lows), len(volumes))
    features: list[list[float]] = []
    labels: list[int] = []

    for t in range(lookback, n - forward_bars):
        fv = build_feature_vector(
            closes=closes[: t + 1],
            highs=highs[: t + 1],
            lows=lows[: t + 1],
            volumes=volumes[: t + 1],
        )
        if fv is None:
            continue
        label = 1 if closes[t + forward_bars] > closes[t] else 0
        features.append(fv.to_list())
        labels.append(label)

    return features, labels
