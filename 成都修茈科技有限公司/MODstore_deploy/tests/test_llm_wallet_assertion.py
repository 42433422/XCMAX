"""Synthetic tests for the unconnected wallet service assertion contract."""

import hashlib
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from modstore_server.llm_wallet_assertion import issue_assertion, verify_assertion


def verify(token, keys, *, operation, **overrides):
    expected = {
        "user_id": 7,
        "request_digest": hashlib.sha256(b"synthetic request").hexdigest(),
        "server_max_amount_cents": 25,
    }
    expected.update(overrides)
    return verify_assertion(token, keys, operation=operation, **expected)


@pytest.fixture
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def make_assertion(private, **overrides):
    values = {
        "key_id": "synthetic",
        "user_id": 7,
        "operation": "preauthorize",
        "request_digest": hashlib.sha256(b"synthetic request").hexdigest(),
        "max_amount_cents": 25,
    }
    values.update(overrides)
    return issue_assertion(private, **values)


def test_assertion_binds_account_and_request(keypair):
    private, public = keypair
    claims = verify(make_assertion(private), {"synthetic": public}, operation="preauthorize")
    assert (claims["sub"], claims["max_amount_cents"]) == ("7", 25)
    assert claims["exp"] - claims["iat"] == 60


def test_signatures_and_key_rotation_fail_closed(keypair):
    private, public = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_assertion(private)
    for trusted in ({}, {"synthetic": other.public_key()}):
        with pytest.raises(ValueError, match="invalid assertion"):
            verify(token, trusted, operation="preauthorize")
    assert verify(token, {"synthetic": public}, operation="preauthorize")["sub"] == "7"


@pytest.mark.parametrize(
    "override",
    [
        {"user_id": 8},
        {"request_digest": hashlib.sha256(b"changed").hexdigest()},
        {"server_max_amount_cents": 24},
    ],
)
def test_cross_subject_or_changed_request_or_limit_fails(keypair, override):
    private, public = keypair
    with pytest.raises(ValueError, match="invalid assertion"):
        verify(make_assertion(private), {"synthetic": public}, operation="preauthorize", **override)


@pytest.mark.parametrize(
    "field,value",
    [
        ("aud", "wrong-audience"),
        ("iss", "wrong-issuer"),
        ("exp", 1),
        ("sub", "0"),
        ("max_amount_cents", -1),
        ("request_digest", "incorrect"),
        ("jti", "invalid"),
    ],
)
def test_wrong_claims_are_rejected(keypair, field, value):
    private, public = keypair
    claims = jwt.decode(make_assertion(private), options={"verify_signature": False})
    claims[field] = value
    token = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "synthetic"})
    with pytest.raises(ValueError, match="invalid assertion"):
        verify(token, {"synthetic": public}, operation="preauthorize")


def test_wrong_operation_and_excess_lifetime_are_rejected(keypair):
    private, public = keypair
    token = make_assertion(private)
    with pytest.raises(ValueError):
        verify(token, {"synthetic": public}, operation="settle")
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["exp"] = int(time.time()) + 300
    long_lived = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "synthetic"})
    with pytest.raises(ValueError):
        verify(long_lived, {"synthetic": public}, operation="preauthorize")


@pytest.mark.parametrize("operation", ["settle", "release"])
def test_finalization_requires_reservation(keypair, operation):
    private, public = keypair
    with pytest.raises(ValueError):
        make_assertion(private, operation=operation)
    token = make_assertion(private, operation=operation, reservation_id="synthetic-hold")
    assert (
        verify(token, {"synthetic": public}, operation=operation)["reservation_id"]
        == "synthetic-hold"
    )
