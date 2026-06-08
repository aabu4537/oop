"""Unit tests for ETL modules — no database or network required."""
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.etl.ingest_elo import _parse_elo_table
from src.etl.ingest_fifa import _load_rows
from src.etl.validate import validate_matches_df, validate_teams_df


# ---------------------------------------------------------------------------
# Elo scraper tests
# ---------------------------------------------------------------------------

SAMPLE_ELO_HTML = """
<html><body>
<table class="maintable">
  <tr><th>Rank</th><th>Team</th><th>Flag</th><th>Elo</th></tr>
  <tr><td>1</td><td>Spain</td><td></td><td>2104</td></tr>
  <tr><td>2</td><td>France</td><td></td><td>2060</td></tr>
  <tr><td>3</td><td>Brazil</td><td></td><td>2058</td></tr>
</table>
</body></html>
"""


def test_parse_elo_table_extracts_ratings():
    ratings = _parse_elo_table(SAMPLE_ELO_HTML)
    assert ratings["Spain"] == 2104.0
    assert ratings["France"] == 2060.0
    assert ratings["Brazil"] == 2058.0


def test_parse_elo_table_empty_html_returns_empty():
    ratings = _parse_elo_table("<html><body></body></html>")
    assert ratings == {}


def test_parse_elo_table_skips_malformed_rows():
    html = """
    <html><body><table class="maintable">
      <tr><th>Rank</th><th>Team</th><th>Flag</th><th>Elo</th></tr>
      <tr><td>1</td><td>Spain</td><td></td><td>not-a-number</td></tr>
      <tr><td>2</td><td>France</td><td></td><td>2060</td></tr>
    </table></body></html>
    """
    ratings = _parse_elo_table(html)
    assert "Spain" not in ratings
    assert ratings["France"] == 2060.0


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
