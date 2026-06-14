from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas.matches import MatchOut
from src.db.models import Match, Team
from src.db.session import get_db

router = APIRouter(prefix="/matches", tags=["matches"])


def _row_to_match_out(m: Match, home_name: str | None, away_name: str | None) -> MatchOut:
    return MatchOut(
        match_id=m.match_id,
        home_team_id=m.home_team_id,
        away_team_id=m.away_team_id,
        home_team_name=home_name,
        away_team_name=away_name,
        match_date=m.match_date,
        competition=m.competition,
        season=m.season,
        home_score=m.home_score,
        away_score=m.away_score,
    )


@router.get("", response_model=list[MatchOut])
def list_matches(
    competition: Optional[str] = Query(None),
    season: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    HT = Team.__table__.alias("ht")
    AT = Team.__table__.alias("at_")
    stmt = (
        select(
            Match,
            HT.c.name.label("home_team_name"),
            AT.c.name.label("away_team_name"),
        )
        .outerjoin(HT, Match.home_team_id == HT.c.team_id)
        .outerjoin(AT, Match.away_team_id == AT.c.team_id)
        .order_by(Match.match_date.desc())
        .limit(limit)
    )
    if competition:
        stmt = stmt.where(Match.competition == competition)
    if season:
        stmt = stmt.where(Match.season == season)

    results = db.execute(stmt).all()
    return [_row_to_match_out(row.Match, row.home_team_name, row.away_team_name) for row in results]


@router.get("/{match_id}", response_model=MatchOut)
def get_match(match_id: UUID, db: Session = Depends(get_db)):
    HT = Team.__table__.alias("ht")
    AT = Team.__table__.alias("at_")
    row = db.execute(
        select(
            Match,
            HT.c.name.label("home_team_name"),
            AT.c.name.label("away_team_name"),
        )
        .outerjoin(HT, Match.home_team_id == HT.c.team_id)
        .outerjoin(AT, Match.away_team_id == AT.c.team_id)
        .where(Match.match_id == match_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return _row_to_match_out(row.Match, row.home_team_name, row.away_team_name)
