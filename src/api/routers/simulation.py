from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.schemas.simulation import (
    SimulateJobResponse,
    SimulateJobStatusResponse,
    SimulateRequest,
    SimulateResponse,
)
from src.db.models import Team, TeamMetric
from src.db.session import get_db
from src.simulation.engine import (
    FALLBACK_GROUPS,
    WC_2026_GROUPS,
    Team as EngineTeam,
    load_groups_from_db,
    run_monte_carlo,
)

router = APIRouter(prefix="/simulate", tags=["simulation"])

# Celery is an optional runtime dependency — import at module level so that
# tests can patch these names; set to None when not installed.
try:
    from src.celery_app import celery_app
    from src.simulation.tasks import run_simulation_task
    _CELERY_AVAILABLE = True
except ImportError:
    celery_app = None          # type: ignore[assignment]
    run_simulation_task = None  # type: ignore[assignment]
    _CELERY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Synchronous endpoint — kept for backward compatibility and testing
# ---------------------------------------------------------------------------

@router.post("/wc2026", response_model=SimulateResponse)
def simulate_wc2026(n_sims: int = 10_000, seed: int = 42):
    """Run the WC 2026 simulation using live Elo + OOP data from the database.

    No request body needed — pulls team ratings and OOP composites automatically.
    Teams without StatsBomb coverage receive their confederation's average OOP boost.
    """
    try:
        groups = load_groups_from_db(WC_2026_GROUPS, FALLBACK_GROUPS)
    except Exception:
        groups = FALLBACK_GROUPS
    df = run_monte_carlo(groups, n_sims=n_sims, seed=seed)
    return SimulateResponse(results=df.to_dict(orient="records"), n_sims=n_sims)


@router.post("", response_model=SimulateResponse)
def simulate(req: SimulateRequest):
    """Run a Monte Carlo simulation synchronously. Returns results immediately."""
    groups = {
        label: [EngineTeam(name=t.name, elo=t.elo) for t in teams]
        for label, teams in req.groups.items()
    }
    seed = req.seed if req.seed is not None else 42
    df = run_monte_carlo(groups, n_sims=req.n_sims, seed=seed)
    return SimulateResponse(results=df.to_dict(orient="records"), n_sims=req.n_sims)


# ---------------------------------------------------------------------------
# Async endpoints — Celery task queue
# ---------------------------------------------------------------------------

@router.post("/async", response_model=SimulateJobResponse)
def simulate_async(req: SimulateRequest, db: Session = Depends(get_db)):
    """Publish a simulation job to the Celery task queue.

    Returns a job_id immediately. Poll GET /simulate/async/{job_id} for results.
    """
    if run_simulation_task is None:
        raise HTTPException(status_code=503, detail="Task queue (Celery) is not available.")

    # Determine whether any requested team has OOP composite data in the DB
    team_names = [t.name for teams in req.groups.values() for t in teams]
    has_oop_data: bool = (
        db.query(TeamMetric)
        .join(Team, Team.team_id == TeamMetric.team_id)
        .filter(Team.name.in_(team_names), TeamMetric.oop_composite.isnot(None))
        .first()
    ) is not None

    groups_data = {
        label: [{"name": t.name, "elo": t.elo} for t in teams]
        for label, teams in req.groups.items()
    }

    try:
        task = run_simulation_task.apply_async(
            kwargs={
                "groups_data": groups_data,
                "n_sims": req.n_sims,
                "seed": req.seed if req.seed is not None else 42,
                "has_oop_data": has_oop_data,
            }
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Task queue unavailable: {exc}. Is the Celery worker running?",
        ) from exc

    return SimulateJobResponse(job_id=task.id, status="queued")


@router.get("/async/{job_id}", response_model=SimulateJobStatusResponse)
def get_simulation_status(job_id: str):
    """Poll for the status and result of an async simulation job."""
    if celery_app is None:
        raise HTTPException(status_code=503, detail="Task queue (Celery) is not available.")

    try:
        task = celery_app.AsyncResult(job_id)
        state = task.state
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Task queue unavailable: {exc}",
        ) from exc

    if state == "SUCCESS":
        return SimulateJobStatusResponse(
            job_id=job_id,
            status="complete",
            result=task.result,
        )
    if state == "FAILURE":
        return SimulateJobStatusResponse(
            job_id=job_id,
            status="failed",
            error=str(task.result),
        )
    # PENDING → "queued", STARTED → "started", any other Celery state → lower-cased
    return SimulateJobStatusResponse(
        job_id=job_id,
        status="queued" if state == "PENDING" else state.lower(),
    )
