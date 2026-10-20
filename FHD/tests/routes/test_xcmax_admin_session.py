# mypy: disable-error-code="misc, union-attr"
"""Tests for app.fastapi_routes.xcmax_admin — coverage ramp C3.3-a.

Covers:
* ``_require_market_admin_session`` — missing session / non-admin / admin / no-sid.
* ``_release_train_snapshot`` — modstore / file / missing / bad JSON.
* A representative admin endpoint with mocked dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes
from app.fastapi_routes.xcmax_admin import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


class TestRequireMarketAdmin:
    def test_no_session_id_returns_401(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value=None,
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 401
        assert "登录" in resp.body.decode()

    def test_non_admin_account_returns_403(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "user", "market_is_admin": False},
            ),
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 403

    def test_admin_returns_none(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value={"account_kind": "admin", "market_is_admin": True},
            ),
        ):
            assert admin_routes._require_market_admin_session(request) is None

    def test_meta_none_returns_403(self) -> None:
        from starlette.requests import Request

        request = MagicMock(spec=Request)
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sess1",
            ),
            patch(
                "app.application.session_account_meta.load_session_account_meta",
                return_value=None,
            ),
        ):
            resp = admin_routes._require_market_admin_session(request)
        assert resp is not None
        assert resp.status_code == 403


class TestReleaseTrainSnapshot:
    def test_modstore_path_used(self) -> None:
        with patch.dict(
            "sys.modules",
            {
                "modstore_server.release_train": MagicMock(
                    snapshot_public=MagicMock(return_value={"current": "1.0.0.0"})
                )
            },
        ):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.0"

    def test_fallback_to_file(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text(
            json.dumps({"current": "9.9.9.9", "epoch": "9.9.0.0"})
        )
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "9.9.9.9"

    def test_file_missing_returns_default(self, tmp_path: Path) -> None:
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.1"
        assert out.get("note") == "ssot missing"

    def test_bad_json_returns_default(self, tmp_path: Path) -> None:
        cfg_dir = tmp_path / "FHD" / "config"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "release_train.json").write_text("not json")
        with patch.dict("os.environ", {"XCMAX_MONOREPO_ROOT": str(tmp_path)}):
            out = admin_routes._release_train_snapshot()
        assert out["current"] == "1.0.0.1"


@pytest.mark.parametrize(
    "meta, sid, expected",
    [
        ({}, None, 401),
        ({"account_kind": "user", "market_is_admin": False}, "session", 403),
        ({"account_kind": "admin", "market_is_admin": False}, "session", 403),
    ],
)
@pytest.mark.parametrize("suffix", ["", "/42"])
def test_customer_ticket_list_requires_bound_market_admin(client, meta, sid, expected, suffix):
    from unittest.mock import AsyncMock

    with (
        patch("app.fastapi_routes.domains.misc.helpers._session_id_from_request", return_value=sid),
        patch("app.application.session_account_meta.load_session_account_meta", return_value=meta),
        patch("app.fastapi_routes.market_account._proxy_json", new_callable=AsyncMock) as proxy,
    ):
        response = client.get(f"/api/xcmax/admin/customer-service/tickets{suffix}?search=290063")
    assert response.status_code == expected
    proxy.assert_not_awaited()


@pytest.fixture
def customer_ticket_identity(monkeypatch):
    from types import SimpleNamespace

    from app.application import desktop_admin_gate, session_account_meta
    from app.application.facades import session_facade
    from app.db import session as db_session
    from app.fastapi_routes import market_account

    service = MagicMock()
    service.validate_session.return_value = SimpleNamespace(id=7, is_active=True)
    monkeypatch.setattr(session_facade, "get_session_service", lambda: service)
    monkeypatch.setattr(
        session_account_meta,
        "load_session_account_meta",
        lambda _sid: {"account_kind": "admin", "market_is_admin": True},
    )
    monkeypatch.setattr(desktop_admin_gate, "is_desktop_runtime", lambda: False)
    monkeypatch.setattr(
        market_account, "_MARKET_SESSION_TOKENS", {"current-session": "test-bound-market-identity"}
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    context = MagicMock()
    context.__enter__.return_value = db
    monkeypatch.setattr(db_session, "get_db", lambda: context)

    forbidden = MagicMock(
        side_effect=AssertionError("CS must never use latest-session or browser-token fallback")
    )
    monkeypatch.setattr(market_account, "latest_session_market_token", forbidden)
    monkeypatch.setattr(market_account, "_authorization_from_request_resolved", forbidden)
    yield service, market_account
    forbidden.assert_not_called()


def test_customer_ticket_proxy_preserves_search_and_market_identity(
    client, customer_ticket_identity
):
    from unittest.mock import AsyncMock
    from urllib.parse import parse_qs, urlsplit

    with patch(
        "app.fastapi_routes.market_account._proxy_json",
        new_callable=AsyncMock,
        return_value={"items": [], "total": 0},
    ) as proxy:
        response = client.get(
            "/api/xcmax/admin/customer-service/tickets",
            params={
                "search": "290063 & 原文",
                "submitter_type": "admin",
                "offset": 50,
                "limit": 50,
            },
            headers={
                "X-Session-ID": "current-session",
                "Authorization": "Bearer unrelated-browser-identity",
            },
        )
        assert response.status_code == 200
        args, kwargs = proxy.await_args
        assert args[0] == "GET"
        assert urlsplit(args[1]).path == "/api/customer-service/tickets"
        assert parse_qs(urlsplit(args[1]).query) == {
            "search": ["290063 & 原文"],
            "submitter_type": ["admin"],
            "offset": ["50"],
            "limit": ["50"],
        }
        assert kwargs["authorization"] == "Bearer test-bound-market-identity"
        assert kwargs["json_body"] is None
        assert client.get("/api/xcmax/admin/customer-service/tickets?offset=-1").status_code == 422
        assert client.get("/api/xcmax/admin/customer-service/tickets?limit=101").status_code == 422
        assert proxy.await_count == 1
        assert (
            client.get(
                "/api/xcmax/admin/customer-service/tickets/42",
                headers={"X-Session-ID": "current-session"},
            ).status_code
            == 200
        )
        assert proxy.await_args.args == ("GET", "/api/customer-service/tickets/42")
        assert proxy.await_args.kwargs["authorization"] == "Bearer test-bound-market-identity"
        service, _ = customer_ticket_identity
        service.validate_session.assert_called_with("current-session")


def test_customer_ticket_close_uses_only_current_admin_market_identity(
    client, customer_ticket_identity
):
    from unittest.mock import AsyncMock

    body = {"request_id": "123e4567-e89b-12d3-a456-426614174000", "note": "验收通过并关闭", "verification": "目标版本页面按原复现步骤通过。"}
    with patch(
        "app.fastapi_routes.market_account._proxy_json",
        new_callable=AsyncMock,
        return_value={"ticket": {"id": 42, "status": "resolved"}},
    ) as proxy:
        response = client.post(
            "/api/xcmax/admin/customer-service/tickets/42/close",
            json=body,
            headers={"X-Session-ID": "current-session", "Authorization": "Bearer unrelated"},
        )
    assert response.status_code == 200
    assert proxy.await_args.args == ("POST", "/api/customer-service/tickets/42/close")
    assert proxy.await_args.kwargs["json_body"] == body
    assert proxy.await_args.kwargs["authorization"] == "Bearer test-bound-market-identity"


@pytest.mark.parametrize("suffix", ["", "/42"])
@pytest.mark.parametrize("failure", ["no_user", "resolver_error", "inactive", "no_bound_token"])
def test_customer_ticket_identity_failures_never_use_another_session(
    client, customer_ticket_identity, suffix, failure
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    service, market = customer_ticket_identity
    if failure == "no_user":
        service.validate_session.return_value = None
    elif failure == "resolver_error":
        service.validate_session.side_effect = RuntimeError("identity unavailable")
    elif failure == "inactive":
        service.validate_session.return_value = SimpleNamespace(id=7, is_active=False)
    else:
        market._MARKET_SESSION_TOKENS.clear()
    with patch("app.fastapi_routes.market_account._proxy_json", new_callable=AsyncMock) as proxy:
        response = client.get(
            f"/api/xcmax/admin/customer-service/tickets{suffix}",
            headers={
                "X-Session-ID": "current-session",
                "Authorization": "Bearer unrelated-browser-identity",
            },
        )
    assert response.status_code == 401
    assert "items" not in response.json()
    proxy.assert_not_awaited()


@pytest.mark.parametrize("suffix", ["", "/42"])
@pytest.mark.parametrize("status", [401, 403, 503])
def test_customer_ticket_proxy_preserves_upstream_failure(
    client, customer_ticket_identity, suffix, status
):
    from unittest.mock import AsyncMock

    with patch(
        "app.fastapi_routes.market_account._proxy_json",
        new_callable=AsyncMock,
        return_value={
            "__proxy_error__": True,
            "status_code": status,
            "payload": {"detail": "unavailable"},
        },
    ) as proxy:
        response = client.get(
            f"/api/xcmax/admin/customer-service/tickets{suffix}",
            headers={"X-Session-ID": "current-session"},
        )
    assert response.status_code == status
    assert "items" not in response.json()
    assert proxy.await_args.kwargs["authorization"] == "Bearer test-bound-market-identity"
