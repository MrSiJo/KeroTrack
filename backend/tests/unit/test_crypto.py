"""argon2id hash + verify."""

from __future__ import annotations

from kerotrack.security.crypto import hash_password, verify_password


def test_hash_password_returns_argon2id_format() -> None:
    h = hash_password("hunter2")
    assert h.startswith("$argon2id$")
    assert h != "hunter2"


def test_verify_password_round_trip() -> None:
    h = hash_password("password123")
    assert verify_password("password123", h) is True


def test_verify_password_wrong_password() -> None:
    h = hash_password("right")
    assert verify_password("wrong", h) is False


def test_verify_password_malformed_hash_returns_false() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


def test_verify_password_empty_hash_returns_false() -> None:
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False


def test_hashes_are_unique() -> None:
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    assert verify_password("same", a)
    assert verify_password("same", b)
