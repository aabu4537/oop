"""Feature matrix builder for match outcome prediction.

Queries matches + teams (Elo) + team_metrics to produce a design matrix.
Matches without team_metrics (FIFA-only rows) have OOP columns median-imputed.

Feature set is OOP-focused:
  elo_diff      — home Elo minus away Elo (always available)
  home/away_oop — oop_composite per team
  home/away_psr — pressure_success_rate per team
  home/away_press — avg_press_intensity per team
  home/away_intercept — interceptions_per90 per team
  home/away_recovery  — ball_recoveries_per90 per team

Outcome encoding:  0 = away win  |  1 = draw  |  2 = home win
"""
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

FEATURE_COLS = [
    "elo_diff",
    "home_oop",       "away_oop",
    "home_psr",       "away_psr",
    "home_press",     "away_press",
    "home_intercept", "away_intercept",
    "home_recovery",  "away_recovery",
]

_OOP_COLS = [c for c in FEATURE_COLS if c != "elo_diff"]

_SQL = text("""
    SELECT
        m.match_id,
        m.match_date,
        m.home_score,
        m.away_score,
        COALESCE(ht.elo_rating,  1500.0) AS home_elo,
        COALESCE(at_.elo_rating, 1500.0) AS away_elo,
        htm.oop_composite           AS home_oop,
        atm.oop_composite           AS away_oop,
        htm.pressure_success_rate   AS home_psr,
        atm.pressure_success_rate   AS away_psr,
        htm.avg_press_intensity     AS home_press,
        atm.avg_press_intensity     AS away_press,
        htm.interceptions_per90     AS home_intercept,
        atm.interceptions_per90     AS away_intercept,
        htm.ball_recoveries_per90   AS home_recovery,
        atm.ball_recoveries_per90   AS away_recovery
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

    Rows are sorted by match_date (oldest first) so callers can do a temporal
    split by integer index without extra sorting.
    OOP columns are median-imputed per column for rows without StatsBomb coverage.
    """
    result = session.execute(_SQL)
    df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    df["elo_diff"] = df["home_elo"] - df["away_elo"]
    df["outcome"] = encode_outcome(df["home_score"], df["away_score"])

    # Median-impute OOP columns (NULL for FIFA-only matches)
    for col in _OOP_COLS:
        median = df[col].median()
        df[col] = df[col].fillna(0.0 if np.isnan(median) else median)

    return df[["match_id", "match_date", "outcome"] + FEATURE_COLS]


_FUTURE_SQL = text("""
    SELECT
        m.match_id,
        m.match_date,
        m.competition,
        ht.name  AS home_team_name,
        at_.name AS away_team_name,
        COALESCE(ht.elo_rating,  1500.0) AS home_elo,
        COALESCE(at_.elo_rating, 1500.0) AS away_elo,
        htm.oop_composite           AS home_oop,
        atm.oop_composite           AS away_oop,
        htm.pressure_success_rate   AS home_psr,
        atm.pressure_success_rate   AS away_psr,
        htm.avg_press_intensity     AS home_press,
        atm.avg_press_intensity     AS away_press,
        htm.interceptions_per90     AS home_intercept,
        atm.interceptions_per90     AS away_intercept,
        htm.ball_recoveries_per90   AS home_recovery,
        atm.ball_recoveries_per90   AS away_recovery
    FROM matches m
    JOIN teams ht   ON m.home_team_id = ht.team_id
    JOIN teams at_  ON m.away_team_id = at_.team_id
    LEFT JOIN team_metrics htm ON m.match_id = htm.match_id
                               AND htm.team_id = m.home_team_id
    LEFT JOIN team_metrics atm ON m.match_id = atm.match_id
                               AND atm.team_id = m.away_team_id
    WHERE m.home_score IS NULL
      AND m.away_score IS NULL
    ORDER BY m.match_date
""")


def build_future_feature_matrix(session: Session) -> pd.DataFrame:
    """Return DataFrame with FEATURE_COLS + metadata for unplayed matches.

    Includes home_team_name, away_team_name, competition and match_date
    so predict.py can store them alongside predictions.
    OOP columns median-imputed from historical data when missing.
    """
    result = session.execute(_FUTURE_SQL)
    df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    if df.empty:
        return df

    df["elo_diff"] = df["home_elo"] - df["away_elo"]

    for col in _OOP_COLS:
        df[col] = df[col].fillna(0.0)

    return df[["match_id", "match_date", "competition", "home_team_name", "away_team_name"] + FEATURE_COLS]


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
