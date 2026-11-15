"""SQLAlchemy engine and session helpers (SQLite for the hackathon)."""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_Session = None


def init_engine(url: str | None = None):
    """Create the engine. Tests pass 'sqlite://' for an in-memory DB."""
    global _engine, _Session
    url = url or get_settings().database_url
    # timeout: background case threads may write at the same time; wait instead of "database is locked".
    kwargs = {"connect_args": {"check_same_thread": False, "timeout": 15}} if url.startswith("sqlite") else {}
    _engine = create_engine(url, **kwargs)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine():
    return _engine or init_engine()


@contextmanager
def session_scope():
    """Commit on success, roll back on error. Use: with session_scope() as s: ..."""
    if _Session is None:
        init_engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
