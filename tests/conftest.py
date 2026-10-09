"""Shared pytest fixtures: a fresh in-memory SQLite database for every test."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from glucobalance.db import Base, make_engine, make_session_factory


@pytest.fixture
def engine() -> Iterator[Engine]:
    """An in-memory SQLite engine with every table created."""
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session bound to the test engine, closed after the test."""
    with make_session_factory(engine)() as session:
        yield session
