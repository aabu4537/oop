"""Phase 3 — Train Logistic Regression and XGBoost match outcome models.

Uses a temporal train/test split (no data leakage) and calibrates raw probabilities
with isotonic regression before saving .joblib artifacts.

Run:
    python -m src.models.train
"""
import logging
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from src.db.session import get_session
from src.models.features import FEATURE_COLS, brier_score_multiclass, build_feature_matrix

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parents[2] / "artifacts"
LR_VERSION  = "lr_v1.0"
XGB_VERSION = "xgb_v1.0"
TEST_RATIO  = 0.2


def _make_lr() -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            multi_class="multinomial",
            solver="lbfgs",
            max_iter=1000,
            C=1.0,
        )),
    ])


def _make_xgb() -> XGBClassifier:
    return XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        n_estimators=200,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="mlogloss",
        verbosity=0,
    )


def _evaluate(model, X_test: np.ndarray, y_test: np.ndarray) -> dict[str, float]:
    probs = model.predict_proba(X_test)
    return {
        "brier":    brier_score_multiclass(y_test, probs),
        "log_loss": log_loss(y_test, probs),
    }


def train_models(test_ratio: float = TEST_RATIO) -> dict[str, dict[str, float]]:
    """Fetch data, train both models, evaluate on temporal holdout, save artifacts.

    Returns a dict of {model_version: {brier: float, log_loss: float}}.
    """
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    with get_session() as session:
        df = build_feature_matrix(session)

    n = len(df)
    if n < 20:
        raise ValueError(f"Not enough training data: {n} matches (need at least 20)")

    X = df[FEATURE_COLS].to_numpy()
    y = df["outcome"].to_numpy()

    split = int(n * (1 - test_ratio))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    logger.info("Training on %d matches, evaluating on %d", split, n - split)

    results = {}

    # --- Logistic Regression ---
    lr_base = _make_lr()
    lr_base.fit(X_train, y_train)
    lr = CalibratedClassifierCV(lr_base, cv="prefit", method="isotonic")
    lr.fit(X_train, y_train)
    results[LR_VERSION] = _evaluate(lr, X_test, y_test)
    joblib.dump(lr, ARTIFACTS_DIR / f"{LR_VERSION}.joblib")
    logger.info("Saved %s — Brier: %.4f  Log-Loss: %.4f",
                LR_VERSION, results[LR_VERSION]["brier"], results[LR_VERSION]["log_loss"])

    # --- XGBoost ---
    xgb_base = _make_xgb()
    xgb_base.fit(X_train, y_train)
    xgb = CalibratedClassifierCV(xgb_base, cv="prefit", method="isotonic")
    xgb.fit(X_train, y_train)
    results[XGB_VERSION] = _evaluate(xgb, X_test, y_test)
    joblib.dump(xgb, ARTIFACTS_DIR / f"{XGB_VERSION}.joblib")
    logger.info("Saved %s — Brier: %.4f  Log-Loss: %.4f",
                XGB_VERSION, results[XGB_VERSION]["brier"], results[XGB_VERSION]["log_loss"])

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    train_models()
