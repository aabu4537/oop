from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas.predictions import PredictionOut
from src.db.models import Prediction
from src.db.session import get_db

router = APIRouter(prefix="/predictions", tags=["predictions"])


@router.get("", response_model=list[PredictionOut])
def list_predictions(
    model_version: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Prediction).order_by(Prediction.predicted_at.desc())
    if model_version:
        stmt = stmt.where(Prediction.model_version == model_version)
    return db.execute(stmt).scalars().all()


@router.get("/{match_id}", response_model=list[PredictionOut])
def get_predictions_for_match(match_id: UUID, db: Session = Depends(get_db)):
    return db.execute(
        select(Prediction).where(Prediction.match_id == match_id)
    ).scalars().all()
