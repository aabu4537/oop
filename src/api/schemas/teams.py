from uuid import UUID
from pydantic import BaseModel


class TeamOut(BaseModel):
    team_id: UUID
    name: str
    fifa_code: str | None
    elo_rating: float | None

    model_config = {"from_attributes": True}
