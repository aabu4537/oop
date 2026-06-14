from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class PlayerOut(BaseModel):
    player_id: UUID
    name: str
    team_name: str | None = None
    position: str | None = None
    nationality: str | None = None

    model_config = {"from_attributes": False}


class PlayerMetricOut(BaseModel):
    metric_id: UUID
    player_id: UUID | None
    match_id: UUID | None
    press_intensity: float | None
    run_frequency: float | None
    space_creation_idx: float | None
    def_line_engagement: float | None
    computed_at: datetime | None

    model_config = {"from_attributes": True}
