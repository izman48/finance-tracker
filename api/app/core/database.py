from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


@lru_cache
def get_engine():
    """Create and cache the database engine."""
    from app.core.config import get_settings

    settings = get_settings()
    
    # Adjust pool settings based on database type
    if settings.database_url.startswith("sqlite"):
        return create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
        )
    else:
        return create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )


def get_session_local():
    """Get sessionmaker bound to engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db():
    """Dependency that provides a database session."""
    SessionLocal = get_session_local()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
