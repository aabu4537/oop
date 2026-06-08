# Football Analytics Platform

A full-stack football analytics platform that ingests StatsBomb event data, Elo ratings, and FIFA match results, engineers off-ball metrics, trains calibrated prediction models, and simulates World Cup tournaments via Monte Carlo methods.

## Architecture

```
StatsBomb / Elo / FIFA Results
        ↓
Python ETL (statsbombpy + requests)
        ↓
Data Validation (pandas expectations + JSON reports)
        ↓
PostgreSQL via Alembic migrations
        ↓
Feature Engineering (SQLAlchemy + Pandas)
        ↓
Modeling Layer (scikit-learn + XGBoost + Dixon-Coles)
        ↓
FastAPI REST Backend
        ↓
Streamlit Dashboard
        ↓
Docker + Railway (free tier)
```

## Project Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | ETL + PostgreSQL Schema | ✅ Complete |
| 2 | Feature Engineering (off-ball metrics) | ✅ Complete |
| 3 | ML Modeling (Logistic Regression + XGBoost) | 🔜 Planned |
| 4 | Monte Carlo Simulation Engine | 🔜 Planned |
| 5 | FastAPI Backend | 🔜 Planned |
| 6 | Streamlit Dashboard + Deployment | 🔜 Planned |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker (for Postgres) or a local PostgreSQL 16 instance

### Install Python 3.11 (macOS)

```bash
brew install python@3.11
```

### Install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/football-analytics.git
cd football-analytics
python3.11 -m pip install -e ".[dev]"
```

### Configure environment

```bash
cp .env.example .env
# Edit .env with your Postgres credentials if needed
```

### Start Postgres + run migrations

```bash
docker compose up db -d
docker compose run migrate
```

Or with a local Postgres instance:

```bash
alembic upgrade head
```

### Run the ETL pipeline

```bash
# Seed FIFA international match results (~45k matches, ~2 min)
python -m src.etl.ingest_fifa

# Seed Elo ratings (scrapes eloratings.net)
python -m src.etl.ingest_elo

# Seed StatsBomb event data (requires statsbombpy)
python -m src.etl.ingest_statsbomb
```

### Run feature engineering (Phase 2)

```bash
# Compute off-ball metrics for all unprocessed matches
python -m src.features.compute_metrics
```

### Run tests

```bash
pytest tests/ -v
```

With coverage:

```bash
pytest tests/ -v --cov=src/etl --cov-report=term-missing
```

---

## Database Schema

Eight tables managed via Alembic migrations:

| Table | Description |
|-------|-------------|
| `teams` | Team names, FIFA codes, Elo ratings |
| `players` | Player profiles linked to teams |
| `matches` | Match results with scores and competition context |
| `events` | StatsBomb event-level data (passes, pressures, carries, etc.) |
| `player_metrics` | Per-player per-match off-ball metrics |
| `team_metrics` | Aggregated team-level metrics per match |
| `predictions` | Model predictions with Brier Score + Log Loss |
| `pipeline_runs` | Audit log for every ETL execution |

---

## Folder Structure

```
football-analytics/
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── alembic/
│   └── versions/
│       └── 0001_initial_schema.py
├── src/
│   ├── config.py               # Pydantic settings + .env loading
│   ├── db/
│   │   ├── models.py           # SQLAlchemy ORM models (8 tables)
│   │   └── session.py          # Connection pool + get_db() dep
│   ├── etl/
│   │   ├── ingest_statsbomb.py # StatsBomb competitions → events
│   │   ├── ingest_elo.py       # Elo ratings scraper
│   │   ├── ingest_fifa.py      # FIFA results CSV loader
│   │   ├── loaders.py          # Idempotent upsert helpers
│   │   ├── validate.py         # DataFrame validation + JSON reports
│   │   └── pipeline_logger.py  # pipeline_runs audit context manager
│   ├── features/               # Phase 2 — off-ball metric pipeline
│   ├── models/                 # Phase 3 — ML models
│   ├── simulation/             # Phase 4 — Monte Carlo engine
│   └── api/                    # Phase 5 — FastAPI routers + schemas
├── streamlit_app/              # Phase 6 — dashboard
└── tests/
    └── test_etl.py             # 11 unit tests (no DB/network required)
```

---

## ETL Design

All loaders are **idempotent** — safe to re-run without producing duplicate rows. They use PostgreSQL `ON CONFLICT DO UPDATE / DO NOTHING` under the hood.

Every pipeline run writes an audit row to `pipeline_runs` with:
- `started_at` / `finished_at` timestamps
- `rows_inserted` / `rows_updated` counts
- `status`: `running` → `success` or `failed`
- `error_message` on failure

Data validation runs before each load and writes a JSON report to `ge_reports/`. Checks include null constraints, uniqueness, and value range assertions.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Ingestion | statsbombpy, requests, BeautifulSoup |
| Validation | pandas-based expectation suite |
| Database | PostgreSQL 16 + Alembic migrations |
| ORM | SQLAlchemy 2.0 |
| Modeling | scikit-learn, XGBoost, SHAP |
| Simulation | NumPy + scipy (Dixon-Coles Poisson) |
| API | FastAPI + Pydantic v2 |
| Dashboard | Streamlit + Plotly |
| Deployment | Docker + Railway free tier |
| CI/CD | GitHub Actions |
