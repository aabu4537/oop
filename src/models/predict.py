"""Phase 3 — Generate match outcome predictions using a trained model.

Loads a saved .joblib artifact, predicts for all matches that don't yet have
predictions from that model version, and upserts results to the predictions table.

Run:
    python -m src.models.predict              # uses xgb_v1.0 by default
    python -m src.models.predict --model lr_v1.0
"""
import argparse
import logging
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import log_loss

from src.db.models import Prediction
from src.db.session import get_session
from src.etl.loaders import upsert_prediction
from src.etl.pipeline_logger import pipeline_run
from src.models.features import FEATURE_COLS, brier_score_multiclass, build_feature_matrix
from src.models.train import ARTIFACTS_DIR, XGB_VERSION

logger = logging.getLogger(__name__)


def run_predictions(model_version: str = XGB_VERSION) -> None:
    """Predict outcomes for all unscored matches and persist to DB.

    Skips matches that already have a prediction from this model_version.
    Idempotent: safe to re-run without producing duplicates.
    """
    model_path = ARTIFACTS_DIR / f"{model_version}.joblib"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model artifact not found: {model_path}\n"
            "Run `python -m src.models.train` first."
        )

    model = joblib.load(model_path)
    logger.info("Loaded model %s from %s", model_version, model_path)

    with get_session() as session:
        with pipeline_run(session, f"predict_{model_version}") as run:
            df = build_feature_matrix(session)

            already_predicted = {
                r[0]
                for r in session.query(Prediction.match_id).filter_by(model_version=model_version)
            }
            df = df[~df["match_id"].isin(already_predicted)].reset_index(drop=True)

            if df.empty:
                logger.info("No new matches to predict for model %s", model_version)
                return

            X = df[FEATURE_COLS].to_numpy()
            # probs columns: [away_win (0), draw (1), home_win (2)]
            probs: np.ndarray = model.predict_proba(X)

            y = df["outcome"].to_numpy()
            brier = brier_score_multiclass(y, probs)
            ll    = log_loss(y, probs)

            for i, row in df.iterrows():
                upsert_prediction(
                    session,
                    match_id=row["match_id"],
                    model_version=model_version,
                    home_win_prob=float(probs[i, 2]),
                    draw_prob=float(probs[i, 1]),
                    away_win_prob=float(probs[i, 0]),
                    brier_score=brier,
                    log_loss=ll,
                )

            run.rows_inserted = len(df)
            logger.info(
                "Persisted %d predictions — Brier: %.4f  Log-Loss: %.4f",
                len(df), brier, ll,
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Generate match outcome predictions")
    parser.add_argument("--model", default=XGB_VERSION, help="Model version to use")
    args = parser.parse_args()
    run_predictions(args.model)
