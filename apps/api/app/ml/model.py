"""
LightGBM directional signal classifier.

Predicts whether close[t + forward_bars] > close[t] (label=1) or not (label=0).
Uses walk-forward cross-validation to prevent look-ahead bias.
Falls back gracefully to a neutral signal (direction=0) when not yet trained.
"""
from __future__ import annotations

import logging
import math
import os
import pickle
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Persisted model lives next to this file inside the container / venv
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "trained_model.pkl")


@dataclass(frozen=True)
class MLSignal:
    direction: int        # +1 bullish, -1 bearish, 0 neutral (below threshold)
    bull_prob: float      # P(price up over forward_bars)
    confidence: float     # |bull_prob - 0.5| * 2  →  [0, 1]
    features_used: int    # number of features the model was trained on


class SignalClassifier:
    """Thin wrapper around a trained LightGBM classifier for real-time inference."""

    def __init__(self, threshold: float = 0.55) -> None:
        self._model = None
        self._feature_names: list[str] = []
        self._threshold = threshold
        self._n_features = 0
        self._load_if_exists()

    # ------------------------------------------------------------------
    def _load_if_exists(self) -> None:
        if not os.path.exists(_MODEL_PATH):
            return
        try:
            with open(_MODEL_PATH, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._feature_names = data.get("feature_names", [])
            self._threshold = data.get("threshold", self._threshold)
            self._n_features = data.get("n_features", 0)
            logger.info("ML model loaded from %s (%d features)", _MODEL_PATH, self._n_features)
        except Exception as exc:
            logger.warning("Failed to load ML model: %s", exc)
            self._model = None

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------
    def predict(self, feature_vector: list[float]) -> MLSignal:
        """Return a directional signal for a single feature vector."""
        if not self.is_trained or self._model is None:
            return MLSignal(direction=0, bull_prob=0.5, confidence=0.0, features_used=0)
        try:
            import numpy as np  # noqa: PLC0415
            X = np.array(feature_vector, dtype=float).reshape(1, -1)
            bull_prob = float(self._model.predict_proba(X)[0][1])
            if not math.isfinite(bull_prob):
                bull_prob = 0.5

            if bull_prob >= self._threshold:
                direction = 1
            elif bull_prob <= (1.0 - self._threshold):
                direction = -1
            else:
                direction = 0

            confidence = abs(bull_prob - 0.5) * 2.0
            return MLSignal(
                direction=direction,
                bull_prob=bull_prob,
                confidence=confidence,
                features_used=len(feature_vector),
            )
        except Exception as exc:
            logger.debug("ML inference failed: %s", exc)
            return MLSignal(direction=0, bull_prob=0.5, confidence=0.0, features_used=0)

    # ------------------------------------------------------------------
    def train(
        self,
        features: list[list[float]],
        labels: list[int],
        feature_names: list[str] | None = None,
        threshold: float = 0.55,
        n_estimators: int = 300,
    ) -> dict:
        """
        Train the classifier on labelled feature data.

        features:      list of feature vectors (one per sample)
        labels:        1 if price went up over forward_bars, else 0
        threshold:     probability required before issuing a directional signal
        n_estimators:  number of boosting rounds

        Returns a metrics dict including walk-forward AUC.
        """
        try:
            import numpy as np  # noqa: PLC0415
            from lightgbm import LGBMClassifier  # noqa: PLC0415
            from sklearn.metrics import roc_auc_score  # noqa: PLC0415
            from sklearn.model_selection import TimeSeriesSplit  # noqa: PLC0415
        except ImportError as exc:
            return {"error": f"Missing dependency: {exc}. Install: lightgbm scikit-learn"}

        if len(features) < 100:
            return {"error": f"Need ≥ 100 samples, got {len(features)}"}

        X = np.array(features, dtype=float)
        y = np.array(labels, dtype=int)

        model = LGBMClassifier(
            n_estimators=n_estimators,
            learning_rate=0.05,
            max_depth=4,
            num_leaves=15,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=0.1,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )

        # Walk-forward cross-validation (respects time ordering)
        tscv = TimeSeriesSplit(n_splits=5)
        auc_scores: list[float] = []
        for train_idx, test_idx in tscv.split(X):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            model.fit(X_tr, y_tr)
            if len(set(y_te)) > 1:
                auc = roc_auc_score(y_te, model.predict_proba(X_te)[:, 1])
                auc_scores.append(float(auc))

        # Final fit on all data
        model.fit(X, y)

        self._model = model
        self._feature_names = feature_names or [f"f{i}" for i in range(X.shape[1])]
        self._threshold = threshold
        self._n_features = X.shape[1]

        # Persist
        try:
            with open(_MODEL_PATH, "wb") as f:
                pickle.dump(
                    {
                        "model": model,
                        "feature_names": self._feature_names,
                        "threshold": threshold,
                        "n_features": self._n_features,
                    },
                    f,
                )
        except Exception as exc:
            logger.warning("Could not persist model: %s", exc)

        mean_auc = sum(auc_scores) / len(auc_scores) if auc_scores else 0.0
        importance = dict(
            zip(self._feature_names, model.feature_importances_.tolist())
        )
        top_features = sorted(importance, key=lambda k: importance[k], reverse=True)[:10]

        return {
            "mean_cv_auc": round(mean_auc, 4),
            "n_samples": len(features),
            "n_features": self._n_features,
            "threshold": threshold,
            "top_features": {k: round(importance[k], 4) for k in top_features},
        }

    def delete_model(self) -> None:
        """Remove the persisted model file and reset in-memory state."""
        self._model = None
        self._n_features = 0
        if os.path.exists(_MODEL_PATH):
            os.remove(_MODEL_PATH)


# Module-level singleton — imported by strategy_engine and API routes
_classifier = SignalClassifier()


def get_classifier() -> SignalClassifier:
    return _classifier
