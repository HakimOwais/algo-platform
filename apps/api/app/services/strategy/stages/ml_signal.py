"""Stage 7: ML signal confirmation / veto.

The LGBM classifier confirms or vetoes the EMA signal.
A veto fires only when the model is trained AND its predicted direction
is non-neutral AND directly opposes the EMA crossover direction.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.quant.features import build_feature_vector
from app.services.strategy.context import CycleContext, SignalContext


def apply_ml_signal(
    cycle: CycleContext,
    ctx: SignalContext,
    market_data,  # MarketDataPort — injected by pipeline, not imported directly
) -> None:
    if not cycle.params.get("use_ml_signal", True):
        return

    from app.ml.model import get_classifier  # avoid module-level circular import
    clf = get_classifier()
    if not clf.is_trained:
        return

    closes = ctx.closes
    lookback = len(closes)

    # Prefer richer OHLCV if the adapter exposes it
    highs = lows = closes
    volumes: list[float] = [1.0] * len(closes)
    if hasattr(market_data, "get_recent_ohlcv"):
        ohlcv = market_data.get_recent_ohlcv(ctx.symbol, lookback)
        highs   = ohlcv.get("highs", highs)
        lows    = ohlcv.get("lows", lows)
        volumes = ohlcv.get("volumes", volumes)

    now = datetime.now(timezone.utc)
    fv = build_feature_vector(
        closes=closes, highs=highs, lows=lows, volumes=volumes,
        timestamp_hour=now.hour,
        timestamp_minute=now.minute,
        timestamp_weekday=now.weekday(),
    )
    if fv is None:
        return

    ml_sig = clf.predict(fv.to_list())
    ctx.diagnostics["ml"] = {
        "direction": ml_sig.direction,
        "bull_prob": round(ml_sig.bull_prob, 4),
        "confidence": round(ml_sig.confidence, 4),
    }

    if ml_sig.direction != 0 and ml_sig.direction != ctx.signal_state:
        ctx.ml_veto = True
