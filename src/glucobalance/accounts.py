"""Accounts: sign-up, password hashing and checking a login.

Passwords are hashed with Argon2id (the ``argon2-cffi`` library). A hash is a one-way
fingerprint with a random salt, so a stolen database does not reveal the passwords.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from glucobalance.models import User
from glucobalance.repositories import UserRepository

MIN_PASSWORD_LENGTH = 10

_hasher = PasswordHasher()
# Checked when the email is unknown, so a login takes similar time either way.
_DUMMY_HASH = _hasher.hash("dummy password for timing")


class AccountError(ValueError):
    """The sign-up input is not acceptable. The message is safe to show to the user."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register(session: Session, email: str, display_name: str, password: str) -> User:
    """Create a user. Raises ``AccountError`` for a bad email, name or password, or a duplicate."""
    email = normalize_email(email)
    display_name = display_name.strip()
    local, _, domain = email.partition("@")
    if not local or "." not in domain or " " in email:
        raise AccountError("Enter a valid email address.")
    if not display_name:
        raise AccountError("Enter your name.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    users = UserRepository(session)
    if users.get_by_email(email) is not None:
        raise AccountError("An account with this email already exists.")
    return users.add(
        User(email=email, display_name=display_name, password_hash=hash_password(password))
    )


def authenticate(session: Session, email: str, password: str) -> User | None:
    """Return the user when the email and password match, otherwise ``None``."""
    user = UserRepository(session).get_by_email(normalize_email(email))
    if user is None or user.password_hash is None:
        verify_password(password, _DUMMY_HASH)
        return None
    return user if verify_password(password, user.password_hash) else None
