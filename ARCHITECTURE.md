# Architecture

## Configuration (`src/config.py`)
Single source of truth for all tuneable constants. `Settings` (pydantic-settings) covers infrastructure — database URL, StatsBomb competition/season IDs, log level — and is populated from `.env`. `ModelConfig` (frozen dataclass, `get_model_config()`) covers all algorithm magic numbers: Elo K-factors, home advantage, goal-difference cap, recency decay, OOP composite weights, rolling window size, and simulation parameters. No other file may hardcode these values; all layers import from this module.

## Ingestion layer (`src/etl/`)
Three idempotent ETL scripts populate the database. `ingest_fifa.py` fetches the martj42/international_results CSV and upserts teams and matches. `ingest_elo.py` reads from the `matches` table and writes Elo ratings to `teams`. `ingest_statsbomb.py` pulls StatsBomb event data (competitions → seasons → matches → events) via `statsbombpy`. Each script wraps its run in a `pipeline_run` context that writes an audit row to `pipeline_runs`; downstream scripts call `assert_upstream_ok()` before starting, halting with a clear error if a required predecessor stage last ran with `status = "failed"`. Pass `--force` to bypass this check for manual reruns. `loaders.py` contains shared idempotent upsert helpers. `validate.py` guards raw DataFrames before they touch the DB.

## Feature engineering (`src/features/compute_metrics.py`)
Reads events from the DB and produces per-player and per-team off-ball metrics, stored in `player_metrics` and `team_metrics`. Player-level outputs: `press_intensity`, `clearances_per90`, `interceptions_per90`, `ball_recoveries_per90`, `def_line_engagement` (composite, kept for backwards compat), and the in-possession-only metrics `run_frequency`/`space_creation_idx` (flagged, not used in the OOP model). Team-level adds `pressure_success_rate` (fraction of pressures followed by a team regain within 5 seconds, computed via temporal event-sequence analysis) and `oop_composite` (weighted OOP signal). `rolling_oop_composite()` returns the last-N-match rolling average for a team strictly before a given date, with no future leakage.

## Modeling layer (`src/models/`)
`interface.py` defines the `PredictionModel` ABC: any model must expose `predict_proba(home_team, away_team, neutral) → {"home": p, "draw": p, "away": p}`. `JoblibModel` wraps a saved sklearn/XGBoost `.joblib` artifact as a `PredictionModel`, accepting a pre-built team-stats dict so it has no DB dependency at inference time. `train.py` trains Logistic Regression and XGBoost models on a temporal train/test split (no data leakage), calibrates with isotonic regression, and saves artifacts under `artifacts/`. `predict.py` loads an artifact and upserts predictions to the `predictions` table. `features.py` builds the design matrix (Elo diff + team off-ball metrics, with median imputation for FIFA-only matches).

## Simulation engine (`src/simulation/engine.py`)
Poisson-based Monte Carlo tournament simulator, independent of the ML models. `goal_lambdas()` derives per-team expected goals from the Elo rating difference. `simulate_knockout_match()` handles extra time (reduced Poisson rate) and Elo-weighted penalties. `run_monte_carlo()` runs N simulations and returns stage-reach probabilities for every team. All numeric constants (`_MU`, extra-time rate, penalty tilt) are sourced from `ModelConfig`. The engine accepts a `PredictionModel` (from `src.models.interface`) as an optional drop-in for future ML-backed simulation; by default it uses the Elo/Poisson model.

## API (`src/api/`)
FastAPI application exposing REST endpoints over the data layer. Routers cover teams, matches, predictions, players, and Monte Carlo simulation (POST `/simulate`). Schemas are Pydantic v2 models. The simulation router constructs `Team` objects from request data and delegates to the simulation engine; it does not interact with the ML models directly.

## Database (`src/db/`)
PostgreSQL 16 managed by SQLAlchemy 2.0 ORM and Alembic migrations. Eight tables: `teams`, `players`, `matches`, `events`, `player_metrics`, `team_metrics`, `predictions`, `pipeline_runs`. All foreign keys cascade through `team_id` / `match_id`. `session.py` provides a context-manager `get_session()` that commits on clean exit and rolls back on exception.
