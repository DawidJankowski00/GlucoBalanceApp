from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from glucobalance.db import Base, get_session, make_engine


def test_session_can_query(session: Session) -> None:
    assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_sqlite_enforces_foreign_keys(engine: Engine) -> None:
    # SQLite ignores foreign keys unless this pragma is switched on per connection.
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_in_memory_sqlite_is_shared_across_connections() -> None:
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (x INTEGER)"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM t")).scalar_one() == 0


def test_constraint_names_follow_the_naming_convention() -> None:
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"


def test_get_session_yields_a_session_and_closes_it(engine: Engine) -> None:
    sessions = get_session(engine)
    session = next(sessions)
    assert isinstance(session, Session)
    sessions.close()
    assert not session.in_transaction()
