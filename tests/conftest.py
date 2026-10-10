"""Shared pytest fixtures: a fresh in-memory SQLite database for every test."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

import glucobalance.models  # noqa: F401  (registers every table on Base.metadata)
from glucobalance.config import Settings
from glucobalance.db import Base, make_engine, make_session_factory
from glucobalance.main import create_app


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


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """A test client for an app that uses the test database."""
    settings = Settings(environment="test", secret_key="test-secret-key", llm_provider="none")
    with TestClient(create_app(settings, engine)) as client:
        yield client
