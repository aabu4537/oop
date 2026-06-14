from uuid import UUID
from datetime import date
from pydantic import BaseModel


class MatchOut(BaseModel):
    match_id: UUID
    home_team_id: UUID | None
    away_team_id: UUID | None
    home_team_name: str | None = None
    away_team_name: str | None = None
    match_date: date
    competition: str | None
    season: str | None
    home_score: int | None
    away_score: int | None

    model_config = {"from_attributes": False}
