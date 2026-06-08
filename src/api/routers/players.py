from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas.players import PlayerMetricOut
from src.db.models import PlayerMetric
from src.db.session import get_db

router = APIRouter(prefix="/players", tags=["players"])


@router.get("/{player_id}/metrics", response_model=list[PlayerMetricOut])
def get_player_metrics(player_id: UUID, db: Session = Depends(get_db)):
    return db.execute(
        select(PlayerMetric).where(PlayerMetric.player_id == player_id)
    ).scalars().all()
