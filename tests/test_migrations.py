"""The Alembic migrations must build exactly the schema the models describe."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

import glucobalance.models  # noqa: F401  (registers every table on Base.metadata)
from glucobalance.db import Base, make_engine

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'migrations.db'}"


@pytest.fixture
def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_upgrade_to_head_matches_the_models(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, "head")

    engine = make_engine(database_url)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert differences == []


def test_downgrade_to_base_removes_every_table(alembic_config: Config, database_url: str) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = make_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert tables <= {"alembic_version"}


def test_there_is_a_single_head(alembic_config: Config) -> None:
    from alembic.script import ScriptDirectory

    assert len(ScriptDirectory.from_config(alembic_config).get_heads()) == 1
