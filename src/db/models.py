import uuid
from datetime import datetime, date

from sqlalchemy import (
    UUID, BigInteger, Boolean, Column, Date, DateTime, Float,
    ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


def _uuid():
    return str(uuid.uuid4())


class Team(Base):
    __tablename__ = "teams"

    team_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    fifa_code = Column(String(3))
    elo_rating = Column(Float)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    players = relationship("Player", back_populates="team")
    home_matches = relationship("Match", foreign_keys="Match.home_team_id", back_populates="home_team")
    away_matches = relationship("Match", foreign_keys="Match.away_team_id", back_populates="away_team")
    team_metrics = relationship("TeamMetric", back_populates="team")

    __table_args__ = (Index("idx_teams_elo", "elo_rating"),)


class Player(Base):
    __tablename__ = "players"

    player_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.team_id"))
    name = Column(String(150), nullable=False)
    position = Column(String(50))
    nationality = Column(String(100))
    statsbomb_id = Column(Integer, unique=True)

    team = relationship("Team", back_populates="players")
    events = relationship("Event", back_populates="player")
    player_metrics = relationship("PlayerMetric", back_populates="player")

    __table_args__ = (Index("idx_players_team", "team_id"),)


class Match(Base):
    __tablename__ = "matches"

    match_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    home_team_id = Column(UUID(as_uuid=True), ForeignKey("teams.team_id"))
    away_team_id = Column(UUID(as_uuid=True), ForeignKey("teams.team_id"))
    match_date = Column(Date, nullable=False)
    competition = Column(String(100))
    season = Column(String(20))
    home_score = Column(Integer)
    away_score = Column(Integer)
    neutral = Column(Boolean, default=False)
    statsbomb_id = Column(Integer, unique=True)

    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_matches")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_matches")
    events = relationship("Event", back_populates="match")
    player_metrics = relationship("PlayerMetric", back_populates="match")
    team_metrics = relationship("TeamMetric", back_populates="match")
    predictions = relationship("Prediction", back_populates="match")

    __table_args__ = (
        Index("idx_matches_date", "match_date"),
        Index("idx_matches_teams", "home_team_id", "away_team_id"),
    )


class Event(Base):
    __tablename__ = "events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.match_id"))
    player_id = Column(UUID(as_uuid=True), ForeignKey("players.player_id"), nullable=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.team_id"))
    event_type = Column(String(50), nullable=False)
    minute = Column(Integer)
    second = Column(Integer)
    location = Column(JSONB)
    outcome = Column(String(50))
    statsbomb_id = Column(UUID(as_uuid=True), unique=True)

    match = relationship("Match", back_populates="events")
    player = relationship("Player", back_populates="events")

    __table_args__ = (
        Index("idx_events_match", "match_id"),
        Index("idx_events_type", "event_type"),
        Index("idx_events_player", "player_id"),
    )


class PlayerMetric(Base):
    __tablename__ = "player_metrics"

    metric_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    player_id = Column(UUID(as_uuid=True), ForeignKey("players.player_id"))
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.match_id"))
    press_intensity = Column(Float)
    run_frequency = Column(Float)
    space_creation_idx = Column(Float)
    def_line_engagement = Column(Float)
    computed_at = Column(DateTime, server_default=func.now())

    player = relationship("Player", back_populates="player_metrics")
    match = relationship("Match", back_populates="player_metrics")

    __table_args__ = (UniqueConstraint("player_id", "match_id", name="uq_player_match_metric"),)


class TeamMetric(Base):
    __tablename__ = "team_metrics"

    metric_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.team_id"))
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.match_id"))
    avg_press_intensity = Column(Float)
    avg_space_creation = Column(Float)
    avg_run_frequency = Column(Float)
    def_line_engagement = Column(Float)
    computed_at = Column(DateTime, server_default=func.now())

    team = relationship("Team", back_populates="team_metrics")
    match = relationship("Match", back_populates="team_metrics")

    __table_args__ = (UniqueConstraint("team_id", "match_id", name="uq_team_match_metric"),)


class Prediction(Base):
    __tablename__ = "predictions"

    pred_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID(as_uuid=True), ForeignKey("matches.match_id"))
    model_version = Column(String(50), nullable=False)
    home_win_prob = Column(Float, nullable=False)
    draw_prob = Column(Float, nullable=False)
    away_win_prob = Column(Float, nullable=False)
    brier_score = Column(Float)
    log_loss = Column(Float)
    predicted_at = Column(DateTime, server_default=func.now())

    match = relationship("Match", back_populates="predictions")

    __table_args__ = (
        Index("idx_predictions_match", "match_id"),
        Index("idx_predictions_model", "model_version"),
    )


class PipelineRun(Base):
    """Audit log for every ETL pipeline execution."""
    __tablename__ = "pipeline_runs"

    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_name = Column(String(100), nullable=False)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime)
    status = Column(String(20), nullable=False, default="running")  # running | success | failed
    rows_inserted = Column(Integer, default=0)
    rows_updated = Column(Integer, default=0)
    error_message = Column(Text)

    __table_args__ = (Index("idx_pipeline_runs_name_status", "pipeline_name", "status"),)
