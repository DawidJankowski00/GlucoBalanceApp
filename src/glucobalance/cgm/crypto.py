"""Encrypting the LibreLinkUp follower password and token before they reach the database.

Fernet (from the ``cryptography`` package) is symmetric, authenticated encryption: the same
key encrypts and decrypts, and a tampered or wrongly keyed value fails loudly instead of
decrypting to garbage. The key lives only in the ``GBA_CGM_SECRET_KEY`` environment variable,
so a copy of the database alone does not reveal the password.

Make a key with ``uv run python -m glucobalance.cgm.crypto``.
"""

from cryptography.fernet import Fernet, InvalidToken


class SecretKeyError(Exception):
    """No key is configured, or the stored value was encrypted with a different key."""


class SecretBox:
    """Encrypts and decrypts short strings with one Fernet key."""

    def __init__(self, key: str | None) -> None:
        if not key:
            raise SecretKeyError("Set GBA_CGM_SECRET_KEY to store CGM passwords.")
        try:
            self._fernet = Fernet(key.encode())
        except ValueError:
            raise SecretKeyError("GBA_CGM_SECRET_KEY is not a valid Fernet key.") from None

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            raise SecretKeyError(
                "A stored CGM secret cannot be read with the current key. Enter the password again."
            ) from None

    def __repr__(self) -> str:
        return "SecretBox(<hidden>)"


def new_key() -> str:
    return Fernet.generate_key().decode()


if __name__ == "__main__":  # pragma: no cover
    print(f"GBA_CGM_SECRET_KEY={new_key()}")
