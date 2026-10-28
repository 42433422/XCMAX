"""Cryptographic service-assertion contract for the optional model wallet.

Callers must obtain the account subject from the authoritative identity source.
PAT authentication and wallet transaction/replay enforcement are separate.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "modstore-llm-auth"
AUDIENCE = "modstore-llm-wallet"
OPERATIONS = frozenset({"preauthorize", "settle", "release"})
MAX_LIFETIME_SECONDS = 60
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_signing_key(path: str) -> rsa.RSAPrivateKey:
    """Load a dedicated private key without relaxing the credential file policy."""
    source = Path(path)
    if os.name == "posix" and source.stat().st_mode & 0o077:
        raise ValueError("invalid signing key permissions")
    try:
        key = serialization.load_pem_private_key(source.read_bytes(), password=None)
    except UnsupportedAlgorithm as exc:
        raise ValueError("invalid signing key") from exc
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("invalid signing key")
    return key


def issue_assertion(
    private_key: Any,
    *,
    key_id: str,
    user_id: int,
    operation: str,
    request_digest: str,
    max_amount_cents: int,
    reservation_id: str | None = None,
) -> str:
    """Sign an assertion from a previously authenticated, authorized identity."""
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "operation": operation,
        "request_digest": request_digest,
        "max_amount_cents": max_amount_cents,
        "reservation_id": reservation_id,
        "jti": secrets.token_hex(16),
        "iat": now,
        "exp": now + MAX_LIFETIME_SECONDS,
    }
    _validate_claims(claims, operation)
    if not key_id or len(key_id) > 64:
        raise ValueError("invalid assertion")
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": key_id})


def _validate_claims(claims: dict[str, Any], operation: str) -> None:
    sub = claims.get("sub")
    amount = claims.get("max_amount_cents")
    iat, exp = claims.get("iat"), claims.get("exp")
    reservation = claims.get("reservation_id")
    if (
        operation not in OPERATIONS
        or claims.get("operation") != operation
        or not isinstance(sub, str)
        or not sub.isascii()
        or not sub.isdecimal()
        or int(sub) <= 0
        or not isinstance(claims.get("request_digest"), str)
        or not _SHA256.fullmatch(claims["request_digest"])
        or type(amount) is not int
        or amount <= 0
        or type(iat) is not int
        or type(exp) is not int
        or exp <= iat
        or exp - iat > MAX_LIFETIME_SECONDS
        or not isinstance(claims.get("jti"), str)
        or not re.fullmatch(r"[0-9a-f]{32}", claims["jti"])
        or (operation == "preauthorize" and reservation is not None)
        or (
            operation != "preauthorize"
            and (not isinstance(reservation, str) or not reservation or len(reservation) > 64)
        )
    ):
        raise ValueError("invalid assertion")


def verify_assertion(
    token: str,
    trusted_keys: dict[str, Any],
    *,
    operation: str,
    user_id: int,
    request_digest: str,
    server_max_amount_cents: int,
) -> dict[str, Any]:
    """Verify a trusted expected context; callers must still enforce replay and ownership."""
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        if not isinstance(key_id, str) or key_id not in trusted_keys:
            raise ValueError("invalid assertion")
        claims = jwt.decode(
            token,
            trusted_keys[key_id],
            algorithms=["RS256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["iss", "aud", "sub", "iat", "exp", "jti"]},
        )
        _validate_claims(claims, operation)
        if (
            type(user_id) is not int
            or claims["sub"] != str(user_id)
            or claims["request_digest"] != request_digest
            or type(server_max_amount_cents) is not int
            or server_max_amount_cents <= 0
            or claims["max_amount_cents"] > server_max_amount_cents
        ):
            raise ValueError("invalid assertion")
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("invalid assertion") from exc
