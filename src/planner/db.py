"""Database connection setup.

PostGIS was not usable here: it has no clean silent-install path on Windows (the
EDB installer's Application Stack Builder is interactive-only, and there's no winget
package for it). This uses plain PostgreSQL instead, with geometry stored as GeoJSON in
JSONB columns rather than native PostGIS geometry types. This is a real, working choice,
not a stand-in: every spatial computation this API serves (H3 membership, reach
polygons, optimization, Huff allocation) already happens in the validated Python
pipeline elsewhere in this project -- the database's job here is to serve those
precomputed, already-tested results, not to run live spatial SQL (ST_Within, ST_Intersects,
etc.), so PostGIS's server-side spatial indexing was never a hard requirement.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (copy .env.example to .env and fill it in)")
    return create_engine(url, pool_pre_ping=True)


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session, always closed after the request."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
