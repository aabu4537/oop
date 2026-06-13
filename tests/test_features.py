"""Unit tests for Phase 2 feature engineering — no DB or network required."""
import uuid
from datetime import date

import pandas as pd
import pytest

from src.features.compute_metrics import (
    compute_player_metrics,
    compute_team_metrics,
    rolling_oop_composite,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_events(rows: list[dict]) -> pd.DataFrame:
    defaults = {"match_id": None, "player_id": None, "team_id": None,
                "event_type": "Pass", "outcome": None, "minute": 45, "second": 0}
    records = [{**defaults, **r} for r in rows]
    return pd.DataFrame(records)


def _make_raw_events(rows: list[dict]) -> pd.DataFrame:
    """Raw events for PSR computation — no player_id, includes second."""
    defaults = {"match_id": None, "team_id": None,
                "event_type": "Pass", "minute": 45, "second": 0}
    records = [{**defaults, **r} for r in rows]
    return pd.DataFrame(records)


def _player_df(*rows) -> pd.DataFrame:
    """Build a minimal player_metrics DataFrame for team metric tests."""
    defaults = {
        "press_intensity": 0.0, "run_frequency": 0.0, "space_creation_idx": 0.0,
        "def_line_engagement": 0.0,
        "clearances_per90": 0.0, "interceptions_per90": 0.0, "ball_recoveries_per90": 0.0,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


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
    assert set(result.columns) >= {
        "press_intensity", "run_frequency", "clearances_per90",
        "interceptions_per90", "ball_recoveries_per90",
    }


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
    # 3 defensive events / 90 * 90 = 3.0
    assert row["def_line_engagement"] == pytest.approx(3.0)


def test_defensive_types_split_into_individual_columns():
    df = _make_events([
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Clearance",     "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Clearance",     "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Interception",  "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Ball Recovery", "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Ball Recovery", "minute": 90},
        {"match_id": MID, "player_id": P1, "team_id": T1, "event_type": "Ball Recovery", "minute": 90},
    ])
    result = compute_player_metrics(df)
    row = result.iloc[0]
    # 2 clearances / 90 * 90 = 2.0
    assert row["clearances_per90"] == pytest.approx(2.0)
    # 1 interception / 90 * 90 = 1.0
    assert row["interceptions_per90"] == pytest.approx(1.0)
    # 3 recoveries / 90 * 90 = 3.0
    assert row["ball_recoveries_per90"] == pytest.approx(3.0)
    # composite = sum = 6.0
    assert row["def_line_engagement"] == pytest.approx(6.0)


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
    for col in (
        "press_intensity", "run_frequency", "space_creation_idx", "def_line_engagement",
        "clearances_per90", "interceptions_per90", "ball_recoveries_per90",
    ):
        assert row[col] == pytest.approx(0.0), f"{col} should be 0 for unknown event type"


# ---------------------------------------------------------------------------
# compute_team_metrics
# ---------------------------------------------------------------------------

def test_team_metrics_empty_input():
    result = compute_team_metrics(pd.DataFrame())
    assert result.empty


def test_team_metrics_averages_players():
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 2.0, "run_frequency": 4.0, "space_creation_idx": 5.0,
         "def_line_engagement": 1.0, "clearances_per90": 0.5,
         "interceptions_per90": 0.3, "ball_recoveries_per90": 0.2},
        {"match_id": MID, "player_id": P2, "team_id": T1,
         "press_intensity": 4.0, "run_frequency": 2.0, "space_creation_idx": 3.0,
         "def_line_engagement": 3.0, "clearances_per90": 1.5,
         "interceptions_per90": 0.7, "ball_recoveries_per90": 0.8},
    )
    result = compute_team_metrics(player_df)
    row = result[result["team_id"] == T1].iloc[0]
    assert row["avg_press_intensity"] == pytest.approx(3.0)
    assert row["avg_run_frequency"]   == pytest.approx(3.0)
    assert row["avg_space_creation"]  == pytest.approx(4.0)
    assert row["def_line_engagement"] == pytest.approx(2.0)
    assert row["clearances_per90"]    == pytest.approx(1.0)
    assert row["interceptions_per90"] == pytest.approx(0.5)
    assert row["ball_recoveries_per90"] == pytest.approx(0.5)


def test_team_metrics_separate_teams():
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 2.0, "run_frequency": 1.0, "space_creation_idx": 1.0,
         "def_line_engagement": 1.0, "clearances_per90": 0.0,
         "interceptions_per90": 0.0, "ball_recoveries_per90": 0.0},
        {"match_id": MID, "player_id": P2, "team_id": T2,
         "press_intensity": 8.0, "run_frequency": 6.0, "space_creation_idx": 7.0,
         "def_line_engagement": 5.0, "clearances_per90": 1.0,
         "interceptions_per90": 2.0, "ball_recoveries_per90": 2.0},
    )
    result = compute_team_metrics(player_df)
    assert len(result) == 2
    t1 = result[result["team_id"] == T1].iloc[0]
    t2 = result[result["team_id"] == T2].iloc[0]
    assert t1["avg_press_intensity"] == pytest.approx(2.0)
    assert t2["avg_press_intensity"] == pytest.approx(8.0)


def test_oop_composite_formula():
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 10.0, "run_frequency": 0.0, "space_creation_idx": 0.0,
         "def_line_engagement": 3.0, "clearances_per90": 1.0,
         "interceptions_per90": 1.0, "ball_recoveries_per90": 1.0},
    )
    result = compute_team_metrics(player_df)
    row = result.iloc[0]
    # press_intensity=10.0, PSR=0.0 (no raw_events), interceptions=1.0, recoveries=1.0
    expected = 10.0 * 0.35 + 0.0 * 0.30 + 1.0 * 0.20 + 1.0 * 0.15
    assert row["oop_composite"] == pytest.approx(expected)


def test_oop_composite_excludes_clearances():
    """Clearances must NOT appear in the oop_composite formula."""
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 0.0, "run_frequency": 0.0, "space_creation_idx": 0.0,
         "def_line_engagement": 5.0, "clearances_per90": 5.0,
         "interceptions_per90": 0.0, "ball_recoveries_per90": 0.0},
    )
    result = compute_team_metrics(player_df)
    row = result.iloc[0]
    # clearances_per90=5 but that weight is 0 in the formula
    assert row["oop_composite"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# pressure_success_rate
# ---------------------------------------------------------------------------

def test_pressure_success_rate_basic():
    """One pressure followed by a team Ball Recovery within 5s → PSR = 1.0."""
    raw = _make_raw_events([
        {"match_id": MID, "team_id": T1, "event_type": "Pressure",      "minute": 1, "second": 0},
        {"match_id": MID, "team_id": T1, "event_type": "Ball Recovery",  "minute": 1, "second": 4},
    ])
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 1.0, "interceptions_per90": 0.0, "ball_recoveries_per90": 0.0},
    )
    result = compute_team_metrics(player_df, raw)
    assert result.iloc[0]["pressure_success_rate"] == pytest.approx(1.0)


def test_pressure_success_rate_outside_window():
    """Regain at 10s after pressure is outside the 5s window → PSR = 0.0."""
    raw = _make_raw_events([
        {"match_id": MID, "team_id": T1, "event_type": "Pressure",      "minute": 2, "second": 0},
        {"match_id": MID, "team_id": T1, "event_type": "Ball Recovery",  "minute": 2, "second": 10},
    ])
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 1.0, "interceptions_per90": 0.0, "ball_recoveries_per90": 0.0},
    )
    result = compute_team_metrics(player_df, raw)
    assert result.iloc[0]["pressure_success_rate"] == pytest.approx(0.0)


def test_pressure_success_rate_partial():
    """1 of 2 pressures succeeds → PSR = 0.5."""
    raw = _make_raw_events([
        # Pressure 1 at t=60 → regain at t=64 (within 5s) ✓
        {"match_id": MID, "team_id": T1, "event_type": "Pressure",      "minute": 1, "second": 0},
        {"match_id": MID, "team_id": T1, "event_type": "Ball Recovery",  "minute": 1, "second": 4},
        # Pressure 2 at t=120 → regain at t=130 (outside 5s) ✗
        {"match_id": MID, "team_id": T1, "event_type": "Pressure",      "minute": 2, "second": 0},
        {"match_id": MID, "team_id": T1, "event_type": "Ball Recovery",  "minute": 2, "second": 10},
    ])
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 2.0, "interceptions_per90": 0.0, "ball_recoveries_per90": 0.0},
    )
    result = compute_team_metrics(player_df, raw)
    assert result.iloc[0]["pressure_success_rate"] == pytest.approx(0.5)


def test_pressure_success_rate_interception_counts():
    """Interception (not just Ball Recovery) within 5s also counts as a regain."""
    raw = _make_raw_events([
        {"match_id": MID, "team_id": T1, "event_type": "Pressure",      "minute": 1, "second": 0},
        {"match_id": MID, "team_id": T1, "event_type": "Interception",  "minute": 1, "second": 3},
    ])
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 1.0, "interceptions_per90": 1.0, "ball_recoveries_per90": 0.0},
    )
    result = compute_team_metrics(player_df, raw)
    assert result.iloc[0]["pressure_success_rate"] == pytest.approx(1.0)


def test_pressure_success_rate_no_raw_events():
    """Without raw_events_df, PSR defaults to 0.0."""
    player_df = _player_df(
        {"match_id": MID, "player_id": P1, "team_id": T1,
         "press_intensity": 5.0, "interceptions_per90": 1.0, "ball_recoveries_per90": 1.0},
    )
    result = compute_team_metrics(player_df)
    assert result.iloc[0]["pressure_success_rate"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# rolling_oop_composite
# ---------------------------------------------------------------------------

def test_rolling_oop_composite_basic():
    df = pd.DataFrame([
        {"team_id": T1, "match_date": date(2024, 1, 1), "oop_composite": 1.0},
        {"team_id": T1, "match_date": date(2024, 2, 1), "oop_composite": 2.0},
        {"team_id": T1, "match_date": date(2024, 3, 1), "oop_composite": 3.0},  # on cutoff — excluded
    ])
    result = rolling_oop_composite(df, T1, date(2024, 3, 1), n=10)
    assert result == pytest.approx(1.5)  # mean(1.0, 2.0)


def test_rolling_oop_composite_respects_n():
    df = pd.DataFrame([
        {"team_id": T1, "match_date": date(2024, 1, 1), "oop_composite": 1.0},
        {"team_id": T1, "match_date": date(2024, 2, 1), "oop_composite": 3.0},
        {"team_id": T1, "match_date": date(2024, 3, 1), "oop_composite": 5.0},
        {"team_id": T1, "match_date": date(2024, 5, 1), "oop_composite": 0.0},  # cutoff
    ])
    # n=2: only last 2 matches before 2024-05-01 → March (5.0) and February (3.0)
    result = rolling_oop_composite(df, T1, date(2024, 5, 1), n=2)
    assert result == pytest.approx(4.0)


def test_rolling_oop_composite_returns_none_for_no_history():
    df = pd.DataFrame([
        {"team_id": T1, "match_date": date(2024, 1, 1), "oop_composite": 1.0},
    ])
    # T2 has no history
    result = rolling_oop_composite(df, T2, date(2024, 6, 1), n=10)
    assert result is None


def test_rolling_oop_composite_excludes_future_matches():
    df = pd.DataFrame([
        {"team_id": T1, "match_date": date(2024, 1, 1), "oop_composite": 1.0},
        {"team_id": T1, "match_date": date(2025, 1, 1), "oop_composite": 100.0},  # future
    ])
    result = rolling_oop_composite(df, T1, date(2024, 6, 1), n=10)
    assert result == pytest.approx(1.0)  # future match excluded
