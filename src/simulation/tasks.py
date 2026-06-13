"""Celery tasks for Monte Carlo simulation.

Tasks are JSON-serialisable: Team objects are passed as plain dicts
({name, elo}) and reconstructed inside the task body.
"""
from src.celery_app import celery_app
from src.simulation.engine import Team, run_monte_carlo


@celery_app.task(name="simulation.run")
def run_simulation_task(
    groups_data: dict[str, list[dict]],
    n_sims: int,
    seed: int,
    has_oop_data: bool = False,
) -> dict:
    """Run a full Monte Carlo tournament simulation.

    Args:
        groups_data:  Serialised groups — {"A": [{"name": "Spain", "elo": 2104}, ...], ...}
        n_sims:       Number of Monte Carlo iterations.
        seed:         RNG seed for reproducibility.
        has_oop_data: Whether any team in the request has OOP composite data in the DB.
                      Passed through to the result for the caller to surface in the UI.

    Returns:
        {"results": [...], "n_sims": int, "has_oop_data": bool}
    """
    groups = {
        label: [Team(name=t["name"], elo=t["elo"]) for t in teams]
        for label, teams in groups_data.items()
    }
    df = run_monte_carlo(groups, n_sims=n_sims, seed=seed)
    return {
        "results": df.to_dict(orient="records"),
        "n_sims": n_sims,
        "has_oop_data": has_oop_data,
    }
