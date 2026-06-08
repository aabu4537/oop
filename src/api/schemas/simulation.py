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


class SimulateResponse(BaseModel):
    results: list[dict[str, float | str]]
    n_sims: int
