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
PostgreSQL 16 managed by SQLAlchemy 2.0 ORM and Alembic migrations. Eight tables: `teams`, `players`, `matches`, `events`, `player_metrics`, `team_metrics`, `predictions`, `pipeline_runs`. All foreign keys cascade through `team_id` / `match_id`. `session.py` provides a context-manager `get_session()` that commits on clean exit and rolls back on exception. Connection pool: `pool_size=10`, `max_overflow=20`, `pool_timeout=30`, `pool_pre_ping=True` (issues `SELECT 1` before each checkout to detect stale TCP connections killed by DB restarts or NAT idle timeouts), `pool_recycle=3600`.

## Infrastructure (`docker-compose.yml`, `nginx.conf`)
Nginx sits in front of the FastAPI container as a reverse proxy: `GET /api/*` is stripped to `/*` and forwarded to `api:8000`; a separate `listen 8501` block proxies Streamlit with WebSocket upgrade headers. Rate limiting is applied at the nginx layer: `limit_req_zone` at 10 req/s per source IP with a burst of 20. Redis 7 runs as a sidecar for both the Celery broker (DB 0) and result backend (DB 1), and the application-level cache (`src/cache.py`). The Celery worker runs the same Docker image as the API, overriding only the CMD.

---

## System Design Decisions

### CAP Theorem — CP over AP
This system prioritises **Consistency over Availability**. Prediction and Elo data must be correct: serving a stale Elo rating (AP behaviour) could silently bias simulation outputs in a way that's hard to detect. Under a network partition we prefer to return an error rather than a possibly-wrong response. PostgreSQL's ACID guarantees and synchronous writes enforce this. The Redis cache layer is a performance optimisation, not a consistency boundary — all cache misses fall back to PostgreSQL, and TTLs (1hr for teams) bound the staleness window.

### Cache-aside vs Write-through
**Cache-aside** was chosen over write-through for three reasons: (1) this is a read-heavy workload — the ingest pipeline writes infrequently (once per ETL run) while the API reads constantly; (2) write-through would couple the ETL pipeline to the cache, adding a failure mode to an already-complex ingestion chain; (3) the 1hr TTL provides bounded staleness automatically, and explicit invalidation via `cache.invalidate("teams:*")` handles the case where ingest completes and fresh Elo ratings need to surface immediately. Under cache-aside, the DB is always the source of truth and the cache is a transparent acceleration layer.

### Task Queue for Simulation (Async Pattern)
Monte Carlo simulation with 10,000–100,000 iterations is CPU-bound and takes 1–30 seconds. Handling it synchronously in a uvicorn thread blocks the event loop and burns WSGI worker slots under concurrent load. The Celery + Redis task queue decouples request acceptance from computation: `POST /simulate/async` returns a `job_id` in milliseconds, and Celery workers (horizontally scalable) process the simulation independently. `worker_prefetch_multiplier=1` prevents a single worker from hoarding multiple long-running tasks and causing head-of-line blocking. The 24hr TTL on results (`result_expires=86400`) balances storage cost against the window in which a client might poll for results.

### Denormalisation — `oop_composite` Pre-computed in `team_metrics`
`oop_composite` is a weighted sum of four per-90 metrics. It could be computed at query time via a SQL expression, but pre-computing it at ETL time (written by `compute_metrics.py`) avoids repeating the formula across every query, ensures consistency (the weights come from `ModelConfig`, not embedded in SQL), and enables a partial index (`idx_team_metrics_oop WHERE oop_composite IS NOT NULL`) that efficiently finds teams with OOP data. The trade-off is that weight changes require re-running the feature pipeline; this is acceptable because weights are researcher-controlled configuration, not user-driven parameters.

### Identified Scaling Bottlenecks and Mitigations
| Bottleneck | Current state | Mitigation path |
|---|---|---|
| `events` table reads | Single Postgres instance; full-table scans during PSR computation | Add read replica; route `_fetch_raw_events` to replica; composite index `idx_events_team_type` reduces scan width |
| Simulation throughput | Single Celery worker, 4 concurrent processes | Add `celery_worker` replicas via `docker compose up --scale celery_worker=N`; stateless tasks scale horizontally without coordination |
| Cache stampede on cold start | All teams requests hit DB simultaneously after cache expires | Use `SETNX`-based lock before population (cache warm-up on startup), or stagger TTLs with random jitter |
| Feature matrix JOIN on large events table | `LEFT JOIN team_metrics` with two join conditions per match | Materialised view or denormalised `match_features` table populated by `compute_metrics.py` |
