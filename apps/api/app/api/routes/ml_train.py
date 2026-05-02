"""
ML training and inference API endpoints.

POST /ml/train           — build dataset from in-memory price history and train LightGBM
GET  /ml/status          — model status (trained / not trained, AUC, features)
POST /ml/predict/{symbol} — get current ML signal for a symbol
DELETE /ml/model         — delete the trained model file
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.ml.model import get_classifier
from app.quant.features import FeatureVector, build_feature_vector, build_training_dataset

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ml", tags=["ml"])


class TrainRequest(BaseModel):
    symbols: list[str] | None = Field(None, description="Symbols to use; None = all configured symbols")
    forward_bars: int = Field(5, ge=1, le=50, description="Bars ahead to define the label")
    lookback: int = Field(256, ge=60, le=1000, description="Max bars of history to use per symbol")
    threshold: float = Field(0.55, ge=0.5, le=0.95, description="Probability threshold for directional signal")
    n_estimators: int = Field(300, ge=50, le=2000)


class TrainResponse(BaseModel):
    status: str
    n_samples: int = 0
    n_features: int = 0
    mean_cv_auc: float = 0.0
    threshold: float = 0.55
    top_features: dict[str, float] = {}
    message: str = ""


class ModelStatus(BaseModel):
    is_trained: bool
    n_features: int
    threshold: float
    model_path: str


class PredictResponse(BaseModel):
    symbol: str
    direction: int          # +1 bullish, -1 bearish, 0 neutral
    bull_prob: float
    confidence: float
    features_used: int
    model_trained: bool


@router.post("/train", response_model=TrainResponse)
async def train_model(
    req: TrainRequest,
    container: ServiceContainer = Depends(get_container),
) -> TrainResponse:
    """
    Build a supervised training dataset from in-memory price history
    and fit a LightGBM directional classifier.

    The label is 1 if close[t + forward_bars] > close[t], else 0.
    Walk-forward time-series cross-validation is used to prevent look-ahead bias.
    Returns mean AUC across CV folds — aim for > 0.52 to have any signal.
    """
    symbols = [s.upper() for s in req.symbols] if req.symbols else container.settings.symbols
    all_features: list[list[float]] = []
    all_labels: list[int] = []

    for sym in symbols:
        closes = container.market_data_service.get_recent_closes(sym, lookback=req.lookback)
        if len(closes) < 60:
            continue
        # Use closes as proxy for H/L/V when not separately stored
        feats, labels = build_training_dataset(
            closes=closes,
            highs=closes,
            lows=closes,
            volumes=[1.0] * len(closes),
            forward_bars=req.forward_bars,
            lookback=30,
        )
        all_features.extend(feats)
        all_labels.extend(labels)

    if len(all_features) < 100:
        return TrainResponse(
            status="error",
            message=f"Not enough data: {len(all_features)} samples (need ≥ 100). "
                    "Let the market simulator run longer to accumulate more bars.",
        )

    clf = get_classifier()
    result = clf.train(
        features=all_features,
        labels=all_labels,
        feature_names=FeatureVector.feature_names(),
        threshold=req.threshold,
        n_estimators=req.n_estimators,
    )

    if "error" in result:
        return TrainResponse(status="error", message=result["error"])

    return TrainResponse(
        status="ok",
        n_samples=result.get("n_samples", 0),
        n_features=result.get("n_features", 0),
        mean_cv_auc=result.get("mean_cv_auc", 0.0),
        threshold=result.get("threshold", req.threshold),
        top_features=result.get("top_features", {}),
        message=(
            "Model trained successfully. "
            f"CV AUC = {result.get('mean_cv_auc', 0):.4f}. "
            "AUC > 0.52 indicates predictive signal. "
            "Enable use_ml_signal=true in strategy params to activate."
        ),
    )


@router.get("/status", response_model=ModelStatus)
async def model_status() -> ModelStatus:
    """Return the current state of the trained ML model."""
    import os  # noqa: PLC0415
    from app.ml.model import _MODEL_PATH  # noqa: PLC0415
    clf = get_classifier()
    return ModelStatus(
        is_trained=clf.is_trained,
        n_features=clf._n_features,
        threshold=clf._threshold,
        model_path=_MODEL_PATH if os.path.exists(_MODEL_PATH) else "(not saved)",
    )


@router.post("/predict/{symbol}", response_model=PredictResponse)
async def predict_signal(
    symbol: str,
    container: ServiceContainer = Depends(get_container),
) -> PredictResponse:
    """Return the current ML directional signal for a symbol."""
    from datetime import datetime, timezone  # noqa: PLC0415
    sym = symbol.upper()
    clf = get_classifier()

    closes = container.market_data_service.get_recent_closes(sym, lookback=256)
    if len(closes) < 30:
        raise HTTPException(status_code=400, detail=f"Insufficient history for {sym}")

    now = datetime.now(timezone.utc)
    fv = build_feature_vector(
        closes=closes,
        highs=closes,
        lows=closes,
        volumes=[1.0] * len(closes),
        timestamp_hour=now.hour,
        timestamp_minute=now.minute,
        timestamp_weekday=now.weekday(),
    )

    if fv is None:
        raise HTTPException(status_code=400, detail="Could not build feature vector")

    sig = clf.predict(fv.to_list())
    return PredictResponse(
        symbol=sym,
        direction=sig.direction,
        bull_prob=sig.bull_prob,
        confidence=sig.confidence,
        features_used=sig.features_used,
        model_trained=clf.is_trained,
    )


@router.delete("/model")
async def delete_model() -> dict:
    """Delete the persisted model file and reset the in-memory classifier."""
    clf = get_classifier()
    clf.delete_model()
    return {"status": "ok", "message": "Model deleted. Retrain via POST /ml/train"}
