"""Fernet encryption of the follower password and token."""

import pytest

from glucobalance.cgm.crypto import SecretBox, SecretKeyError, new_key


def test_a_secret_round_trips_and_is_not_stored_in_plain_text() -> None:
    box = SecretBox(new_key())

    stored = box.encrypt("hunter2")

    assert "hunter2" not in stored
    assert box.decrypt(stored) == "hunter2"


def test_encrypting_twice_gives_different_ciphertexts() -> None:
    box = SecretBox(new_key())

    assert box.encrypt("same") != box.encrypt("same")


def test_a_different_key_cannot_read_the_secret() -> None:
    stored = SecretBox(new_key()).encrypt("hunter2")

    with pytest.raises(SecretKeyError, match="Enter the password again"):
        SecretBox(new_key()).decrypt(stored)


@pytest.mark.parametrize("key", [None, ""])
def test_a_missing_key_is_reported(key: str | None) -> None:
    with pytest.raises(SecretKeyError, match="GBA_CGM_SECRET_KEY"):
        SecretBox(key)


def test_a_malformed_key_is_reported() -> None:
    with pytest.raises(SecretKeyError, match="not a valid"):
        SecretBox("not-a-key")


def test_the_key_never_shows_in_repr() -> None:
    key = new_key()

    assert key not in repr(SecretBox(key))
