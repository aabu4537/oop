"""Phase 2 — Feature engineering: compute off-ball metrics from event data.

Per-90-minute metrics derived from StatsBomb event types:

  Player-level
  ────────────
  press_intensity           — Pressure events per 90 min
  run_frequency             — Carry events per 90 min          [IN-POSSESSION ONLY]
  space_creation_idx        — (Carry + completed Dribble) / 90 [IN-POSSESSION ONLY]
  def_line_engagement       — (Clearance + Interception + Ball Recovery) / 90 (backwards compat)
  clearances_per90          — Clearance events per 90 min
  interceptions_per90       — Interception events per 90 min
  ball_recoveries_per90     — Ball Recovery events per 90 min
  pressure_final_third_pct  — Fraction of pressures applied in the final third (x > 80)

  Team-level (aggregated from players, plus event-sequence analysis)
  ──────────────────────────────────────────────────────────────────
  avg_press_intensity        — team mean of press_intensity
  avg_space_creation         — team mean of space_creation_idx [IN-POSSESSION ONLY]
  avg_run_frequency          — team mean of run_frequency      [IN-POSSESSION ONLY]
  def_line_engagement        — team mean (composite, backwards compat)
  clearances_per90           — team mean of clearances_per90
  interceptions_per90        — team mean of interceptions_per90
  ball_recoveries_per90      — team mean of ball_recoveries_per90
  pressure_success_rate      — fraction of pressures leading to regain within 5 s
  pressure_final_third_pct   — team mean of pressure_final_third_pct

  Possession-adjusted (corrects for high-possession teams having fewer opportunities)
  ─────────────────────────────────────────────────────────────────────────────────
  opponent_possession_phases — approximate count of opponent possession runs
  opponent_passing_attempts  — count of Pass events by the opponent
  press_intensity_adj        — raw pressure count / opponent_possession_phases
  interceptions_adj          — interceptions_per90 / opponent_passing_attempts * 100
  ball_recoveries_adj        — ball_recoveries_per90 / opponent_possession_phases
  oop_composite_adj          — possession-adjusted OOP composite:
                                 press_intensity_adj       × 0.35
                               + pressure_success_rate     × 0.30
                               + interceptions_adj         × 0.20
                               + ball_recoveries_adj       × 0.15
  oop_composite              — original (possession-biased) composite, kept for comparison

  Confidence-weighted blending (corrects for small sample size)
  ─────────────────────────────────────────────────────────────
  oop_composite_final = confidence * oop_composite_adj
                      + (1 - confidence) * confederation_avg
  oop_confidence      = min(n_matches / 15, 1.0)
  Where confederation_avg is the mean oop_composite_adj of same-confederation
  teams with 10+ matches (falls back to global median if < 3 qualifying teams).

Rolling window (rolling_oop_composite)
───────────────────────────────────────
  EWMA (span=10) of oop_composite_final over the last n matches
  strictly before the target date — no future data leakage.

Pipeline is idempotent: re-running skips already-processed matches unless
explicit match_ids are supplied (forces recompute).
"""
import logging
import uuid
from datetime import date
from typing import Sequence

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import get_model_config
from src.db.models import Event, PlayerMetric, Team
from src.db.session import get_session
from src.etl.loaders import upsert_player_metrics, upsert_team_metrics
from src.etl.pipeline_logger import assert_upstream_ok, pipeline_run

logger = logging.getLogger(__name__)

_PRESSURE = "Pressure"
_CARRY = "Carry"
_DRIBBLE = "Dribble"
_DRIBBLE_COMPLETE = "Complete"
_CLEARANCE = "Clearance"
_INTERCEPTION = "Interception"
_BALL_RECOVERY = "Ball Recovery"
_PASS = "Pass"
_DEFENSIVE_TYPES = frozenset({_CLEARANCE, _INTERCEPTION, _BALL_RECOVERY})
_REGAIN_TYPES = frozenset({_BALL_RECOVERY, _INTERCEPTION})

_cfg = get_model_config()
_OOP_W_PRESS     = _cfg.oop_w_press
_OOP_W_PSR       = _cfg.oop_w_psr
_OOP_W_INTERCEPT = _cfg.oop_w_intercept
_OOP_W_RECOVERY  = _cfg.oop_w_recovery

_FINAL_THIRD_X = 80.0  # StatsBomb 120×80 pitch; final third starts at x=80

# ---------------------------------------------------------------------------
# Confederation mapping — covers all teams appearing in StatsBomb open data
# ---------------------------------------------------------------------------

_CONFEDERATION_MAP: dict[str, str] = {
    # UEFA
    "England": "UEFA", "France": "UEFA", "Spain": "UEFA", "Germany": "UEFA",
    "Portugal": "UEFA", "Netherlands": "UEFA", "Belgium": "UEFA", "Croatia": "UEFA",
    "Denmark": "UEFA", "Switzerland": "UEFA", "Serbia": "UEFA", "Poland": "UEFA",
    "Wales": "UEFA", "Austria": "UEFA", "Scotland": "UEFA", "North Macedonia": "UEFA",
    "Ukraine": "UEFA", "Finland": "UEFA", "Iceland": "UEFA", "Hungary": "UEFA",
    "Czech Republic": "UEFA", "Slovakia": "UEFA", "Albania": "UEFA", "Slovenia": "UEFA",
    "Georgia": "UEFA", "Turkey": "UEFA", "Romania": "UEFA", "Italy": "UEFA",
    "Russia": "UEFA", "Sweden": "UEFA", "Norway": "UEFA", "Greece": "UEFA",
    "Bosnia and Herzegovina": "UEFA", "Montenegro": "UEFA", "Kosovo": "UEFA",
    "Republic of Ireland": "UEFA", "Northern Ireland": "UEFA", "Luxembourg": "UEFA",
    "Malta": "UEFA", "Cyprus": "UEFA", "Andorra": "UEFA", "Liechtenstein": "UEFA",
    "San Marino": "UEFA", "Faroe Islands": "UEFA", "Estonia": "UEFA",
    "Latvia": "UEFA", "Lithuania": "UEFA", "Belarus": "UEFA", "Moldova": "UEFA",
    "Armenia": "UEFA", "Azerbaijan": "UEFA", "Kazakhstan": "UEFA", "Bulgaria": "UEFA",
    # CONMEBOL
    "Argentina": "CONMEBOL", "Brazil": "CONMEBOL", "Uruguay": "CONMEBOL",
    "Colombia": "CONMEBOL", "Ecuador": "CONMEBOL", "Chile": "CONMEBOL",
    "Peru": "CONMEBOL", "Paraguay": "CONMEBOL", "Bolivia": "CONMEBOL",
    "Venezuela": "CONMEBOL",
    # CAF
    "Morocco": "CAF", "Senegal": "CAF", "Ghana": "CAF", "Cameroon": "CAF",
    "Tunisia": "CAF", "Nigeria": "CAF", "Côte d'Ivoire": "CAF", "Algeria": "CAF",
    "South Africa": "CAF", "Egypt": "CAF", "Mali": "CAF", "Burkina Faso": "CAF",
    "Cape Verde Islands": "CAF", "Angola": "CAF", "Mauritania": "CAF",
    "Namibia": "CAF", "Mozambique": "CAF", "Guinea": "CAF", "Congo DR": "CAF",
    "Gambia": "CAF", "Guinea-Bissau": "CAF", "Tanzania": "CAF", "Zambia": "CAF",
    "Equatorial Guinea": "CAF", "Gabon": "CAF", "Rwanda": "CAF", "Comoros": "CAF",
    "South Sudan": "CAF",
    # AFC
    "Japan": "AFC", "South Korea": "AFC", "Iran": "AFC", "Saudi Arabia": "AFC",
    "Australia": "AFC", "Qatar": "AFC", "China": "AFC", "United Arab Emirates": "AFC",
    "Uzbekistan": "AFC", "Iraq": "AFC", "Bahrain": "AFC", "Oman": "AFC",
    "Jordan": "AFC", "Syria": "AFC", "Lebanon": "AFC", "Kuwait": "AFC",
    "India": "AFC", "Thailand": "AFC", "Vietnam": "AFC", "Malaysia": "AFC",
    "Philippines": "AFC", "North Korea": "AFC", "Taiwan": "AFC",
    "Tajikistan": "AFC", "Kyrgyzstan": "AFC", "Turkmenistan": "AFC",
    "Maldives": "AFC", "Cambodia": "AFC", "Indonesia": "AFC", "Guam": "AFC",
    "Hong Kong": "AFC",
    # CONCACAF
    "United States": "CONCACAF", "Mexico": "CONCACAF", "Canada": "CONCACAF",
    "Costa Rica": "CONCACAF", "Jamaica": "CONCACAF", "Panama": "CONCACAF",
    "Honduras": "CONCACAF", "El Salvador": "CONCACAF",
    "Trinidad and Tobago": "CONCACAF", "Haiti": "CONCACAF",
    "Guatemala": "CONCACAF", "Cuba": "CONCACAF",
    # OFC
    "New Zealand": "OFC", "Fiji": "OFC", "Papua New Guinea": "OFC",
}


# ---------------------------------------------------------------------------
# Pure computation — no DB access
# ---------------------------------------------------------------------------

def compute_player_metrics(events_df: pd.DataFrame) -> pd.DataFrame:
    """Map raw events to per-player per-match metrics.

    Input columns : match_id, player_id, team_id, event_type, outcome, minute,
                    location (optional JSONB [x, y])
    Output columns: match_id, player_id, team_id,
                    press_intensity, run_frequency, space_creation_idx,
                    def_line_engagement, clearances_per90, interceptions_per90,
                    ball_recoveries_per90, pressure_final_third_pct
    """
    _EMPTY_COLS = [
        "match_id", "player_id", "team_id",
        "press_intensity", "run_frequency", "space_creation_idx", "def_line_engagement",
        "clearances_per90", "interceptions_per90", "ball_recoveries_per90",
        "pressure_final_third_pct",
    ]
    if events_df.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    df = events_df.copy()
    df["is_pressure"] = df["event_type"] == _PRESSURE
    df["is_carry"] = df["event_type"] == _CARRY
    df["is_dribble_complete"] = (df["event_type"] == _DRIBBLE) & (df["outcome"] == _DRIBBLE_COMPLETE)
    df["is_defensive"] = df["event_type"].isin(_DEFENSIVE_TYPES)
    df["is_clearance"] = df["event_type"] == _CLEARANCE
    df["is_interception"] = df["event_type"] == _INTERCEPTION
    df["is_ball_recovery"] = df["event_type"] == _BALL_RECOVERY

    # Pressure in final third: x > 80 on 120×80 pitch.
    # StatsBomb stores location as {'x': float, 'y': float} in JSONB.
    if "location" in df.columns:
        def _in_final_third(loc):
            try:
                if isinstance(loc, dict):
                    return float(loc["x"]) > _FINAL_THIRD_X
                # fallback for list-encoded locations
                return float(loc[0]) > _FINAL_THIRD_X
            except (TypeError, IndexError, KeyError):
                return False
        df["is_pressure_ft"] = df["is_pressure"] & df["location"].map(_in_final_third)
    else:
        df["is_pressure_ft"] = False

    agg = (
        df.groupby(["match_id", "player_id", "team_id"], sort=False)
        .agg(
            pressure_count=("is_pressure", "sum"),
            pressure_ft_count=("is_pressure_ft", "sum"),
            carry_count=("is_carry", "sum"),
            dribble_complete_count=("is_dribble_complete", "sum"),
            defensive_count=("is_defensive", "sum"),
            clearance_count=("is_clearance", "sum"),
            interception_count=("is_interception", "sum"),
            ball_recovery_count=("is_ball_recovery", "sum"),
            max_minute=("minute", "max"),
        )
        .reset_index()
    )

    minutes = agg["max_minute"].clip(lower=1)
    agg["press_intensity"] = (agg["pressure_count"] / minutes * 90).round(4)
    agg["run_frequency"] = (agg["carry_count"] / minutes * 90).round(4)
    agg["space_creation_idx"] = (
        (agg["carry_count"] + agg["dribble_complete_count"]) / minutes * 90
    ).round(4)
    agg["def_line_engagement"] = (agg["defensive_count"] / minutes * 90).round(4)
    agg["clearances_per90"] = (agg["clearance_count"] / minutes * 90).round(4)
    agg["interceptions_per90"] = (agg["interception_count"] / minutes * 90).round(4)
    agg["ball_recoveries_per90"] = (agg["ball_recovery_count"] / minutes * 90).round(4)
    agg["pressure_final_third_pct"] = (
        agg["pressure_ft_count"] / agg["pressure_count"].clip(lower=1)
    ).round(4)

    return agg[_EMPTY_COLS]


def compute_team_metrics(
    player_metrics_df: pd.DataFrame,
    raw_events_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate player metrics to team level, compute OOP composite and adj variants.

    Args:
        player_metrics_df: Output of compute_player_metrics.
        raw_events_df:     All events for the same matches with columns:
                           match_id, team_id, event_type, minute, second.
                           Required for PSR and possession adjustments.

    Output columns: match_id, team_id,
                    avg_press_intensity, avg_space_creation, avg_run_frequency,
                    def_line_engagement, clearances_per90, interceptions_per90,
                    ball_recoveries_per90, pressure_success_rate,
                    pressure_final_third_pct, oop_composite,
                    opponent_possession_phases, opponent_passing_attempts,
                    press_intensity_adj, interceptions_adj, ball_recoveries_adj,
                    oop_composite_adj
    """
    _EMPTY_COLS = [
        "match_id", "team_id",
        "avg_press_intensity", "avg_space_creation", "avg_run_frequency", "def_line_engagement",
        "clearances_per90", "interceptions_per90", "ball_recoveries_per90",
        "pressure_success_rate", "pressure_final_third_pct",
        "oop_composite",
        "opponent_possession_phases", "opponent_passing_attempts",
        "press_intensity_adj", "interceptions_adj", "ball_recoveries_adj",
        "oop_composite_adj",
    ]
    if player_metrics_df.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    agg_dict: dict = {
        "avg_press_intensity": ("press_intensity", "mean"),
        "avg_space_creation":  ("space_creation_idx", "mean"),
        "avg_run_frequency":   ("run_frequency", "mean"),
        "def_line_engagement": ("def_line_engagement", "mean"),
        "clearances_per90":    ("clearances_per90", "mean"),
        "interceptions_per90": ("interceptions_per90", "mean"),
        "ball_recoveries_per90": ("ball_recoveries_per90", "mean"),
    }
    if "pressure_final_third_pct" in player_metrics_df.columns:
        agg_dict["pressure_final_third_pct"] = ("pressure_final_third_pct", "mean")

    team = (
        player_metrics_df.groupby(["match_id", "team_id"], sort=False)
        .agg(**agg_dict)
        .round(4)
        .reset_index()
    )
    if "pressure_final_third_pct" not in team.columns:
        team["pressure_final_third_pct"] = 0.0

    if raw_events_df is not None and not raw_events_df.empty:
        psr = _compute_pressure_success_rate(raw_events_df)
        team = team.merge(psr, on=["match_id", "team_id"], how="left")
        team["pressure_success_rate"] = team["pressure_success_rate"].fillna(0.0).round(4)
    else:
        team["pressure_success_rate"] = 0.0

    team["oop_composite"] = (
        team["avg_press_intensity"] * _OOP_W_PRESS
        + team["pressure_success_rate"] * _OOP_W_PSR
        + team["interceptions_per90"] * _OOP_W_INTERCEPT
        + team["ball_recoveries_per90"] * _OOP_W_RECOVERY
    ).round(4)

    if raw_events_df is not None and not raw_events_df.empty:
        adj = _compute_possession_adjustments(raw_events_df, team)
        team = team.merge(adj, on=["match_id", "team_id"], how="left")
    else:
        for col in ["opponent_possession_phases", "opponent_passing_attempts",
                    "press_intensity_adj", "interceptions_adj",
                    "ball_recoveries_adj", "oop_composite_adj"]:
            team[col] = None

    return team[_EMPTY_COLS]


def rolling_oop_composite(
    team_metrics_df: pd.DataFrame,
    team_id: uuid.UUID,
    before_date: date,
    n: int | None = None,
    use_adjusted: bool = True,
    return_confidence: bool = False,
) -> float | None | tuple[float | None, float]:
    """EWMA OOP composite for a team over the last n matches before a date.

    Column preference (highest to lowest): oop_composite_final →
    oop_composite_adj → oop_composite.

    Args:
        team_metrics_df:  DataFrame with team_id, match_date, and OOP columns.
        team_id:          Target team.
        before_date:      Only matches strictly before this date are used.
        n:                EWMA span (default: oop_rolling_window from config).
        use_adjusted:     If True (default), prefer the possession-adjusted and
                          confidence-blended columns over the raw composite.
        return_confidence: If True, return (value, confidence) tuple instead of
                          just the float. Confidence is the mean oop_confidence
                          over the history window (1.0 if column absent).

    Returns None (or (None, 0.0)) if the team has no history before before_date.
    """
    if n is None:
        n = get_model_config().oop_rolling_window

    if use_adjusted:
        for candidate in ("oop_composite_final", "oop_composite_adj", "oop_composite"):
            if candidate in team_metrics_df.columns:
                col = candidate
                break
        else:
            col = "oop_composite"
    else:
        col = "oop_composite"

    mask = (
        (team_metrics_df["team_id"] == team_id)
        & (team_metrics_df["match_date"] < before_date)
        & team_metrics_df[col].notna()
    )
    history = team_metrics_df.loc[mask].sort_values("match_date", ascending=True)
    if history.empty:
        return (None, 0.0) if return_confidence else None

    ewma = history[col].ewm(span=n, adjust=False).mean()
    value = round(float(ewma.iloc[-1]), 4)

    if return_confidence:
        conf_col = "oop_confidence"
        confidence = (
            round(float(history[conf_col].mean()), 4)
            if conf_col in history.columns and history[conf_col].notna().any()
            else 1.0
        )
        return value, confidence

    return value


# ---------------------------------------------------------------------------
# Pressure success rate — team-level, requires temporal event sequence
# ---------------------------------------------------------------------------

def _compute_pressure_success_rate(raw_events_df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of Pressure events where the pressing team regained possession within 5 s.

    Input columns : match_id, team_id, event_type, minute, second
    Output columns: match_id, team_id, pressure_success_rate
    """
    df = raw_events_df.copy()
    df["t"] = df["minute"] * 60 + df["second"].fillna(0).astype(int)

    pressures = (
        df[df["event_type"] == _PRESSURE][["match_id", "team_id", "t"]]
        .reset_index(drop=True)
    )
    pressures["press_idx"] = pressures.index

    empty = pd.DataFrame(columns=["match_id", "team_id", "pressure_success_rate"])
    if pressures.empty:
        return empty

    regains = df[df["event_type"].isin(_REGAIN_TYPES)][["match_id", "team_id", "t"]].copy()

    if regains.empty:
        totals = pressures.groupby(["match_id", "team_id"]).size().reset_index(name="_n")
        totals["pressure_success_rate"] = 0.0
        return totals[["match_id", "team_id", "pressure_success_rate"]]

    merged = pressures.merge(
        regains.rename(columns={"t": "regain_t"}),
        on=["match_id", "team_id"],
        how="left",
    )
    merged["is_success"] = (
        merged["regain_t"].notna()
        & (merged["regain_t"] >= merged["t"])
        & (merged["regain_t"] <= merged["t"] + 5)
    )

    per_press = (
        merged.groupby(["press_idx", "match_id", "team_id"])["is_success"]
        .any()
        .reset_index()
    )

    team_psr = (
        per_press.groupby(["match_id", "team_id"])
        .agg(success=("is_success", "sum"), total=("is_success", "count"))
        .reset_index()
    )
    team_psr["pressure_success_rate"] = (team_psr["success"] / team_psr["total"]).round(4)

    return team_psr[["match_id", "team_id", "pressure_success_rate"]]


# ---------------------------------------------------------------------------
# Possession-adjusted metrics
# ---------------------------------------------------------------------------

def _compute_possession_adjustments(
    raw_events_df: pd.DataFrame,
    team_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute possession-adjusted pressing metrics to remove possession bias.

    High-possession teams (Spain, England) naturally have fewer pressing
    opportunities because the opponent has less of the ball. These metrics
    normalise by opponent activity so dominance of the ball doesn't depress
    a team's OOP score.

    Input:
        raw_events_df — match_id, team_id, event_type, minute, second
        team_df       — output of compute_team_metrics (pre-adj columns)

    Output columns: match_id, team_id,
                    opponent_possession_phases, opponent_passing_attempts,
                    press_intensity_adj, interceptions_adj,
                    ball_recoveries_adj, oop_composite_adj
    """
    df = raw_events_df.copy()
    df["t"] = df["minute"] * 60 + df["second"].fillna(0).astype(int)
    df_sorted = df.sort_values(["match_id", "t"])

    # --- Opponent possession phases (approximate from sequential event stream) ---
    # Each time the team_id changes in the event order, a new possession phase starts.
    df_sorted = df_sorted.copy()
    df_sorted["_changed"] = (
        df_sorted.groupby("match_id")["team_id"]
        .transform(lambda x: (x != x.shift(1)).astype(int))
    )
    df_sorted["_phase"] = df_sorted.groupby("match_id")["_changed"].cumsum()

    team_phases = (
        df_sorted.groupby(["match_id", "team_id"])["_phase"]
        .nunique()
        .reset_index(name="own_phases")
    )

    # Cross-join within each match so each team gets the other team's phase count
    opp_phases = team_phases.rename(
        columns={"team_id": "opp_id", "own_phases": "opponent_possession_phases"}
    )
    cross = team_phases.merge(opp_phases, on="match_id")
    cross = cross[cross["team_id"] != cross["opp_id"]]
    opponent_phases = cross[["match_id", "team_id", "opponent_possession_phases"]].drop_duplicates()

    # --- Opponent passing attempts ---
    team_passes = (
        df[df["event_type"] == _PASS]
        .groupby(["match_id", "team_id"])
        .size()
        .reset_index(name="own_passes")
    )
    opp_passes = team_passes.rename(
        columns={"team_id": "opp_id", "own_passes": "opponent_passing_attempts"}
    )
    cross_passes = team_passes.merge(opp_passes, on="match_id")
    cross_passes = cross_passes[cross_passes["team_id"] != cross_passes["opp_id"]]
    opponent_passes = cross_passes[["match_id", "team_id", "opponent_passing_attempts"]].drop_duplicates()

    # --- Team raw pressure counts ---
    pressure_counts = (
        df[df["event_type"] == _PRESSURE]
        .groupby(["match_id", "team_id"])
        .size()
        .reset_index(name="pressure_count")
    )

    # --- Merge and compute ---
    adj = team_df[["match_id", "team_id", "interceptions_per90",
                   "ball_recoveries_per90", "pressure_success_rate"]].copy()
    adj = adj.merge(opponent_phases, on=["match_id", "team_id"], how="left")
    adj = adj.merge(opponent_passes, on=["match_id", "team_id"], how="left")
    adj = adj.merge(pressure_counts, on=["match_id", "team_id"], how="left")

    adj["opponent_possession_phases"] = adj["opponent_possession_phases"].fillna(1).clip(lower=1)
    adj["opponent_passing_attempts"]  = adj["opponent_passing_attempts"].fillna(1).clip(lower=1)
    adj["pressure_count"] = adj["pressure_count"].fillna(0)

    adj["press_intensity_adj"] = (
        adj["pressure_count"] / adj["opponent_possession_phases"]
    ).round(4)
    adj["interceptions_adj"] = (
        adj["interceptions_per90"] / adj["opponent_passing_attempts"] * 100
    ).round(4)
    adj["ball_recoveries_adj"] = (
        adj["ball_recoveries_per90"] / adj["opponent_possession_phases"]
    ).round(4)

    adj["oop_composite_adj"] = (
        adj["press_intensity_adj"]  * _OOP_W_PRESS
        + adj["pressure_success_rate"] * _OOP_W_PSR
        + adj["interceptions_adj"]   * _OOP_W_INTERCEPT
        + adj["ball_recoveries_adj"] * _OOP_W_RECOVERY
    ).round(4)

    return adj[[
        "match_id", "team_id",
        "opponent_possession_phases", "opponent_passing_attempts",
        "press_intensity_adj", "interceptions_adj",
        "ball_recoveries_adj", "oop_composite_adj",
    ]]


# ---------------------------------------------------------------------------
# Confederation baseline + confidence-weighted blending
# ---------------------------------------------------------------------------

def _populate_team_confederations(session: Session) -> None:
    """Write confederation column for all known teams."""
    for name, conf in _CONFEDERATION_MAP.items():
        session.execute(
            text("UPDATE teams SET confederation = :conf WHERE name = :name"),
            {"conf": conf, "name": name},
        )


def _compute_global_median(session: Session) -> float:
    """Median of per-team avg oop_composite_adj across all teams with data."""
    row = session.execute(text("""
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY avg_adj) AS median_val
        FROM (
            SELECT AVG(tm.oop_composite_adj) AS avg_adj
            FROM team_metrics tm
            WHERE tm.oop_composite_adj IS NOT NULL
            GROUP BY tm.team_id
        ) sub
    """)).fetchone()
    return float(row.median_val) if row and row.median_val is not None else 0.175


def compute_confederation_baselines(
    session: Session,
    min_matches: int = 10,
    min_teams: int = 3,
) -> dict[str, float]:
    """Per-confederation mean oop_composite_adj using teams with min_matches.

    Falls back to global median for confederations with fewer than min_teams
    qualifying teams.

    Returns dict keyed by confederation string plus '_global' fallback.
    """
    rows = session.execute(text("""
        SELECT t.confederation,
               AVG(team_avg.avg_adj) AS conf_avg,
               COUNT(*)              AS n_teams
        FROM (
            SELECT tm.team_id, AVG(tm.oop_composite_adj) AS avg_adj, COUNT(*) AS n_matches
            FROM team_metrics tm
            WHERE tm.oop_composite_adj IS NOT NULL
            GROUP BY tm.team_id
            HAVING COUNT(*) >= :min_matches
        ) team_avg
        JOIN teams t ON t.team_id = team_avg.team_id
        WHERE t.confederation IS NOT NULL
        GROUP BY t.confederation
        HAVING COUNT(*) >= :min_teams
    """), {"min_matches": min_matches, "min_teams": min_teams}).fetchall()

    global_median = _compute_global_median(session)
    baselines: dict[str, float] = {"_global": global_median}
    for r in rows:
        baselines[r.confederation] = float(r.conf_avg)
        logger.debug(
            "Confederation baseline %s = %.4f (%d qualifying teams)",
            r.confederation, r.conf_avg, r.n_teams,
        )
    return baselines


def confidence_weighted_oop(
    team_oop: float,
    confederation: str | None,
    n_matches: int,
    confederation_baselines: dict[str, float],
    threshold: int = 15,
) -> tuple[float, float]:
    """Blend team OOP with confederation average weighted by sample confidence.

    confidence = min(n_matches / threshold, 1.0)
    blended    = confidence * team_oop + (1 - confidence) * confederation_avg

    Returns (blended_oop, confidence).
    """
    confidence = min(n_matches / threshold, 1.0)
    conf_avg = confederation_baselines.get(
        confederation or "",
        confederation_baselines["_global"],
    )
    blended = confidence * team_oop + (1 - confidence) * conf_avg
    return round(blended, 4), round(confidence, 4)


def _apply_confidence_blending(session: Session) -> None:
    """Second pass: compute oop_composite_final and oop_confidence for all teams.

    Runs after all per-match metrics are persisted so it sees the full sample.
    Updates all team_metrics rows for a given team with the same blended value
    (since confidence is a team-level property, not per-match).
    """
    _populate_team_confederations(session)
    baselines = compute_confederation_baselines(session)

    logger.info(
        "Confederation baselines: %s",
        {k: f"{v:.4f}" for k, v in baselines.items()},
    )

    teams = session.execute(text("""
        SELECT t.team_id, t.name, t.confederation,
               AVG(tm.oop_composite_adj) AS avg_adj,
               COUNT(*)                  AS n_matches
        FROM team_metrics tm
        JOIN teams t ON t.team_id = tm.team_id
        WHERE tm.oop_composite_adj IS NOT NULL
        GROUP BY t.team_id, t.name, t.confederation
    """)).fetchall()

    for r in teams:
        blended, confidence = confidence_weighted_oop(
            float(r.avg_adj),
            r.confederation,
            int(r.n_matches),
            baselines,
        )
        session.execute(text("""
            UPDATE team_metrics
            SET oop_composite_final = :final,
                oop_confidence      = :conf
            WHERE team_id = :tid
        """), {"final": blended, "conf": confidence, "tid": r.team_id})

    logger.info("Applied confidence blending to %d teams", len(teams))


# ---------------------------------------------------------------------------
# DB I/O
# ---------------------------------------------------------------------------

def _fetch_events(
    session: Session,
    match_ids: Sequence[uuid.UUID] | None = None,
) -> pd.DataFrame:
    """Events with player_id for player-level metric computation.

    If match_ids is None, fetches only matches without existing player_metrics.
    If match_ids is provided, fetches those matches unconditionally (force-recompute).
    """
    query = session.query(
        Event.match_id,
        Event.player_id,
        Event.team_id,
        Event.event_type,
        Event.outcome,
        Event.minute,
        Event.location,
    ).filter(Event.player_id.isnot(None))

    if match_ids is not None:
        query = query.filter(Event.match_id.in_(match_ids))
    else:
        processed = session.query(PlayerMetric.match_id).distinct().subquery()
        query = query.filter(Event.match_id.notin_(processed))

    rows = query.all()
    cols = ["match_id", "player_id", "team_id", "event_type", "outcome", "minute", "location"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols)


def _fetch_raw_events(
    session: Session,
    match_ids: Sequence[uuid.UUID],
) -> pd.DataFrame:
    """All events for the given matches (no player filter) for PSR and possession computation."""
    if not match_ids:
        return pd.DataFrame(columns=["match_id", "team_id", "event_type", "minute", "second"])

    rows = (
        session.query(
            Event.match_id,
            Event.team_id,
            Event.event_type,
            Event.minute,
            Event.second,
        )
        .filter(Event.match_id.in_(match_ids))
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["match_id", "team_id", "event_type", "minute", "second"])
    return pd.DataFrame(rows, columns=["match_id", "team_id", "event_type", "minute", "second"])


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return None


def _persist(session: Session, player_df: pd.DataFrame, team_df: pd.DataFrame) -> int:
    for _, row in player_df.iterrows():
        upsert_player_metrics(
            session,
            player_id=row["player_id"],
            match_id=row["match_id"],
            press_intensity=_safe_float(row["press_intensity"]),
            run_frequency=_safe_float(row["run_frequency"]),
            space_creation_idx=_safe_float(row["space_creation_idx"]),
            def_line_engagement=_safe_float(row["def_line_engagement"]),
            clearances_per90=_safe_float(row["clearances_per90"]),
            interceptions_per90=_safe_float(row["interceptions_per90"]),
            ball_recoveries_per90=_safe_float(row["ball_recoveries_per90"]),
            pressure_final_third_pct=_safe_float(row.get("pressure_final_third_pct")),
        )

    for _, row in team_df.iterrows():
        upsert_team_metrics(
            session,
            team_id=row["team_id"],
            match_id=row["match_id"],
            avg_press_intensity=_safe_float(row["avg_press_intensity"]),
            avg_space_creation=_safe_float(row["avg_space_creation"]),
            avg_run_frequency=_safe_float(row["avg_run_frequency"]),
            def_line_engagement=_safe_float(row["def_line_engagement"]),
            clearances_per90=_safe_float(row["clearances_per90"]),
            interceptions_per90=_safe_float(row["interceptions_per90"]),
            ball_recoveries_per90=_safe_float(row["ball_recoveries_per90"]),
            pressure_success_rate=_safe_float(row["pressure_success_rate"]),
            pressure_final_third_pct=_safe_float(row.get("pressure_final_third_pct")),
            oop_composite=_safe_float(row["oop_composite"]),
            opponent_possession_phases=_safe_float(row.get("opponent_possession_phases")),
            opponent_passing_attempts=_safe_float(row.get("opponent_passing_attempts")),
            press_intensity_adj=_safe_float(row.get("press_intensity_adj")),
            interceptions_adj=_safe_float(row.get("interceptions_adj")),
            ball_recoveries_adj=_safe_float(row.get("ball_recoveries_adj")),
            oop_composite_adj=_safe_float(row.get("oop_composite_adj")),
        )

    return len(player_df)


def _print_oop_rankings(session: Session, team_df: pd.DataFrame) -> None:
    """Print top/bottom 10 teams by both oop_composite and oop_composite_adj."""
    if team_df.empty:
        return

    team_ids = team_df["team_id"].unique().tolist()
    name_rows = session.query(Team.team_id, Team.name).filter(Team.team_id.in_(team_ids)).all()
    id_to_name = {r.team_id: r.name for r in name_rows}

    for col, label in [
        ("oop_composite",     "oop_composite (original)"),
        ("oop_composite_adj", "oop_composite_adj (possession-adjusted)"),
    ]:
        if col not in team_df.columns or team_df[col].isna().all():
            continue
        summary = (
            team_df.groupby("team_id")[col]
            .mean()
            .reset_index()
            .rename(columns={col: "avg"})
            .sort_values("avg", ascending=False)
            .reset_index(drop=True)
        )
        summary["team"] = summary["team_id"].map(id_to_name).fillna("Unknown")
        print(f"\n=== Top 10 by {label} ===")
        for _, r in summary.head(10).iterrows():
            print(f"  {r['team']:<35} {r['avg']:.4f}")
        print(f"=== Bottom 10 by {label} ===")
        for _, r in summary.tail(10).iterrows():
            print(f"  {r['team']:<35} {r['avg']:.4f}")
    print()


def _print_sanity_checks(session: Session) -> None:
    """Sanity checks: confidence blending table, final ranking, player sample."""

    spotlight = [
        "Jamaica", "Saudi Arabia", "Ghana", "South Korea", "United States",
        "Japan", "Brazil", "Germany", "Spain", "England",
    ]
    baselines = compute_confederation_baselines(session)

    rows = session.execute(text("""
        SELECT t.name, t.confederation,
               COUNT(*)                       AS n_matches,
               AVG(tm.oop_confidence)         AS confidence,
               AVG(tm.oop_composite_adj)      AS oop_raw,
               AVG(tm.oop_composite_final)    AS oop_final
        FROM team_metrics tm
        JOIN teams t ON t.team_id = tm.team_id
        WHERE t.name = ANY(:names)
          AND tm.oop_composite_final IS NOT NULL
        GROUP BY t.name, t.confederation
        ORDER BY n_matches
    """), {"names": spotlight}).fetchall()

    print(f"\n=== Confidence-weighted OOP blending ===")
    print(f"  {'Team':<20} {'Conf':>8} {'Matches':>8} {'Confid':>7} {'Raw Adj':>8} {'Conf Avg':>9} {'Final':>8}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*7} {'-'*8} {'-'*9} {'-'*8}")
    for r in rows:
        conf_avg = baselines.get(r.confederation or "", baselines["_global"])
        print(
            f"  {r.name:<20} {(r.confederation or '?'):>8} {r.n_matches:>8} "
            f"{r.confidence:>7.2f} {r.oop_raw:>8.4f} {conf_avg:>9.4f} {r.oop_final:>8.4f}"
        )

    # Full ranking by oop_composite_final
    all_rows = session.execute(text("""
        SELECT t.name,
               AVG(tm.oop_composite_adj)   AS avg_adj,
               AVG(tm.oop_composite_final) AS avg_final,
               AVG(tm.oop_confidence)      AS avg_conf
        FROM team_metrics tm
        JOIN teams t ON t.team_id = tm.team_id
        WHERE tm.oop_composite_final IS NOT NULL
        GROUP BY t.name
        ORDER BY avg_final DESC
    """)).fetchall()

    if all_rows:
        print(f"\n=== Top 15 / Bottom 10 by oop_composite_final ===")
        print(f"  {'Team':<35} {'Adj':>8} {'Final':>8} {'Conf':>6}")
        for item in list(all_rows[:15]) + ["..."] + list(all_rows[-10:]):
            if item == "...":
                print("  ...")
                continue
            marker = " ←" if item.name in ("Spain", "Germany", "England", "France", "Brazil") else ""
            print(f"  {item.name:<35} {item.avg_adj:>8.4f} {item.avg_final:>8.4f} {item.avg_conf:>6.2f}{marker}")

    # Player sample
    player_rows = session.execute(text("""
        SELECT p.name, AVG(pm.pressure_final_third_pct) AS avg_ft_pct,
               AVG(pm.press_intensity) AS avg_press, COUNT(*) AS n_matches
        FROM player_metrics pm
        JOIN players p ON p.player_id = pm.player_id
        WHERE pm.pressure_final_third_pct IS NOT NULL
        GROUP BY p.name
        HAVING COUNT(*) >= 5
        ORDER BY avg_ft_pct DESC
        LIMIT 12
    """)).fetchall()

    if player_rows:
        print(f"\n=== Top players by pressure_final_third_pct (≥5 matches) ===")
        print(f"  {'Player':<32} {'FT%':>6} {'Press/90':>9} {'Matches':>8}")
        for r in player_rows:
            print(f"  {r.name:<32} {r.avg_ft_pct:>6.3f} {r.avg_press:>9.2f} {r.n_matches:>8}")
    print()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    match_ids: Sequence[uuid.UUID] | None = None,
    force: bool = False,
    recompute_all: bool = False,
) -> None:
    """Compute and persist off-ball metrics.

    Args:
        match_ids:     If provided, recomputes these specific matches.
                       If None, processes only matches with no existing player_metrics.
        force:         Bypass upstream pipeline status checks.
        recompute_all: Recompute all matches that already have player_metrics
                       (used to backfill new metric columns).
    """
    with get_session() as session:
        assert_upstream_ok(session, "statsbomb_ingest", force=force)
        with pipeline_run(session, "feature_engineering") as run:
            if recompute_all and match_ids is None:
                all_ids = [
                    r[0] for r in session.query(Event.match_id).distinct().all()
                ]
                match_ids = all_ids or None

            events_df = _fetch_events(session, match_ids)

            if events_df.empty:
                logger.info("No unprocessed events found — nothing to compute")
                return

            n_matches = events_df["match_id"].nunique()
            logger.info(
                "Computing metrics for %d events across %d matches",
                len(events_df), n_matches,
            )

            processed_match_ids = events_df["match_id"].unique().tolist()
            raw_events_df = _fetch_raw_events(session, processed_match_ids)

            player_df = compute_player_metrics(events_df)
            team_df   = compute_team_metrics(player_df, raw_events_df)

            rows = _persist(session, player_df, team_df)
            run.rows_inserted = rows

            logger.info(
                "Wrote %d player-metric rows, %d team-metric rows across %d matches",
                len(player_df), len(team_df), n_matches,
            )

            _apply_confidence_blending(session)
            _print_oop_rankings(session, team_df)
            _print_sanity_checks(session)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Compute off-ball feature metrics")
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass upstream pipeline status checks",
    )
    parser.add_argument(
        "--recompute-all", action="store_true",
        help="Recompute all existing matches (backfills new metric columns)",
    )
    args = parser.parse_args()
    run_pipeline(force=args.force, recompute_all=args.recompute_all)
