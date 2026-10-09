"""Database setup: the declarative base, engine and session helpers (SQLAlchemy 2)."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Fixed constraint names, so Alembic migrations stay stable across databases.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Parent class of every ORM model; collects their tables in one MetaData."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str, *, echo: bool = False) -> Engine:
    """Create an engine. SQLite gets foreign keys on; in-memory SQLite shares one connection."""
    if not url.startswith("sqlite"):
        return create_engine(url, echo=echo)
    in_memory = url in ("sqlite://", "sqlite:///:memory:")
    engine = create_engine(
        url,
        echo=echo,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if in_memory else None,
    )
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a factory that opens sessions bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(engine: Engine) -> Generator[Session]:
    """Yield one session and close it afterwards (shape of a FastAPI dependency)."""
    with make_session_factory(engine)() as session:
        yield session
