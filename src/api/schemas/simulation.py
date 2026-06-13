from pydantic import BaseModel, Field


class SimTeam(BaseModel):
    name: str
    elo: float


class SimulateRequest(BaseModel):
    groups: dict[str, list[SimTeam]] = Field(
        ..., description="Group label → list of teams with name and elo"
    )
    n_sims: int = Field(10_000, ge=100, le=100_000)
    seed: int | None = None


# Synchronous response (POST /simulate)
class SimulateResponse(BaseModel):
    results: list[dict[str, float | str]]
    n_sims: int


# Async job responses (POST /simulate/async + GET /simulate/async/{job_id})
class SimulateJobResponse(BaseModel):
    job_id: str
    status: str  # "queued"


class SimulateJobResult(BaseModel):
    results: list[dict[str, float | str]]
    n_sims: int
    has_oop_data: bool


class SimulateJobStatusResponse(BaseModel):
    job_id: str
    status: str                     # "queued" | "started" | "complete" | "failed"
    result: SimulateJobResult | None = None
    error: str | None = None
