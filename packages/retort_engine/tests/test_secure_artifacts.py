from __future__ import annotations

import json
import stat

import pytest
from cryptography.fernet import Fernet
from retort_engine.secure_artifacts import (
    PRIVATE_JSON_SCHEMA,
    SecureArtifactError,
    read_private_json,
    write_private_json,
)


def test_private_json_is_encrypted_authenticated_and_owner_only(tmp_path) -> None:
    target = tmp_path / "private.json"
    payload = {"token": "do-not-persist-in-clear-text", "status": "ready"}

    write_private_json(target, payload)

    raw = target.read_text(encoding="utf-8")
    envelope = json.loads(raw)
    assert envelope["schema"] == PRIVATE_JSON_SCHEMA
    assert payload["token"] not in raw
    assert read_private_json(target, allow_legacy=False) == payload
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_private_json_fails_closed_with_wrong_key(tmp_path, monkeypatch) -> None:
    target = tmp_path / "private.json"
    write_private_json(target, {"private": "value"})
    monkeypatch.setenv("RETORT_ARTIFACT_MASTER_KEY", Fernet.generate_key().decode())

    with pytest.raises(SecureArtifactError, match="authentication failed"):
        read_private_json(target, allow_legacy=False)


def test_private_json_rejects_plaintext_when_legacy_is_disabled(tmp_path) -> None:
    target = tmp_path / "legacy.json"
    target.write_text('{"private":"legacy"}', encoding="utf-8")

    with pytest.raises(SecureArtifactError, match="unencrypted"):
        read_private_json(target, allow_legacy=False)
