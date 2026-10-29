"""A PAT must not become an unrestricted login or administrator identity."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server import auth_service
from modstore_server.models import DeveloperToken, User


@pytest.fixture
def pat_case(tmp_path, monkeypatch):
    from modstore_server import (
        browser_handoff_api,
        customer_issue_api,
        developer_api,
        market_catalog_api,
        openai_llm_gateway_api,
        production_line_api,
    )
    from modstore_server.api import catalog, config, market_routes

    engine = create_engine(
        f"sqlite:///{tmp_path / 'pat.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    User.__table__.create(engine)
    DeveloperToken.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    for module in (
        "modstore_server.auth_service",
        "modstore_server.application.auth",
        "modstore_server.infrastructure.db",
    ):
        monkeypatch.setattr(module + ".get_session_factory", lambda: sessions)
    with sessions.begin() as db:
        db.add_all(
            [
                User(
                    id=7,
                    username="synthetic-admin",
                    password_hash="unused",
                    is_admin=True,
                ),
                User(
                    id=8,
                    username="synthetic-member",
                    password_hash="unused",
                    is_admin=False,
                ),
            ]
        )
    save = Mock()
    monkeypatch.setattr(config.library_paths, "save_config", save)
    monkeypatch.setattr(config, "get_config", lambda: {"ok": True})
    handoff = Mock(return_value={"code": "synthetic-not-a-live-code"})
    monkeypatch.setattr(browser_handoff_api, "issue_code", handoff)
    app = FastAPI()
    for router in (
        config.router,
        catalog.router,
        developer_api.router,
        production_line_api.router,
        openai_llm_gateway_api.router,
    ):
        app.include_router(router)
    app.include_router(market_routes.router)
    app.include_router(market_catalog_api.router, prefix="/api")
    app.include_router(browser_handoff_api.router, prefix="/api")
    app.include_router(customer_issue_api.router, prefix="/api/customer-service")
    with TestClient(app) as client:
        yield client, sessions, save, handoff
    engine.dispose()


def _pat(sessions, scopes, *, state="valid", uid=7):
    raw, prefix, digest = auth_service.generate_pat()
    with sessions.begin() as db:
        row = DeveloperToken(
            user_id=uid,
            name="synthetic",
            token_prefix=prefix,
            token_hash=digest,
            scopes_json=json.dumps(scopes),
        )
        if state == "revoked":
            row.revoked_at = datetime.now(UTC)
        elif state == "expired":
            row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        elif state == "deleted-user":
            db.get(User, uid).deleted_at = datetime.now(UTC)
        elif state == "disabled-user":
            db.get(User, uid).account_state = "disabled"
        db.add(row)
    return raw


@pytest.mark.parametrize(
    "scopes",
    [
        [],
        ["workflow:read"],
        ["catalog:read"],
        ["workflow:execute"],
        ["employee:execute"],
        ["webhook:manage"],
        ["llm:use"],
        ["mod:sync"],
    ],
)
def test_pat_cannot_write_admin_config_or_issue_credentials(pat_case, scopes):
    client, sessions, save, handoff = pat_case
    headers = {"Authorization": "Bearer " + _pat(sessions, scopes)}
    response = client.put(
        "/api/config",
        headers=headers,
        json={"xcagi_backend_url": "http://test.invalid"},
    )
    assert response.status_code == 403, response.text
    save.assert_not_called()
    token = client.post(
        "/api/developer/tokens",
        headers=headers,
        json={"name": "must-not-exist", "scopes": ["employee:execute"]},
    )
    assert token.status_code == 403, token.text
    login = client.post(
        "/api/auth/browser-handoff",
        headers=headers,
        json={"target": "/wallet", "purpose": "wallet"},
    )
    assert login.status_code == 403, login.text
    handoff.assert_not_called()
    with sessions() as db:
        assert db.query(DeveloperToken).count() == 1


@pytest.mark.parametrize("state", ["revoked", "expired", "deleted-user"])
def test_invalid_pat_stays_unauthenticated(pat_case, state):
    client, sessions, save, _ = pat_case
    response = client.put(
        "/api/config",
        headers={"Authorization": "Bearer " + _pat(sessions, ["mod:sync"], state=state)},
        json={},
    )
    assert response.status_code == 401
    save.assert_not_called()


@pytest.mark.parametrize("uid,expected", [(7, 200), (8, 403)])
def test_jwt_user_authority_is_unchanged(pat_case, uid, expected):
    client, _, save, _ = pat_case
    token = auth_service.create_access_token(uid, "synthetic", is_admin=uid == 7)
    response = client.put("/api/config", headers={"Authorization": "Bearer " + token}, json={})
    assert response.status_code == expected, response.text
    assert save.call_count == (1 if expected == 200 else 0)


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/api/admin/production-line/stop", "POST", {}),
        (
            "/api/customer-service/issues/pending-runtime?host_sha=" + "a" * 40,
            "GET",
            None,
        ),
        (
            "/api/mods/synthetic/file",
            "PUT",
            {"path": "synthetic.txt", "content": "must-not-write"},
        ),
    ],
)
def test_pat_rejection_covers_direct_admin_and_alternate_user_dependencies(
    pat_case, path, method, body, monkeypatch
):
    from modstore_server import (
        customer_issue_shared_release,
        production_line_orchestrator,
    )

    forbidden = [
        Mock(side_effect=AssertionError("protected business action reached")) for _ in range(3)
    ]
    monkeypatch.setattr(
        production_line_orchestrator, "get_production_line_orchestrator", forbidden[0]
    )
    from modstore_server.api import catalog

    monkeypatch.setattr(catalog, "write_text_under_mod", forbidden[1])
    monkeypatch.setattr(customer_issue_shared_release, "bind_shared_release", forbidden[2])
    client, sessions, _, _ = pat_case
    response = client.request(
        method,
        path,
        headers={"Authorization": "Bearer " + _pat(sessions, ["workflow:read"])},
        json=body,
    )
    assert response.status_code == 403, response.text
    for action in forbidden:
        action.assert_not_called()


@pytest.mark.parametrize("optional", ["auth_deps", "market_shared", "market_routes"])
def test_optional_user_does_not_downgrade_pat_scope_denial(pat_case, optional):
    from fastapi import HTTPException

    from modstore_server.api import market_routes
    from modstore_server.api.auth_deps import get_optional_user
    from modstore_server.market_shared import _optional_current_user

    _get_optional_user = market_routes._get_optional_user

    _, sessions, _, _ = pat_case
    fn = {
        "auth_deps": get_optional_user,
        "market_shared": _optional_current_user,
        "market_routes": _get_optional_user,
    }[optional]
    assert fn(None) is None
    with pytest.raises(HTTPException) as error:
        fn("Bearer " + _pat(sessions, ["catalog:read"]))
    assert error.value.status_code == 403


@pytest.mark.parametrize("bearer_prefix", ["Bearer ", "Bearer  "])
@pytest.mark.parametrize("cookie", [False, True])
@pytest.mark.parametrize("scopes,expected", [(["mod:sync"], 200), (["catalog:read"], 403)])
def test_scoped_mod_sync_pat_keeps_scope_and_csrf_boundaries(
    pat_case, monkeypatch, tmp_path, cookie, scopes, expected, bearer_prefix
):
    from modstore_server import app as app_module
    from modstore_server import mod_sync_catalog_api as sync
    from modstore_server.api.csrf import CSRFMiddleware

    _, sessions, _, _ = pat_case
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    monkeypatch.setattr(app_module, "_cfg", lambda: None)
    monkeypatch.setattr(sync, "resolved_xcagi", lambda config: tmp_path)
    monkeypatch.setattr(sync, "_lib", lambda: tmp_path)
    deploy = Mock(return_value=["synthetic"])
    monkeypatch.setattr(sync, "deploy_to_xcagi", deploy)
    app = FastAPI()
    app.include_router(sync.router)
    app.add_middleware(CSRFMiddleware)
    with TestClient(app) as client:
        if cookie:
            client.cookies.set("csrf_token", "synthetic-cookie")
        response = client.post(
            "/v1/mod-sync/push",
            json={"mod_ids": ["synthetic"]},
            headers={"Authorization": bearer_prefix + _pat(sessions, scopes)},
        )
    assert response.status_code == expected, response.text
    assert deploy.call_count == (1 if expected == 200 else 0)
    if expected == 403:
        assert "mod:sync" in response.text


def test_pat_identity_preserves_scopes_without_generic_user_access(pat_case):
    from modstore_server.application.auth import (
        AuthApplicationService,
        ScopeAuthorizationError,
    )

    _, sessions, _, _ = pat_case
    token = _pat(sessions, ["mod:sync"])
    identity = auth_service.resolve_pat_identity(token)
    assert identity.user.id == 7 and identity.scopes == ("mod:sync",)
    with pytest.raises(ScopeAuthorizationError):
        AuthApplicationService().current_user_from_authorization("Bearer " + token)


@pytest.mark.parametrize("uid", [7, 8])
def test_model_dependency_preserves_pat_owner_and_jwt(pat_case, uid, monkeypatch, tmp_path):
    from modstore_server.openai_llm_gateway_api import _get_llm_gateway_user

    _, sessions, _, _ = pat_case
    _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    pat = _pat(sessions, ["llm:use"], uid=uid)
    jwt = auth_service.create_access_token(uid, "synthetic", is_admin=uid == 7)
    assert (
        _get_llm_gateway_user(SimpleNamespace(state=SimpleNamespace()), "Bearer " + pat).id == uid
    )
    assert (
        _get_llm_gateway_user(SimpleNamespace(state=SimpleNamespace()), "Bearer " + jwt).id == uid
    )


@pytest.mark.parametrize(
    "state,scopes,status",
    [
        ("valid", [], 403),
        ("valid", ["catalog:read"], 403),
        ("revoked", ["llm:use"], 401),
        ("expired", ["llm:use"], 401),
        ("deleted-user", ["llm:use"], 401),
        ("disabled-user", ["llm:use"], 401),
    ],
)
def test_model_dependency_denies_invalid_scope_and_identity(
    pat_case, state, scopes, status, monkeypatch, tmp_path
):
    from fastapi import HTTPException

    from modstore_server.openai_llm_gateway_api import _get_llm_gateway_user

    _, sessions, _, _ = pat_case
    _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as error:
        _get_llm_gateway_user(
            SimpleNamespace(state=SimpleNamespace()),
            "Bearer " + _pat(sessions, scopes, state=state),
        )
    assert error.value.status_code == status


def _enable_synthetic_llm_pat(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "synthetic.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    monkeypatch.setenv("MODSTORE_LLM_PAT_ENABLED", "1")
    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    monkeypatch.setenv("MODSTORE_LLM_WALLET_SIGNING_KEY_PATH", str(path))
    monkeypatch.setenv("MODSTORE_LLM_WALLET_KEY_ID", "synthetic")
    monkeypatch.setenv("MODSTORE_LLM_WALLET_MAX_CENTS", "100")
    return key


@pytest.mark.parametrize("revoke_before_preauth", [False, True])
def test_model_pat_bridge_revalidates_and_finishes_existing_hold(
    pat_case, monkeypatch, tmp_path, revoke_before_preauth
):
    import hashlib

    import httpx

    from modstore_server import openai_llm_gateway_api as gateway
    from modstore_server.llm_wallet_assertion import verify_assertion
    from modstore_server.llm_wallet_client import JavaWalletClient

    client, sessions, _, _ = pat_case
    key = _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    pat = _pat(sessions, ["llm:use"], uid=8)
    operations = []

    async def post(url, *, headers, content, timeout):
        operation = url.rsplit("/", 1)[-1]
        assert "Authorization" not in headers
        data = json.loads(content)
        claims = verify_assertion(
            headers["X-Llm-Wallet-Assertion"],
            {"synthetic": key.public_key()},
            operation=operation,
            user_id=8,
            request_digest=hashlib.sha256(content).hexdigest(),
            server_max_amount_cents=100,
        )
        operations.append((operation, claims["sub"]))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "hold": {
                    "hold_no": "synthetic-hold",
                    "amount": "0.05",
                    "status": "settled" if operation == "settle" else "held",
                    "settled_amount": "0.02" if operation == "settle" else "0.00",
                },
            },
        )

    monkeypatch.setattr(
        "modstore_server.infrastructure.http_clients.get_java_client",
        lambda: SimpleNamespace(post=post),
    )

    def revoke():
        with sessions.begin() as db:
            db.query(DeveloperToken).filter(DeveloperToken.user_id == 8).one().revoked_at = (
                datetime.now(UTC)
            )

    async def run(request, db, user, **kwargs):
        wallet = JavaWalletClient(request=request)
        if revoke_before_preauth:
            revoke()
        hold = await wallet.preauthorize(
            request.headers["authorization"],
            Decimal("0.05"),
            "openai",
            "synthetic",
            "synthetic-request",
        )
        revoke()
        await wallet.settle(
            request.headers["authorization"], hold, Decimal("0.02"), "synthetic-request"
        )
        return {"content": "synthetic", "billed": True, "charge_amount": 0.02}

    monkeypatch.setattr(gateway, "run_billed_llm_chat", AsyncMock(side_effect=run))
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer " + pat},
        json={"model": "openai/synthetic", "messages": [{"role": "user", "content": "synthetic"}]},
    )
    assert response.status_code == (401 if revoke_before_preauth else 200), response.text
    assert operations == ([] if revoke_before_preauth else [("preauthorize", "8"), ("settle", "8")])


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/v1/models", None),
        (
            "POST",
            "/v1/chat/completions",
            {"model": "xcauto-account", "messages": [{"role": "user", "content": "test"}]},
        ),
    ],
)
def test_model_gateway_currently_rejects_even_llm_scoped_pat(pat_case, method, path, body):
    client, sessions, _, _ = pat_case
    response = client.request(
        method, path, json=body, headers={"Authorization": "Bearer " + _pat(sessions, ["llm:use"])}
    )
    assert response.status_code == 403


def test_enabled_model_pat_fails_closed_without_wallet_configuration(pat_case, monkeypatch):
    client, sessions, _, _ = pat_case
    monkeypatch.setenv("MODSTORE_LLM_PAT_ENABLED", "1")
    monkeypatch.delenv("MODSTORE_LLM_WALLET_SIGNING_KEY_PATH", raising=False)
    response = client.get(
        "/v1/models", headers={"Authorization": "Bearer " + _pat(sessions, ["llm:use"])}
    )
    assert response.status_code == 503


def test_enabled_model_pat_rejects_world_readable_signing_key(pat_case, monkeypatch, tmp_path):
    import os

    if os.name != "posix":
        pytest.skip("POSIX key permissions")
    client, sessions, _, _ = pat_case
    _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    (tmp_path / "synthetic.pem").chmod(0o644)
    response = client.get(
        "/v1/models", headers={"Authorization": "Bearer " + _pat(sessions, ["llm:use"])}
    )
    assert response.status_code == 503


def test_enabled_model_pat_rejects_invalid_signing_key(pat_case, monkeypatch, tmp_path):
    client, sessions, _, _ = pat_case
    _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    (tmp_path / "synthetic.pem").write_bytes(b"invalid")
    response = client.get(
        "/v1/models", headers={"Authorization": "Bearer " + _pat(sessions, ["llm:use"])}
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_pat_wallet_never_uses_debug_billing_when_backend_disabled(
    pat_case, monkeypatch, tmp_path
):
    from fastapi import HTTPException

    from modstore_server.llm_wallet_client import JavaWalletClient

    _, sessions, _, _ = pat_case
    _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    pat = _pat(sessions, ["llm:use"], uid=8)
    monkeypatch.setenv("PAYMENT_BACKEND", "python")
    wallet = JavaWalletClient(request=SimpleNamespace(state=SimpleNamespace(llm_pat_user_id=8)))
    with pytest.raises(HTTPException) as error:
        await wallet.preauthorize(
            "Bearer " + pat, Decimal("0.05"), "openai", "synthetic", "synthetic-request"
        )
    assert error.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["revoked", "disabled-user"])
async def test_byok_rechecks_pat_before_upstream(pat_case, monkeypatch, state):
    from fastapi import HTTPException

    from modstore_server import llm_billed_once

    _, sessions, _, _ = pat_case
    pat = _pat(sessions, ["llm:use"], state=state, uid=8)
    request = SimpleNamespace(
        state=SimpleNamespace(llm_pat_user_id=8), headers={"authorization": "Bearer " + pat}
    )
    monkeypatch.setattr(
        llm_billed_once, "resolve_api_key", lambda *args: ("synthetic", "user_override")
    )
    monkeypatch.setattr(llm_billed_once, "resolve_base_url", lambda *args: None)
    monkeypatch.setattr(llm_billed_once, "assert_llm_chat_allowed", AsyncMock())
    monkeypatch.setattr(llm_billed_once, "enforce_risk_limits", Mock())
    dispatch = AsyncMock()
    monkeypatch.setattr(llm_billed_once, "chat_dispatch", dispatch)
    with pytest.raises(HTTPException) as error:
        await llm_billed_once.run_billed_llm_chat_once(
            request,
            object(),
            SimpleNamespace(id=8),
            provider="openai",
            model="synthetic",
            messages=[{"role": "user", "content": "synthetic"}],
        )
    assert error.value.status_code == 401
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["invalid-json", "non-object", "wrong-amount", "fractional-cent", "terminal", "nan"]
)
async def test_pat_preauthorization_rejects_corrupt_success_response(
    pat_case, monkeypatch, tmp_path, case
):
    import httpx
    from fastapi import HTTPException

    from modstore_server.llm_wallet_client import JavaWalletClient

    _, sessions, _, _ = pat_case
    _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    pat = _pat(sessions, ["llm:use"], uid=8)
    if case == "invalid-json":
        response = httpx.Response(200, content=b"not json")
    elif case == "non-object":
        response = httpx.Response(200, json=[])
    else:
        amount = {
            "wrong-amount": "0.06",
            "fractional-cent": "0.049",
            "terminal": "0.05",
            "nan": "NaN",
        }[case]
        response = httpx.Response(
            200,
            json={
                "ok": True,
                "hold": {
                    "hold_no": "synthetic",
                    "amount": amount,
                    "status": "settled" if case == "terminal" else "held",
                },
            },
        )
    monkeypatch.setattr(
        "modstore_server.infrastructure.http_clients.get_java_client",
        lambda: SimpleNamespace(post=AsyncMock(return_value=response)),
    )
    wallet = JavaWalletClient(request=SimpleNamespace(state=SimpleNamespace(llm_pat_user_id=8)))
    with pytest.raises(HTTPException) as error:
        await wallet.preauthorize(
            "Bearer " + pat, Decimal("0.05"), "openai", "synthetic", "synthetic-request"
        )
    assert error.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settled_amount,status",
    [("0.00", "settled"), ("0.019", "settled"), ("0.02", "held"), ("Infinity", "settled")],
)
async def test_pat_settlement_requires_confirmed_exact_amount(
    pat_case, monkeypatch, tmp_path, settled_amount, status
):
    import httpx
    from fastapi import HTTPException

    from modstore_server.llm_billing_values import WalletHold
    from modstore_server.llm_wallet_client import JavaWalletClient

    _enable_synthetic_llm_pat(monkeypatch, tmp_path)
    response = httpx.Response(
        200,
        json={
            "ok": True,
            "hold": {
                "hold_no": "synthetic-hold",
                "status": status,
                "settled_amount": settled_amount,
            },
        },
    )
    monkeypatch.setattr(
        "modstore_server.infrastructure.http_clients.get_java_client",
        lambda: SimpleNamespace(post=AsyncMock(return_value=response)),
    )
    wallet = JavaWalletClient(request=SimpleNamespace(state=SimpleNamespace(llm_pat_user_id=8)))
    with pytest.raises(HTTPException) as error:
        await wallet.settle(
            "Bearer synthetic",
            WalletHold("synthetic-hold", Decimal("0.05"), True),
            Decimal("0.02"),
            "synthetic-request",
        )
    assert error.value.status_code == 502


@pytest.mark.parametrize("path", ["/api/mods", "/api/auth/me", "/api/market/catalog"])
def test_real_optional_routes_deny_scoped_pat_instead_of_anonymous(pat_case, path):
    client, sessions, _, _ = pat_case
    response = client.get(
        path, headers={"Authorization": "Bearer " + _pat(sessions, ["catalog:read"])}
    )
    assert response.status_code == 403, response.text


def test_invalid_scope_json_cannot_grant_generic_permissions(pat_case):
    client, sessions, save, _ = pat_case
    token = _pat(sessions, [])
    with sessions.begin() as db:
        db.query(DeveloperToken).one().scopes_json = "not-valid-json"
    response = client.put("/api/config", json={}, headers={"Authorization": "Bearer " + token})
    assert response.status_code == 403
    save.assert_not_called()


@pytest.mark.parametrize("owned", [True, False])
def test_mod_sync_member_pat_cannot_write_shared_host_even_when_owned(
    pat_case, monkeypatch, tmp_path, owned
):
    from modstore_server import app as app_module
    from modstore_server import mod_sync_catalog_api as sync

    _, sessions, _, _ = pat_case
    monkeypatch.setattr(app_module, "_cfg", lambda: None)
    monkeypatch.setattr(sync, "resolved_xcagi", lambda config: tmp_path)
    monkeypatch.setattr(sync, "_lib", lambda: tmp_path)
    monkeypatch.setattr(
        sync,
        "user_owns_mod",
        lambda uid, mid: uid == 8 and mid == "synthetic" and owned,
    )
    deploy = Mock(return_value=["synthetic"])
    monkeypatch.setattr(sync, "deploy_to_xcagi", deploy)
    app = FastAPI()
    app.include_router(sync.router)
    with TestClient(app) as client:
        response = client.post(
            "/v1/mod-sync/push",
            json={"mod_ids": ["synthetic"]},
            headers={"Authorization": "Bearer " + _pat(sessions, ["mod:sync"], uid=8)},
        )
    assert response.status_code == 403, response.text
    deploy.assert_not_called()


def test_jwt_can_still_manage_credentials_and_request_handoff(pat_case):
    client, sessions, _, handoff = pat_case
    token = auth_service.create_access_token(7, "synthetic-admin", is_admin=True)
    headers = {"Authorization": "Bearer " + token}
    response = client.post(
        "/api/developer/tokens",
        headers=headers,
        json={"name": "synthetic-positive", "scopes": ["mod:sync"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["scopes"] == ["mod:sync"]
    with sessions() as db:
        assert db.query(DeveloperToken).count() == 1
    response = client.post(
        "/api/auth/browser-handoff",
        headers=headers,
        json={"target": "/wallet", "purpose": "wallet"},
    )
    assert response.status_code == 200
    handoff.assert_called_once_with(7, "/wallet", "wallet")
