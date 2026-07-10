from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.fastapi_routes import mobile_api as mobile_api_module
from app.fastapi_routes import mobile_api_extensions as mobile_ext
from app.fastapi_routes.mobile_extensions import relay_helpers
from app.fastapi_routes.mobile_extensions.models import PairingExchangeBody, PairingIssueBody
from app.security.mobile_jwt import (
    issue_mobile_tokens,
    refresh_mobile_access_token,
    verify_mobile_jwt,
)
from app.security.mobile_pairing import PAIRING_FAILURE_LIMIT, reset_pairing_failure_limits

_enterprise_pairing_user = mobile_api_module._enterprise_pairing_user
get_mobile_user = mobile_api_module.get_mobile_user
router = mobile_api_module.router


@pytest.fixture(autouse=True)
def _reset_pairing_failure_state():
    reset_pairing_failure_limits()
    yield
    reset_pairing_failure_limits()


def _request(*, authorization: str = "") -> Request:
    headers = [(b"host", b"192.168.10.2:17500")]
    if authorization:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/mobile/v1/pairing/issue",
            "raw_path": b"/api/mobile/v1/pairing/issue",
            "query_string": b"",
            "headers": headers,
            "client": ("192.168.10.8", 45678),
            "server": ("192.168.10.2", 17500),
        }
    )


def _admin(*, user_id: int = 7, tenant_id: int | None = 11):
    return SimpleNamespace(
        id=user_id,
        username=f"admin-{user_id}",
        display_name="管理端",
        role="admin",
        tier="admin",
        tenant_id=tenant_id,
        is_active=True,
    )


async def _issue(monkeypatch: pytest.MonkeyPatch, *, tenant_id: int = 11) -> dict:
    monkeypatch.setattr(
        mobile_ext,
        "_mobile_session_meta",
        lambda _request: {
            "account_kind": "admin",
            "market_is_admin": True,
            "tenant_id": tenant_id,
            "company_brand": f"tenant-{tenant_id}",
        },
    )
    monkeypatch.setattr(mobile_ext, "_register_desktop_relay_for_pairing", lambda *_: None)
    result = await mobile_ext.mobile_pairing_issue(
        PairingIssueBody(host="192.168.10.2", port=17500),
        _request(),
        user=_admin(tenant_id=tenant_id),
    )
    assert isinstance(result, dict)
    assert result["success"] is True
    return result["data"]


@pytest.mark.asyncio
async def test_pairing_issue_requires_authenticated_management_admin(monkeypatch):
    body = PairingIssueBody(host="192.168.10.2", port=17500)

    missing = await mobile_ext.mobile_pairing_issue(body, _request(), user=None)
    assert missing.status_code == 401

    enterprise = SimpleNamespace(
        id=8,
        username="member",
        role="enterprise",
        tier="enterprise",
        tenant_id=11,
        is_active=True,
    )
    forbidden = await mobile_ext.mobile_pairing_issue(body, _request(), user=enterprise)
    assert forbidden.status_code == 403

    bearer_admin = await mobile_ext.mobile_pairing_issue(
        body,
        _request(authorization="Bearer mobile-admin-token"),
        user=_admin(),
    )
    assert bearer_admin.status_code == 403


@pytest.mark.asyncio
async def test_management_pairing_is_tenant_bound_enterprise_only_and_one_time(
    monkeypatch,
):
    monkeypatch.setenv("SECRET_KEY", "pairing-security-test-secret-key-at-least-32-bytes")
    issued = await _issue(monkeypatch, tenant_id=11)
    code = str(issued["code"])
    assert len(code) == 6

    def subject(record: dict):
        return {
            "id": int(record["subject_user_id"]),
            "username": str(record["subject_username"]),
            "display_name": "移动企业端",
            "role": "enterprise",
            "tier": "enterprise",
            "tenant_id": record["tenant_id"],
            "is_active": True,
        }

    monkeypatch.setattr(mobile_ext, "_pairing_subject_user", subject)
    result = await mobile_ext.mobile_pairing_exchange(
        PairingExchangeBody(code=code),
        _request(),
        user=None,
    )
    assert isinstance(result, dict)
    data = result["data"]
    assert data["account_kind"] == "enterprise"
    assert data["token_scope"] == "enterprise_pairing"
    assert data["tenant_id"] == 11
    assert data["company_brand"] == "tenant-11"
    assert data["user"]["role"] == "enterprise"

    access = verify_mobile_jwt(data["access_token"])
    refresh = verify_mobile_jwt(data["refresh_token"])
    assert access is not None and refresh is not None
    for payload in (access, refresh):
        assert payload["account_kind"] == "enterprise"
        assert payload["token_scope"] == "enterprise_pairing"
        assert payload["tenant_id"] == 11
        assert payload["paired_by_user_id"] == 7

    rotated = refresh_mobile_access_token(data["refresh_token"])
    assert rotated is not None
    rotated_access = verify_mobile_jwt(rotated["access_token"])
    assert rotated_access is not None
    assert rotated_access["token_scope"] == "enterprise_pairing"
    assert rotated_access["tenant_id"] == 11

    replay = await mobile_ext.mobile_pairing_exchange(
        PairingExchangeBody(code=code),
        _request(),
        user=None,
    )
    assert replay.status_code == 400


@pytest.mark.asyncio
async def test_cross_tenant_or_user_cannot_consume_pairing_code(monkeypatch):
    issued = await _issue(monkeypatch, tenant_id=11)
    code = str(issued["code"])
    monkeypatch.setattr(
        mobile_ext,
        "_mobile_session_meta",
        lambda _request: {"account_kind": "enterprise", "tenant_id": 22},
    )
    other_tenant = SimpleNamespace(
        id=99,
        username="tenant-22-user",
        role="enterprise",
        tier="enterprise",
        tenant_id=22,
        is_active=True,
    )
    rejected = await mobile_ext.mobile_pairing_exchange(
        PairingExchangeBody(code=code),
        _request(),
        user=other_tenant,
    )
    assert rejected.status_code == 403

    monkeypatch.setattr(
        mobile_ext,
        "_pairing_subject_user",
        lambda record: {
            "id": record["subject_user_id"],
            "username": record["subject_username"],
            "role": "enterprise",
            "tier": "enterprise",
            "tenant_id": record["tenant_id"],
            "is_active": True,
        },
    )
    legitimate = await mobile_ext.mobile_pairing_exchange(
        PairingExchangeBody(code=code),
        _request(),
        user=None,
    )
    assert isinstance(legitimate, dict)
    assert legitimate["data"]["tenant_id"] == 11


def test_pairing_token_projects_bound_admin_as_enterprise_only(monkeypatch):
    user = _admin(user_id=7, tenant_id=11)
    payload = {
        "user_id": 7,
        "username": "admin-7",
        "account_kind": "enterprise",
        "token_scope": "enterprise_pairing",
        "tenant_id": 11,
        "company_brand": "tenant-11",
        "paired_by_user_id": 7,
    }
    projected = _enterprise_pairing_user(user, payload)
    assert projected is not None
    assert projected.role == "enterprise"
    assert projected.tier == "enterprise"
    assert projected.tenant_id == 11

    wrong_tenant = dict(payload, tenant_id=22)
    assert _enterprise_pairing_user(user, wrong_tenant) is None


def test_unsafe_relay_admin_resolution_helpers_are_not_exposed():
    assert not hasattr(mobile_ext, "_resolve_mobile_relay_user")
    assert not hasattr(relay_helpers, "_relay_admin_fallback_user")

    with pytest.raises(ValueError, match="authenticated user"):
        relay_helpers._relay_mobile_auth_payload({"id": 0, "role": "admin"})
    with pytest.raises(ValueError, match="enterprise-only"):
        relay_helpers._relay_mobile_auth_payload(
            {"id": 7, "username": "admin", "role": "admin"},
            account_kind_override="admin",
        )


class _FakeUserDb:
    def __init__(self, user):
        self.user = user

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.user

    def expunge(self, _user):
        return None


def _http_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.include_router(mobile_ext.extension_router, prefix="/api/mobile/v1")
    return app


def test_real_http_pairing_projects_admin_and_preserves_enterprise_capabilities(
    monkeypatch: pytest.MonkeyPatch,
):
    """Exercise the real Bearer dependency chain instead of direct guard calls."""
    monkeypatch.setenv("SECRET_KEY", "pairing-http-integration-secret-key-at-least-32-bytes")
    admin = _admin(user_id=71, tenant_id=11)
    admin.email = "admin@example.test"
    admin.wx_avatar_url = None
    monkeypatch.setattr("app.db.session.get_db", lambda: _FakeUserDb(admin))
    monkeypatch.setattr(mobile_ext, "_register_desktop_relay_for_pairing", lambda *_: None)

    async def empty_profiles():
        return {}, False, ""

    monkeypatch.setattr(mobile_ext, "_load_market_ai_employee_profile_index", empty_profiles)
    monkeypatch.setattr(mobile_ext, "_mobile_mod_items", lambda *_args, **_kwargs: [])

    class FakeSyncDb:
        def get_status(self):
            return {}

    monkeypatch.setattr("app.db.xcmax_sync.SyncDb", FakeSyncDb)

    class FakeCodexService:
        def list_messages(self, *, user_id: int, limit: int):
            assert user_id == 71
            assert limit > 0
            return []

    monkeypatch.setattr(mobile_ext, "CodexSuperEmployeeService", FakeCodexService)

    app = _http_app()
    client = TestClient(app, client=("192.168.10.20", 51000))
    app.dependency_overrides[get_mobile_user] = lambda: admin
    issue = client.post(
        "/api/mobile/v1/pairing/issue",
        json={"host": "192.168.10.2", "port": 17500},
    )
    assert issue.status_code == 200
    code = issue.json()["data"]["code"]

    app.dependency_overrides[get_mobile_user] = lambda: None
    exchange = client.post("/api/mobile/v1/pairing/exchange", json={"code": code})
    assert exchange.status_code == 200
    access_token = exchange.json()["data"]["access_token"]
    app.dependency_overrides.clear()
    headers = {"Authorization": f"Bearer {access_token}"}

    # The bound DB row is an administrator, but the real dependency returns a
    # downgraded enterprise projection to every downstream route.
    assert client.get("/api/mobile/v1/admin/home", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/mobile/v1/im/cs/inbox/1/reply",
            headers=headers,
            json={"body": "must not send"},
        ).status_code
        == 403
    )
    assert client.get("/api/mobile/v1/home", headers=headers).status_code == 200
    super_employee = client.get(
        "/api/mobile/v1/admin/codex-super-employee/messages", headers=headers
    )
    assert super_employee.status_code == 200
    assert super_employee.json()["data"]["messages"] == []


def test_legacy_lan_pairing_tokens_are_invalidated_immediately(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SECRET_KEY", "pairing-legacy-rejection-secret-key-at-least-32-bytes")
    app = _http_app()
    client = TestClient(app)
    legacy_missing_scope = issue_mobile_tokens(
        user_id=7,
        session_id="mobile-relay-legacy-no-scope",
        account_kind="enterprise",
        username="legacy",
    )
    legacy_admin = issue_mobile_tokens(
        user_id=7,
        session_id="mobile-relay-legacy-admin",
        account_kind="admin",
        username="legacy-admin",
        token_scope="enterprise_pairing",
        tenant_id=11,
        company_brand="tenant-11",
        paired_by_user_id=7,
    )

    for tokens in (legacy_missing_scope, legacy_admin):
        assert verify_mobile_jwt(tokens["access_token"]) is None
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        assert client.get("/api/mobile/v1/home", headers=headers).status_code == 401
        assert client.get("/api/mobile/v1/admin/home", headers=headers).status_code == 401
        assert (
            client.get(
                "/api/mobile/v1/admin/codex-super-employee/messages", headers=headers
            ).status_code
            == 401
        )
        refresh = client.post(
            "/api/mobile/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refresh.status_code == 401
        assert "无效或已过期" in refresh.json()["message"]


def test_pairing_code_failures_lock_source_without_blocking_other_client_or_tenant(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SECRET_KEY", "pairing-rate-limit-secret-key-at-least-32-bytes")
    monkeypatch.setattr(mobile_ext, "_register_desktop_relay_for_pairing", lambda *_: None)
    monkeypatch.setattr(
        mobile_ext,
        "_pairing_subject_user",
        lambda record: {
            "id": record["subject_user_id"],
            "username": record["subject_username"],
            "role": "enterprise",
            "tier": "enterprise",
            "tenant_id": record["tenant_id"],
            "is_active": True,
        },
    )
    app = _http_app()
    issuer = TestClient(app, client=("192.168.20.2", 52000))

    app.dependency_overrides[get_mobile_user] = lambda: _admin(user_id=7, tenant_id=11)
    first = issuer.post(
        "/api/mobile/v1/pairing/issue",
        json={"host": "192.168.20.2", "port": 17500},
    )
    assert first.status_code == 200

    app.dependency_overrides[get_mobile_user] = lambda: _admin(user_id=8, tenant_id=22)
    second = issuer.post(
        "/api/mobile/v1/pairing/issue",
        json={"host": "192.168.20.2", "port": 17500},
    )
    assert second.status_code == 200
    tenant_22_code = second.json()["data"]["code"]
    app.dependency_overrides[get_mobile_user] = lambda: None

    attacker = TestClient(app, client=("192.168.20.88", 53000))
    attack_headers = {"X-Device-ID": "attacker-device"}
    for _ in range(PAIRING_FAILURE_LIMIT - 1):
        rejected = attacker.post(
            "/api/mobile/v1/pairing/exchange",
            json={"code": "000000"},
            headers=attack_headers,
        )
        assert rejected.status_code == 400
    locked = attacker.post(
        "/api/mobile/v1/pairing/exchange",
        json={"code": "000000"},
        headers=attack_headers,
    )
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0

    # Locking is source-scoped: another LAN device can still exchange the exact
    # code that was bound to tenant 22.
    legitimate = TestClient(app, client=("192.168.20.99", 54000))
    exchanged = legitimate.post(
        "/api/mobile/v1/pairing/exchange",
        json={"code": tenant_22_code},
        headers={"X-Device-ID": "tenant-22-phone"},
    )
    assert exchanged.status_code == 200
    assert exchanged.json()["data"]["tenant_id"] == 22
