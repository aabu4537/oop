"""Modeling contract for match outcome prediction.

All prediction models — whether sklearn, XGBoost, or future alternatives —
must implement PredictionModel.  The simulation engine and API layer must
only ever call predict_proba through this interface, never import a concrete
model class directly.

Usage::

    from src.models.interface import JoblibModel

    team_stats = {
        "Spain":   {"elo": 2104.0, "press": 3.2, "space": 2.1, "run": 1.8, "def": 4.1},
        "Germany": {"elo": 1939.0, "press": 2.8, "space": 1.9, "run": 2.0, "def": 3.7},
    }
    model = JoblibModel("xgb_v1.0", team_stats)
    probs = model.predict_proba("Spain", "Germany", neutral=True)
    # {"home": 0.47, "draw": 0.28, "away": 0.25}
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PredictionModel(ABC):
    """Abstract prediction model contract.

    Implementations must return a dict with keys "home", "draw", "away"
    whose values are non-negative floats summing to 1.0.
    """

    @abstractmethod
    def predict_proba(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = False,
    ) -> dict[str, float]:
        """Predict match outcome probabilities.

        Args:
            home_team: Name of the home team (or team 1 at a neutral venue).
            away_team: Name of the away team (or team 2 at a neutral venue).
            neutral:   True when the match is played at a neutral venue.

        Returns:
            {"home": p_home, "draw": p_draw, "away": p_away} — values sum to 1.0.
        """


class JoblibModel(PredictionModel):
    """Wraps a saved sklearn / XGBoost .joblib artifact as a PredictionModel.

    The underlying artifact is a CalibratedClassifierCV trained with class
    ordering: 0 = away win, 1 = draw, 2 = home win (see src/models/train.py).

    Args:
        model_version: Artifact name without extension, e.g. ``"xgb_v1.0"``.
        team_stats:    Mapping of team name → feature dict with keys:
                       ``elo``, ``press``, ``space``, ``run``, ``def``.
                       Unknown teams default to neutral values (Elo=1500, metrics=0).
        artifacts_dir: Override for the artifacts directory (useful in tests).
    """

    _NEUTRAL_STATS: dict[str, float] = {
        "elo": 1500.0,
        "press": 0.0,
        "space": 0.0,
        "run": 0.0,
        "def": 0.0,
    }

    def __init__(
        self,
        model_version: str,
        team_stats: dict[str, dict[str, float]],
        artifacts_dir: Path | None = None,
    ) -> None:
        import joblib

        if artifacts_dir is None:
            artifacts_dir = Path(__file__).parents[2] / "artifacts"

        model_path = artifacts_dir / f"{model_version}.joblib"
        if not model_path.exists():
            raise FileNotFoundError(
                f"Model artifact not found: {model_path}\n"
                "Run `python -m src.models.train` first."
            )

        self._model = joblib.load(model_path)
        self._team_stats = team_stats
        self._version = model_version

    def predict_proba(
        self,
        home_team: str,
        away_team: str,
        neutral: bool = False,
    ) -> dict[str, float]:
        import numpy as np
        from src.config import get_model_config

        h = self._team_stats.get(home_team, self._NEUTRAL_STATS)
        a = self._team_stats.get(away_team, self._NEUTRAL_STATS)

        elo_h = h.get("elo", 1500.0)
        elo_a = a.get("elo", 1500.0)

        # Home advantage is implicitly encoded in elo_diff for non-neutral venues.
        # At neutral venues we remove the conventional 100-point offset.
        cfg = get_model_config()
        elo_diff = (elo_h - elo_a) - (cfg.elo_home_advantage if neutral else 0.0)

        feat = np.array([[
            elo_diff,
            h.get("press", 0.0), a.get("press", 0.0),
            h.get("space", 0.0), a.get("space", 0.0),
            h.get("run", 0.0),   a.get("run", 0.0),
            h.get("def", 0.0),   a.get("def", 0.0),
        ]])

        # sklearn class order: 0=away, 1=draw, 2=home
        probs = self._model.predict_proba(feat)[0]
        return {
            "home": float(probs[2]),
            "draw": float(probs[1]),
            "away": float(probs[0]),
        }
