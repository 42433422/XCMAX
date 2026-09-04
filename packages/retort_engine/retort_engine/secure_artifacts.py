"""Encrypted persistence for private Retort execution artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

PRIVATE_JSON_SCHEMA = "retort.private_json.encrypted/v1"


class SecureArtifactError(RuntimeError):
    """Raised when private evidence cannot be encrypted or authenticated."""


def _fernet() -> Fernet:
    raw = (
        os.environ.get("RETORT_ARTIFACT_MASTER_KEY")
        or os.environ.get("MODSTORE_LLM_MASTER_KEY")
        or ""
    ).strip()
    if not raw:
        raise SecureArtifactError(
            "RETORT_ARTIFACT_MASTER_KEY is required for private execution artifacts"
        )
    try:
        return Fernet(raw.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise SecureArtifactError("invalid Retort artifact encryption key") from exc


def write_private_json(path: str | Path, payload: Any) -> Path:
    """Atomically persist JSON as an authenticated Fernet ciphertext envelope."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    ciphertext = _fernet().encrypt(plaintext).decode("ascii")
    envelope = json.dumps(
        {"schema": PRIVATE_JSON_SCHEMA, "ciphertext": ciphertext},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(envelope)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
        target.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def read_private_json(path: str | Path, *, allow_legacy: bool = True) -> dict[str, Any]:
    """Read an encrypted artifact, optionally accepting pre-encryption JSON."""

    target = Path(path)
    try:
        envelope = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecureArtifactError(f"private artifact is unreadable: {target}") from exc
    if not isinstance(envelope, dict):
        raise SecureArtifactError("private artifact root must be an object")
    if envelope.get("schema") != PRIVATE_JSON_SCHEMA:
        if allow_legacy:
            return envelope
        raise SecureArtifactError("unencrypted private artifact rejected")
    ciphertext = str(envelope.get("ciphertext") or "").strip()
    if not ciphertext:
        raise SecureArtifactError("encrypted private artifact has no ciphertext")
    try:
        plaintext = _fernet().decrypt(ciphertext.encode("ascii"))
        payload = json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, UnicodeError, json.JSONDecodeError) as exc:
        raise SecureArtifactError("private artifact authentication failed") from exc
    if not isinstance(payload, dict):
        raise SecureArtifactError("decrypted private artifact root must be an object")
    return payload
