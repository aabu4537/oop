import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy.orm import Session

from src.db.models import PipelineRun

logger = logging.getLogger(__name__)


class PipelineBlockedError(RuntimeError):
    """Raised when a required upstream pipeline stage last ran with status 'failed'."""


def assert_upstream_ok(session: Session, *stage_names: str, force: bool = False) -> None:
    """Halt if any named upstream stage's most recent run has status 'failed'.

    Pass force=True (--force CLI flag) to bypass the check for manual reruns.
    """
    if force:
        logger.warning("--force: skipping upstream pipeline status checks")
        return

    for stage in stage_names:
        latest: PipelineRun | None = (
            session.query(PipelineRun)
            .filter_by(pipeline_name=stage)
            .order_by(PipelineRun.started_at.desc())
            .first()
        )
        if latest is not None and latest.status == "failed":
            raise PipelineBlockedError(
                f"Upstream stage '{stage}' last run failed "
                f"(run_id={latest.run_id}, error={latest.error_message!r}). "
                "Fix the issue and rerun, or pass --force to bypass this check."
            )


@contextmanager
def pipeline_run(session: Session, name: str) -> Generator[PipelineRun, None, None]:
    """Context manager that writes a PipelineRun audit row for the duration of the ETL.

    Usage::

        with get_session() as session:
            with pipeline_run(session, "statsbomb_ingest") as run:
                run.rows_inserted += load_matches(session)
    """
    run = PipelineRun(pipeline_name=name, started_at=datetime.now(timezone.utc), status="running")
    session.add(run)
    session.flush()
    logger.info("Pipeline '%s' started (run_id=%s)", name, run.run_id)

    try:
        yield run
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        logger.info(
            "Pipeline '%s' finished — inserted=%d updated=%d",
            name,
            run.rows_inserted or 0,
            run.rows_updated or 0,
        )
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = str(exc)
        logger.error("Pipeline '%s' failed: %s", name, exc)
        raise
