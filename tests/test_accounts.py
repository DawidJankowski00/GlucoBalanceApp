"""Sign-up, password hashing and authentication."""

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import (
    AccountError,
    authenticate,
    hash_password,
    register,
    verify_password,
)

PASSWORD = "correct horse battery"


def test_hash_is_argon2_and_salted() -> None:
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first.startswith("$argon2id$")
    assert first != second
    assert PASSWORD not in first


def test_verify_password() -> None:
    hashed = hash_password(PASSWORD)
    assert verify_password(PASSWORD, hashed)
    assert not verify_password("wrong password!", hashed)
    assert not verify_password(PASSWORD, "not a hash")


def test_register_stores_a_hash_not_the_password(session: Session) -> None:
    user = register(session, " Ann@Example.com ", "Ann", PASSWORD)
    assert user.id is not None
    assert user.email == "ann@example.com"
    assert user.password_hash is not None
    assert PASSWORD not in user.password_hash


def test_register_rejects_a_duplicate_email_ignoring_case(session: Session) -> None:
    register(session, "ann@example.com", "Ann", PASSWORD)
    with pytest.raises(AccountError, match="already exists"):
        register(session, "ANN@example.com", "Other", PASSWORD)


@pytest.mark.parametrize(
    ("email", "name", "password", "message"),
    [
        ("not-an-email", "Ann", PASSWORD, "email"),
        ("ann@example.com", "  ", PASSWORD, "name"),
        ("ann@example.com", "Ann", "short", "at least 10"),
    ],
)
def test_register_validates_input(
    session: Session, email: str, name: str, password: str, message: str
) -> None:
    with pytest.raises(AccountError, match=message):
        register(session, email, name, password)


def test_authenticate(session: Session) -> None:
    user = register(session, "ann@example.com", "Ann", PASSWORD)
    assert authenticate(session, "ANN@example.com", PASSWORD) == user
    assert authenticate(session, "ann@example.com", "wrong password!") is None
    assert authenticate(session, "nobody@example.com", PASSWORD) is None


def test_users_without_a_password_cannot_log_in(session: Session) -> None:
    from glucobalance.models import User

    session.add(User(email="demo@example.com", display_name="Demo"))
    session.flush()
    assert authenticate(session, "demo@example.com", "") is None
    assert authenticate(session, "demo@example.com", PASSWORD) is None
