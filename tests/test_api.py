from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.db.session import get_db

NULL_UUID = "00000000-0000-0000-0000-000000000001"

_GROUPS_SINGLE = {
    "A": [
        {"name": "France", "elo": 2003},
        {"name": "Germany", "elo": 1988},
        {"name": "Brazil", "elo": 2045},
        {"name": "Argentina", "elo": 2142},
    ]
}

_GROUPS_DOUBLE = {
    **_GROUPS_SINGLE,
    "B": [
        {"name": "Spain", "elo": 1975},
        {"name": "Portugal", "elo": 1960},
        {"name": "England", "elo": 1950},
        {"name": "Italy", "elo": 1932},
    ],
}


def _mock_db():
    mock = MagicMock()
    mock.execute.return_value.scalars.return_value.all.return_value = []
    mock.get.return_value = None
    yield mock


app.dependency_overrides[get_db] = _mock_db

client = TestClient(app)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /teams
# ---------------------------------------------------------------------------

def test_list_teams_empty():
    r = client.get("/teams")
    assert r.status_code == 200
    assert r.json() == []


def test_get_team_not_found():
    r = client.get(f"/teams/{NULL_UUID}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Team not found"


# ---------------------------------------------------------------------------
# /matches
# ---------------------------------------------------------------------------

def test_list_matches_empty():
    r = client.get("/matches")
    assert r.status_code == 200
    assert r.json() == []


def test_list_matches_with_filters():
    r = client.get("/matches?competition=World%20Cup&season=2022")
    assert r.status_code == 200


def test_get_match_not_found():
    r = client.get(f"/matches/{NULL_UUID}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Match not found"


# ---------------------------------------------------------------------------
# /predictions
# ---------------------------------------------------------------------------

def test_list_predictions_empty():
    r = client.get("/predictions")
    assert r.status_code == 200
    assert r.json() == []


def test_list_predictions_by_model_version():
    r = client.get("/predictions?model_version=xgb_v1.0")
    assert r.status_code == 200


def test_get_predictions_for_match_empty():
    r = client.get(f"/predictions/{NULL_UUID}")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# /players
# ---------------------------------------------------------------------------

def test_get_player_metrics_empty():
    r = client.get(f"/players/{NULL_UUID}/metrics")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# /simulate
# ---------------------------------------------------------------------------

def test_simulate_single_group():
    r = client.post("/simulate", json={"groups": _GROUPS_SINGLE, "n_sims": 200, "seed": 0})
    assert r.status_code == 200
    data = r.json()
    assert data["n_sims"] == 200
    assert len(data["results"]) == 4
    assert all("team" in row for row in data["results"])
    assert all("champion" in row for row in data["results"])


def test_simulate_multiple_groups():
    r = client.post("/simulate", json={"groups": _GROUPS_DOUBLE, "n_sims": 500, "seed": 42})
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) == 8


def test_simulate_probabilities_sum_to_one():
    r = client.post("/simulate", json={"groups": _GROUPS_SINGLE, "n_sims": 1000, "seed": 7})
    assert r.status_code == 200
    champion_probs = [row["champion"] for row in r.json()["results"]]
    assert abs(sum(champion_probs) - 1.0) < 0.01


def test_simulate_n_sims_too_low():
    r = client.post("/simulate", json={"groups": _GROUPS_SINGLE, "n_sims": 50})
    assert r.status_code == 422


def test_simulate_n_sims_too_high():
    r = client.post("/simulate", json={"groups": _GROUPS_SINGLE, "n_sims": 200_000})
    assert r.status_code == 422


def test_simulate_missing_groups():
    r = client.post("/simulate", json={"n_sims": 500})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /simulate/async — Celery async endpoints (Celery mocked, no broker needed)
# ---------------------------------------------------------------------------

def test_simulate_async_returns_job_id():
    mock_task = MagicMock()
    mock_task.id = "test-job-id-abc123"
    with patch("src.api.routers.simulation.run_simulation_task") as mock_fn:
        mock_fn.apply_async.return_value = mock_task
        r = client.post("/simulate/async", json={"groups": _GROUPS_SINGLE, "n_sims": 200, "seed": 0})
    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] == "test-job-id-abc123"
    assert data["status"] == "queued"


def test_simulate_async_status_queued():
    mock_async_result = MagicMock()
    mock_async_result.state = "PENDING"
    with patch("src.api.routers.simulation.celery_app") as mock_celery:
        mock_celery.AsyncResult.return_value = mock_async_result
        r = client.get("/simulate/async/test-job-id-abc123")
    assert r.status_code == 200
    data = r.json()
    assert data["job_id"] == "test-job-id-abc123"
    assert data["status"] == "queued"
    assert data["result"] is None


def test_simulate_async_status_complete():
    mock_async_result = MagicMock()
    mock_async_result.state = "SUCCESS"
    mock_async_result.result = {
        "results": [{"team": "France", "champion": 0.35}],
        "n_sims": 200,
        "has_oop_data": False,
    }
    with patch("src.api.routers.simulation.celery_app") as mock_celery:
        mock_celery.AsyncResult.return_value = mock_async_result
        r = client.get("/simulate/async/test-job-id-abc123")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "complete"
    assert data["result"]["has_oop_data"] is False
    assert data["result"]["n_sims"] == 200


def test_simulate_async_status_failed():
    mock_async_result = MagicMock()
    mock_async_result.state = "FAILURE"
    mock_async_result.result = ValueError("simulation crashed")
    with patch("src.api.routers.simulation.celery_app") as mock_celery:
        mock_celery.AsyncResult.return_value = mock_async_result
        r = client.get("/simulate/async/bad-job-id")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "failed"
    assert data["result"] is None
    assert "error" in data
