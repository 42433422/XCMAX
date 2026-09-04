from __future__ import annotations

import pytest
from fastapi import HTTPException

from modstore_server import webhook_subscription_api as api


def test_webhook_crypto_fails_closed_without_master_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "fernet_configured", lambda: False)

    with pytest.raises(HTTPException) as exc_info:
        api._encrypt_secret_or_reject("customer-secret")

    assert exc_info.value.status_code == 503


def test_webhook_crypto_encrypts_before_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "fernet_configured", lambda: True)
    monkeypatch.setattr(api, "encrypt_secret", lambda value: f"encrypted:{len(value)}")

    assert api._encrypt_secret_or_reject("customer-secret") == "encrypted:15"
    assert api._encrypt_secret_or_reject("") == ""
