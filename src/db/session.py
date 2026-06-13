from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_size=10,       # persistent connections kept open (covers typical concurrent load)
    max_overflow=20,    # extra connections allowed beyond pool_size under burst traffic
    pool_timeout=30,    # seconds to wait for a connection before raising TimeoutError
    pool_pre_ping=True, # issues a lightweight SELECT 1 before handing out each connection;
                        # detects TCP connections killed by the DB or a firewall (e.g. after
                        # a Postgres restart or a cloud NAT idle timeout) so the pool never
                        # gives the application a connection that will immediately error
    pool_recycle=3600,  # force-replace connections older than 1hr to prevent server-side timeouts
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a session and always closes it."""
    with get_session() as session:
        yield session
