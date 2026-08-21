"""Tests for the AI employee account credential store."""

from __future__ import annotations

import stat

import pytest

from modstore_server.ai_employee_account_secrets import (
    delete_secret,
    read_secret,
    secret_path_for,
    validate_qq_secret,
    write_secret,
)


def test_secret_round_trip_is_atomic_and_owner_only(tmp_path, monkeypatch) -> None:
    root = tmp_path / "credentials"
    monkeypatch.setenv("MODSTORE_AI_ACCOUNT_SECRETS_DIR", str(root))
    secret = {"app_id": "123", "app_secret": "top-secret", "bot_token": "bot-token"}

    target = write_secret(platform="QQ", account_id=7, external_id="123", secret=secret)

    assert target == root / "qq" / "7.json"
    assert read_secret(platform="qq", account_id=7) == secret
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert list(target.parent.glob("*.tmp")) == []


def test_read_supports_legacy_flat_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_AI_ACCOUNT_SECRETS_DIR", str(tmp_path))
    target = secret_path_for("email", 2)
    target.parent.mkdir(parents=True)
    target.write_text('{"password":"legacy"}\n', encoding="utf-8")

    assert read_secret(platform="email", account_id=2) == {"password": "legacy"}


def test_delete_reports_presence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_AI_ACCOUNT_SECRETS_DIR", str(tmp_path))
    write_secret(platform="email", account_id=3, external_id="u@example.com", secret={"p": "x"})

    assert delete_secret(platform="email", account_id=3) is True
    assert delete_secret(platform="email", account_id=3) is False


@pytest.mark.parametrize("platform", ["", "../qq", "QQ/other", "space value"])
def test_secret_path_rejects_unsafe_platform(platform: str) -> None:
    with pytest.raises(ValueError):
        secret_path_for(platform, 1)


def test_validate_qq_secret_requires_all_credentials() -> None:
    with pytest.raises(ValueError, match="bot_token"):
        validate_qq_secret({"app_id": "1", "app_secret": "s"})

    validate_qq_secret({"app_id": "1", "app_secret": "s", "bot_token": "t"})
