"""Routing-layer authorization boundary tests for the desktop install-receipt route.

Covers ``POST /api/desktop/update-install-receipts/report``
(``app.fastapi_routes.desktop_runtime.report_update_install_receipt``), the
endpoint the Electron main process calls after a stable update or a rollback.

Acceptance criteria exercised here:

* non-desktop runtime is rejected before any market call;
* desktop runtime does not accept non-loopback callers;
* malformed ``status`` values are rejected with a 422;
* a desktop session without a bound market token is rejected with a 409 and no
  proxying happens;
* the happy path forwards the exact receipt body to the market endpoint with
  ``POST`` and the caller's token, without making a real network call.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.desktop_runtime import router as desktop_router

_RECEIPT_PATH = "/api/desktop/update-install-receipts/report"
_MARKET_PATH = "/api/update-installations/receipts"
_MARKET_MODULE = "app.fastapi_routes.market_account"


def _valid_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "installation_id": "install-123",
        "idempotency_key": "idem-abc",
        "channel": "stable",
        "platform": "darwin",
        "target_version": "1.2.3",
        "target_build_sha": "aaaa1111",
        "installed_version": "1.2.3",
        "installed_build_sha": "aaaa1111",
        "status": "installed",
        "error": "",
        "source": "desktop_ota",
    }
    body.update(overrides)
    return body


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(desktop_router)
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


class TestUnprivilegedCallersRejected:
    def test_non_desktop_runtime_is_rejected(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.fastapi_routes.desktop_runtime.is_desktop_mode", lambda: False
        )
        proxy = AsyncMock()
        monkeypatch.setattr(f"{_MARKET_MODULE}._proxy_json", proxy)

        with TestClient(app) as client:
            response = client.post(_RECEIPT_PATH, json=_valid_body())

        assert response.status_code == 403
        proxy.assert_not_awaited()

    def test_non_loopback_client_is_rejected(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.fastapi_routes.desktop_runtime.is_desktop_mode", lambda: True
        )
        proxy = AsyncMock()
        monkeypatch.setattr(f"{_MARKET_MODULE}._proxy_json", proxy)

        # A remote address that is not 127.0.0.1 / ::1 / testclient.
        with TestClient(app, client=("10.0.0.5", 50000)) as client:
            response = client.post(_RECEIPT_PATH, json=_valid_body())

        assert response.status_code == 403
        proxy.assert_not_awaited()


class TestValidationAndTokenBoundary:
    def test_invalid_status_is_rejected(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.fastapi_routes.desktop_runtime.is_desktop_mode", lambda: True
        )
        proxy = AsyncMock()
        monkeypatch.setattr(f"{_MARKET_MODULE}._proxy_json", proxy)

        with TestClient(app) as client:
            response = client.post(_RECEIPT_PATH, json=_valid_body(status="bogus"))

        assert response.status_code == 422
        proxy.assert_not_awaited()

    def test_missing_market_token_returns_conflict(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.fastapi_routes.desktop_runtime.is_desktop_mode", lambda: True
        )
        # The route imports ``latest_session_market_token`` from the module, so
        # patching that module attribute is what actually takes effect.
        monkeypatch.setattr(
            f"{_MARKET_MODULE}.latest_session_market_token", lambda *a, **k: None
        )
        proxy = AsyncMock()
        monkeypatch.setattr(f"{_MARKET_MODULE}._proxy_json", proxy)

        with TestClient(app) as client:
            response = client.post(_RECEIPT_PATH, json=_valid_body())

        assert response.status_code == 409
        proxy.assert_not_awaited()


class TestAuthorizedHappyPath:
    def test_receipt_forwarded_with_exact_body(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.fastapi_routes.desktop_runtime.is_desktop_mode", lambda: True
        )
        monkeypatch.setattr(
            f"{_MARKET_MODULE}.latest_session_market_token", lambda *a, **k: "market-token"
        )
        proxy = AsyncMock(return_value={"ok": True, "marker": "proxied"})
        monkeypatch.setattr(f"{_MARKET_MODULE}._proxy_json", proxy)

        body = _valid_body(
            target_build_sha="bbbb2222",
            installed_build_sha="bbbb2222",
            status="installed",
        )

        with TestClient(app) as client:
            response = client.post(_RECEIPT_PATH, json=body)

        assert response.status_code == 200
        assert response.json() == {"ok": True, "marker": "proxied"}
        proxy.assert_awaited_once()

        args, kwargs = proxy.await_args
        assert args == ("POST", _MARKET_PATH)
        assert kwargs["authorization"] == "market-token"

        forwarded = kwargs["json_body"]
        assert forwarded["target_build_sha"] == "bbbb2222"
        assert forwarded["installed_build_sha"] == "bbbb2222"
        # The forwarded body must preserve the field identity, not collapse it.
        assert forwarded["target_build_sha"] == forwarded["installed_build_sha"]
        assert forwarded["installation_id"] == "install-123"
        assert forwarded["idempotency_key"] == "idem-abc"
        assert forwarded["status"] == "installed"
