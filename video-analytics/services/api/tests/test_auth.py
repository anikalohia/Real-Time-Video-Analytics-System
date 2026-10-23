import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import hash_password, verify_password


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert verify_password("s3cret", h) is True
    assert verify_password("wrong", h) is False


def test_token_roundtrip():
    pytest.importorskip("jose")
    from auth import create_access_token, decode_token

    token = create_access_token("admin@example.com", "admin")
    payload = decode_token(token)
    assert payload["sub"] == "admin@example.com"
    assert payload["role"] == "admin"


def test_invalid_token_rejected():
    pytest.importorskip("jose")
    from fastapi import HTTPException
    from auth import decode_token

    with pytest.raises(HTTPException):
        decode_token("not-a-token")
