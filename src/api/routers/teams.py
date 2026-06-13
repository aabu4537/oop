from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas.teams import TeamOut
from src.cache import cache
from src.db.models import Team
from src.db.session import get_db

router = APIRouter(prefix="/teams", tags=["teams"])

_TEAMS_LIST_KEY = "teams:list"
_TEAMS_TTL = 3600  # 1 hour


@router.get("", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db)):
    """Return all teams sorted by Elo rating (descending).

    Cache-aside: checks Redis first; on miss queries PostgreSQL and caches
    the result for 1 hour.  Cache is busted when ingest_elo completes
    (cache.invalidate('teams:*')) or expires automatically after 1hr.
    """
    cached = cache.get(_TEAMS_LIST_KEY)
    if cached is not None:
        # Return list of dicts — FastAPI validates each against TeamOut schema
        return cached

    teams = db.execute(select(Team).order_by(Team.elo_rating.desc())).scalars().all()
    # Serialise via TeamOut so UUIDs become strings before JSON storage
    serialised = [TeamOut.model_validate(t).model_dump(mode="json") for t in teams]
    cache.set(_TEAMS_LIST_KEY, serialised, ttl=_TEAMS_TTL)
    return teams


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: UUID, db: Session = Depends(get_db)):
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team
