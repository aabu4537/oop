from dataclasses import dataclass
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "football_analytics"
    postgres_user: str = "football"
    postgres_password: str = "changeme"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def async_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    statsbomb_competition_ids: str = "11,43"
    statsbomb_season_ids: str = "90"
    elo_base_url: str = "https://www.eloratings.net"

    redis_url: str = "redis://localhost:6379/0"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Model / algorithm constants — single source of truth for all magic numbers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    # ── Elo ──────────────────────────────────────────────────────────────────
    elo_start: float = 1500.0
    elo_home_advantage: float = 100.0   # points added to home team expected score
    elo_gd_cap: float = 2.0             # maximum goal-difference K multiplier
    elo_k_world_cup: float = 60.0       # K-factor for WC final tournament
    elo_k_continental: float = 50.0     # K-factor for major continental championships
    elo_k_qualifier: float = 40.0       # K-factor for WC / continental qualifying
    elo_k_friendly: float = 20.0        # K-factor for friendlies and all other matches
    elo_decay_rate: float = 0.10        # fraction pulled toward elo_start per year beyond window
    elo_decay_window_years: int = 4     # years before recency decay kicks in

    # ── OOP composite weights (must sum to 1.0) ───────────────────────────────
    oop_w_press: float = 0.35           # press_intensity weight
    oop_w_psr: float = 0.30             # pressure_success_rate weight
    oop_w_intercept: float = 0.20       # interceptions_per90 weight
    oop_w_recovery: float = 0.15        # ball_recoveries_per90 weight
    oop_rolling_window: int = 10        # last N StatsBomb matches for rolling OOP

    # ── Simulation ────────────────────────────────────────────────────────────
    sim_mu: float = 1.15                # geometric mean goals per team per match
    sim_extra_time_rate: float = 0.25   # expected goals per team in extra time
    sim_penalty_elo_factor: float = 0.04  # Elo tilt on penalty shootout win probability
    sim_penalty_elo_scale: float = 200.0  # Elo scale for penalty tilt (tanh denominator)
    sim_oop_elo_scale: float = 75.0       # Elo points per 1 std-dev of oop_composite


@lru_cache
def get_model_config() -> ModelConfig:
    return ModelConfig()
