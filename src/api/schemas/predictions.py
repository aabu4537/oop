from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class PredictionOut(BaseModel):
    pred_id: UUID
    match_id: UUID | None
    model_version: str
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    brier_score: float | None
    log_loss: float | None
    predicted_at: datetime | None

    model_config = {"from_attributes": True}
