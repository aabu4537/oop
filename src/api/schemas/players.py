from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


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
