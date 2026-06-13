"""Unit tests for ETL modules — no database or network required."""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.etl.ingest_elo import calculate_elos, elo_update, k_factor
from src.etl.ingest_fifa import _load_rows
from src.etl.validate import validate_matches_df, validate_teams_df


# ---------------------------------------------------------------------------
# Elo calculator tests
# ---------------------------------------------------------------------------

def test_k_factor_world_cup():
    assert k_factor("FIFA World Cup") == 60.0

def test_k_factor_continental():
    assert k_factor("UEFA Euro") == 50.0
    assert k_factor("Copa América") == 50.0
    assert k_factor("African Cup of Nations") == 50.0

def test_k_factor_qualifier():
    assert k_factor("FIFA World Cup qualification") == 40.0
    assert k_factor("UEFA Euro qualification") == 40.0

def test_k_factor_friendly():
    assert k_factor("Friendly") == 20.0
    assert k_factor(None) == 20.0


def test_elo_update_home_win_raises_home_rating():
    r_h, r_a = elo_update(1500.0, 1500.0, 2, 1, "Friendly")
    assert r_h > 1500.0
    assert r_a < 1500.0


def test_elo_update_away_win_raises_away_rating():
    r_h, r_a = elo_update(1500.0, 1500.0, 0, 1, "Friendly")
    assert r_h < 1500.0
    assert r_a > 1500.0


def test_elo_update_draw_favours_away_when_home_is_stronger():
    # Home team is much stronger, so a draw is a bad result for them
    r_h, r_a = elo_update(1800.0, 1500.0, 1, 1, "Friendly")
    assert r_h < 1800.0
    assert r_a > 1500.0


def test_elo_update_ratings_are_zero_sum():
    r_h0, r_a0 = 1600.0, 1400.0
    r_h1, r_a1 = elo_update(r_h0, r_a0, 3, 0, "FIFA World Cup")
    assert abs((r_h1 + r_a1) - (r_h0 + r_a0)) < 1e-9


def test_calculate_elos_new_teams_start_at_1500():
    class Row:
        def __init__(self, h, a, hs, as_, c):
            self.home_team, self.away_team = h, a
            self.home_score, self.away_score = hs, as_
            self.competition = c

    rows = [Row("Spain", "Germany", 2, 1, "Friendly")]
    ratings = calculate_elos(rows)
    assert "Spain" in ratings
    assert "Germany" in ratings
    assert ratings["Spain"] > 1500.0
    assert ratings["Germany"] < 1500.0


def test_calculate_elos_processes_chronologically():
    class Row:
        def __init__(self, h, a, hs, as_, c):
            self.home_team, self.away_team = h, a
            self.home_score, self.away_score = hs, as_
            self.competition = c

    # Spain beats Germany twice; Spain's rating should compound upward
    rows = [
        Row("Spain", "Germany", 2, 0, "Friendly"),
        Row("Spain", "Germany", 3, 0, "Friendly"),
    ]
    ratings = calculate_elos(rows)
    assert ratings["Spain"] > 1510.0  # meaningfully above start


# ---------------------------------------------------------------------------
# FIFA results loader tests
# ---------------------------------------------------------------------------

def _make_session_mock():
    session = MagicMock()
    # query().filter_by().first() returns None by default (no existing match)
    session.query.return_value.filter_by.return_value.first.return_value = None
    return session


def test_load_rows_inserts_new_matches():
    session = _make_session_mock()
    rows = [
        {"home_team": "Spain", "away_team": "Germany", "date": "2023-06-10",
         "home_score": "2", "away_score": "1", "tournament": "Friendly"},
        {"home_team": "Brazil", "away_team": "Argentina", "date": "2023-07-01",
         "home_score": "0", "away_score": "3", "tournament": "Copa America"},
    ]
    inserted = _load_rows(session, rows)
    assert inserted == 2


def test_load_rows_skips_malformed_date():
    session = _make_session_mock()
    rows = [{"home_team": "Spain", "away_team": "Germany", "date": "not-a-date",
             "home_score": "1", "away_score": "0", "tournament": ""}]
    inserted = _load_rows(session, rows)
    assert inserted == 0


def test_load_rows_skips_existing_match():
    session = _make_session_mock()
    # Simulate match already existing in DB
    session.query.return_value.filter_by.return_value.first.return_value = MagicMock()
    rows = [{"home_team": "Spain", "away_team": "Germany", "date": "2023-06-10",
             "home_score": "2", "away_score": "1", "tournament": "Friendly"}]
    inserted = _load_rows(session, rows)
    assert inserted == 0


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

def _good_matches_df():
    return pd.DataFrame({
        "match_id": [1, 2, 3],
        "home_team": ["Spain", "France", "Brazil"],
        "away_team": ["Germany", "Italy", "Argentina"],
        "match_date": ["2023-06-10", "2023-06-11", "2023-06-12"],
        "home_score": [2, 1, 0],
        "away_score": [1, 2, 3],
    })


def test_validate_matches_df_passes_good_data():
    df = _good_matches_df()
    assert validate_matches_df(df) is True


def test_validate_matches_df_fails_on_null_match_id():
    df = _good_matches_df()
    df.loc[0, "match_id"] = None
    with pytest.raises(ValueError, match="Validation failed"):
        validate_matches_df(df, raise_on_failure=True)


def test_validate_matches_df_fails_on_duplicate_match_id():
    df = _good_matches_df()
    df.loc[1, "match_id"] = df.loc[0, "match_id"]  # introduce duplicate
    with pytest.raises(ValueError, match="Validation failed"):
        validate_matches_df(df, raise_on_failure=True)


def test_validate_teams_df_passes():
    df = pd.DataFrame({"name": ["Spain", "Germany", "Brazil"]})
    assert validate_teams_df(df) is True


def test_validate_teams_df_fails_on_duplicate_name():
    df = pd.DataFrame({"name": ["Spain", "Spain", "Brazil"]})
    with pytest.raises(ValueError, match="Validation failed"):
        validate_teams_df(df, raise_on_failure=True)
