"""Unit tests for Phase 2 feature engineering — no DB or network required."""
import uuid

import pandas as pd
import pytest

from src.features.compute_metrics import compute_player_metrics, compute_team_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_events(rows: list[dict]) -> pd.DataFrame:
    defaults = {"match_id": None, "player_id": None, "team_id": None,
                "event_type": "Pass", "outcome": None, "minute": 45}
    records = [{**defaults, **r} for r in rows]
    return pd.DataFrame(records)


MID = uuid.uuid4()   # match
P1  = uuid.uuid4()   # player 1
P2  = uuid.uuid4()   # player 2
T1  = uuid.uuid4()   # team 1
T2  = uuid.uuid4()   # team 2


# ---------------------------------------------------------------------------
# compute_player_metrics
# ---------------------------------------------------------------------------

def test_empty_input_returns_empty_df():
    result = compute_player_metrics(pd.DataFrame())
    assert result.empty
    assert set(result.columns) >= {"press_intensity", "run_frequency"}


def test_pressure_events_map_to_press_intensity():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Pressure", "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Pressure", "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Pass",     "minute": 90},
    ])
    result = compute_player_metrics(df)
    row = result[(result["player_id"] == P1)].iloc[0]
    # 2 pressures / 90 min * 90 = 2.0
    assert row["press_intensity"] == pytest.approx(2.0)
    assert row["run_frequency"] == pytest.approx(0.0)


def test_carry_events_map_to_run_frequency():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Carry", "minute": 45},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Carry", "minute": 45},
    ])
    result = compute_player_metrics(df)
    row = result.iloc[0]
    # 2 carries / 45 min * 90 = 4.0
    assert row["run_frequency"] == pytest.approx(4.0)


def test_space_creation_includes_carries_and_dribbles():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Carry",   "outcome": None,       "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Dribble", "outcome": "Complete", "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Dribble", "outcome": "Incomplete", "minute": 90},
    ])
    result = compute_player_metrics(df)
    row = result.iloc[0]
    # 1 carry + 1 complete dribble = 2 / 90 * 90 = 2.0
    assert row["space_creation_idx"] == pytest.approx(2.0)


def test_defensive_types_map_to_def_line_engagement():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Clearance",    "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Interception", "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Ball Recovery","minute": 90},
    ])
    result = compute_player_metrics(df)
    row = result.iloc[0]
    assert row["def_line_engagement"] == pytest.approx(3.0)


def test_minute_zero_does_not_raise():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Pressure", "minute": 0},
    ])
    result = compute_player_metrics(df)
    # minute clipped to 1, so 1 pressure / 1 * 90 = 90.0
    assert result.iloc[0]["press_intensity"] == pytest.approx(90.0)


def test_multiple_players_computed_independently():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Pressure", "minute": 90},
        {"match_id": MID, "player_id": P2, "team_id": T2, "event_type": "Carry",    "minute": 45},
    ])
    result = compute_player_metrics(df)
    assert len(result) == 2
    p1_row = result[result["player_id"] == P1].iloc[0]
    p2_row = result[result["player_id"] == P2].iloc[0]
    assert p1_row["press_intensity"] == pytest.approx(1.0)
    assert p2_row["run_frequency"] == pytest.approx(2.0)


def test_unknown_event_type_contributes_zero_to_all_metrics():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Shot", "minute": 60},
    ])
    result = compute_player_metrics(df)
    row = result.iloc[0]
    for col in ("press_intensity", "run_frequency", "space_creation_idx", "def_line_engagement"):
        assert row[col] == pytest.approx(0.0), f"{col} should be 0 for unknown event type"


# ---------------------------------------------------------------------------
# compute_team_metrics
# ---------------------------------------------------------------------------

def test_team_metrics_empty_input():
    result = compute_team_metrics(pd.DataFrame())
    assert result.empty


def test_team_metrics_averages_players():
    player_df = pd.DataFrame([
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 2.0, "run_frequency": 4.0, "space_creation_idx": 5.0, "def_line_engagement": 1.0},
        {"match_id": MID, "player_id": P2, "team_id": T1,
         "press_intensity": 4.0, "run_frequency": 2.0, "space_creation_idx": 3.0, "def_line_engagement": 3.0},
    ])
    result = compute_team_metrics(player_df)
    row = result[result["team_id"] == T1].iloc[0]
    assert row["avg_press_intensity"] == pytest.approx(3.0)
    assert row["avg_run_frequency"]   == pytest.approx(3.0)
    assert row["avg_space_creation"]  == pytest.approx(4.0)
    assert row["def_line_engagement"] == pytest.approx(2.0)


def test_team_metrics_separate_teams():
    player_df = pd.DataFrame([
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 2.0, "run_frequency": 1.0, "space_creation_idx": 1.0, "def_line_engagement": 1.0},
        {"match_id": MID, "player_id": P2, "team_id": T2,
         "press_intensity": 8.0, "run_frequency": 6.0, "space_creation_idx": 7.0, "def_line_engagement": 5.0},
    ])
    result = compute_team_metrics(player_df)
    assert len(result) == 2
    t1 = result[result["team_id"] == T1].iloc[0]
    t2 = result[result["team_id"] == T2].iloc[0]
    assert t1["avg_press_intensity"] == pytest.approx(2.0)
    assert t2["avg_press_intensity"] == pytest.approx(8.0)
