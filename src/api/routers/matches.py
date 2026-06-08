from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas.matches import MatchOut
from src.db.models import Match
from src.db.session import get_db

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchOut])
def list_matches(
    competition: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Match).order_by(Match.match_date.desc())
    if competition:
        stmt = stmt.where(Match.competition == competition)
    if season:
        stmt = stmt.where(Match.season == season)
    return db.execute(stmt).scalars().all()


@router.get("/{match_id}", response_model=MatchOut)
def get_match(match_id: UUID, db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return match
