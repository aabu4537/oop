from fastapi import APIRouter

from src.api.schemas.simulation import SimulateRequest, SimulateResponse
from src.simulation.engine import Team as EngineTeam, run_monte_carlo

router = APIRouter(prefix="/simulate", tags=["simulation"])


@router.post("", response_model=SimulateResponse)
def simulate(req: SimulateRequest):
    groups = {
        label: [EngineTeam(name=t.name, elo=t.elo) for t in teams]
        for label, teams in req.groups.items()
    }
    seed = req.seed if req.seed is not None else 42
    df = run_monte_carlo(groups, n_sims=req.n_sims, seed=seed)
    return SimulateResponse(results=df.to_dict(orient="records"), n_sims=req.n_sims)
