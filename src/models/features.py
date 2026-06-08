"""Feature matrix builder for match outcome prediction.

Queries matches + teams (Elo) + team_metrics to produce a design matrix.
Matches without team_metrics (FIFA-only rows) have metric columns median-imputed.

Outcome encoding:  0 = away win  |  1 = draw  |  2 = home win
"""
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

FEATURE_COLS = [
    "elo_diff",
    "home_press", "away_press",
    "home_space", "away_space",
    "home_run",   "away_run",
    "home_def",   "away_def",
]

_METRIC_COLS = [c for c in FEATURE_COLS if c != "elo_diff"]

_SQL = text("""
    SELECT
        m.match_id,
        m.match_date,
        m.home_score,
        m.away_score,
        COALESCE(ht.elo_rating,  1500.0) AS home_elo,
        COALESCE(at_.elo_rating, 1500.0) AS away_elo,
        htm.avg_press_intensity AS home_press,
        atm.avg_press_intensity AS away_press,
        htm.avg_space_creation  AS home_space,
        atm.avg_space_creation  AS away_space,
        htm.avg_run_frequency   AS home_run,
        atm.avg_run_frequency   AS away_run,
        htm.def_line_engagement AS home_def,
        atm.def_line_engagement AS away_def
    FROM matches m
    JOIN teams ht   ON m.home_team_id = ht.team_id
    JOIN teams at_  ON m.away_team_id = at_.team_id
    LEFT JOIN team_metrics htm ON m.match_id = htm.match_id
                               AND htm.team_id = m.home_team_id
    LEFT JOIN team_metrics atm ON m.match_id = atm.match_id
                               AND atm.team_id = m.away_team_id
    WHERE m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
    ORDER BY m.match_date
""")


def build_feature_matrix(session: Session) -> pd.DataFrame:
    """Return DataFrame with FEATURE_COLS + ['outcome', 'match_id', 'match_date'].

    Rows are sorted by match_date (oldest first) so callers can do a temporal split
    by integer index without extra sorting.
    """
    result = session.execute(_SQL)
    df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    df["elo_diff"] = df["home_elo"] - df["away_elo"]
    df["outcome"] = encode_outcome(df["home_score"], df["away_score"])

    # Median impute off-ball metric columns (absent for FIFA-only matches)
    for col in _METRIC_COLS:
        median = df[col].median()
        df[col] = df[col].fillna(0.0 if np.isnan(median) else median)

    return df


def encode_outcome(home_score: pd.Series, away_score: pd.Series) -> pd.Series:
    """Encode match result as integer class (0=away win, 1=draw, 2=home win)."""
    return pd.Series(
        np.where(home_score > away_score, 2,
                 np.where(home_score == away_score, 1, 0)),
        index=home_score.index,
        dtype=int,
    )


def brier_score_multiclass(y_true: np.ndarray, y_prob: np.ndarray, n_classes: int = 3) -> float:
    """Mean squared error between probability vectors and one-hot encoded outcomes."""
    from sklearn.preprocessing import label_binarize
    y_one_hot = label_binarize(y_true, classes=list(range(n_classes))).astype(float)
    return float(np.mean(np.sum((y_prob - y_one_hot) ** 2, axis=1)))
