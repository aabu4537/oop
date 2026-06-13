"""Celery application instance.

Broker and backend both use Redis (separate DBs: 0 = broker, 1 = results).
Import this module to get the configured Celery app; never instantiate Celery
directly elsewhere so the configuration stays centralised here.

Usage::
    # Start a worker
    celery -A src.celery_app.celery_app worker --loglevel=info

    # Inspect registered tasks
    celery -A src.celery_app.celery_app inspect registered
"""
from celery import Celery

from src.config import get_settings


def _make_celery() -> Celery:
    settings = get_settings()
    broker = settings.redis_url
    # Results go to Redis DB 1 to keep them separate from the broker queue
    backend = settings.redis_url.rstrip("/0") + "/1" if settings.redis_url.endswith("/0") else settings.redis_url

    app = Celery(
        "football_analytics",
        broker=broker,
        backend=backend,
        include=["src.simulation.tasks"],
    )
    app.conf.update(
        result_expires=86400,       # 24-hour TTL on task results in Redis
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,    # enables STARTED state for in-progress tasks
        worker_prefetch_multiplier=1,  # one task at a time per worker process (long simulations)
    )
    return app


celery_app = _make_celery()
