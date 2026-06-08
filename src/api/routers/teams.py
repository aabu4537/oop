from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas.teams import TeamOut
from src.db.models import Team
from src.db.session import get_db

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db)):
    return db.execute(select(Team).order_by(Team.elo_rating.desc())).scalars().all()


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: UUID, db: Session = Depends(get_db)):
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team
