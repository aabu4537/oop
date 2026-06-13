from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class TeamOut(BaseModel):
    team_id: UUID
    name: str
    fifa_code: str | None
    elo_rating: float | None

    model_config = {"from_attributes": True}


class TeamMetricOut(BaseModel):
    metric_id: UUID
    match_id: UUID | None
    avg_press_intensity: float | None
    pressure_success_rate: float | None
    interceptions_per90: float | None
    ball_recoveries_per90: float | None
    clearances_per90: float | None
    oop_composite: float | None
    computed_at: datetime | None

    model_config = {"from_attributes": True}
