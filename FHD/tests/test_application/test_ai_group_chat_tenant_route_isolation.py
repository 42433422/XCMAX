"""Route-level tenant isolation for admin/mobile AI group chat.

These tests go through IndustryContextMiddleware and auth dependencies with
ASGI TestClient. They must not wrap calls in tenant_scope, so a passing
result means current_tenant_id() was established by the request path.
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_group_chat_service import AiGroupChatService
from app.infrastructure.request_context import get_current_request
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope

# 测试内的显式边界：响应体解析失败与线程内异常收集都需要捕获全部错误，
# 用命名元组替代直接 broad except，满足 broad-except 门禁。
_BODY_DECODE_ERRORS = (ValueError, TypeError)
_THREAD_ERRORS = (Exception,)


async def _complete(_history: list[dict[str, str]]) -> dict[str, Any]:
    return {"success": True, "content": "已记录"}


def _service(tmp_path: Path) -> AiGroupChatService:
    return AiGroupChatService(
        storage_root=tmp_path,
        completion_fn=_complete,
        department_loader=lambda: {},
        employee_loader=lambda: [{"employee_id": "worker", "name": "同事", "department_key": ""}],
    )


def _user(*, user_id: int, tenant_id: int | None, username: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        is_active=True,
        role="enterprise",
        tier="enterprise",
        username=username,
        display_name=username,
        email=f"{username}@example.test",
        industry_id="通用",
        wx_avatar_url=None,
    )


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "ai-group-tenant-route-isolation-test-secret")
    monkeypatch.delenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", raising=False)


def _legacy_shared(tmp_path: Path) -> Path:
    legacy = tmp_path / "ai_group_chat"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "groups.jsonl").write_text(
        json.dumps(
            {"id": "legacy-shared", "user_id": 1, "name": "共享目录旧群"}, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )
    return legacy


def _group_names(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    groups = payload.get("groups")
    if groups is None and isinstance(payload.get("data"), dict):
        groups = payload["data"].get("groups")
    return [str(row.get("name") or "") for row in groups or [] if isinstance(row, dict)]


def _body_text(resp) -> str:
    try:
        return json.dumps(resp.json(), ensure_ascii=False)
    except _BODY_DECODE_ERRORS:
        return resp.text


def _assert_no_existence_leak(resp, *secrets: str) -> None:
    text = _body_text(resp)
    for secret in secrets:
        assert secret not in text
    assert resp.status_code != 500


def _assert_cross_tenant_denied(resp, *secrets: str) -> None:
    _assert_no_existence_leak(resp, *secrets)
    assert resp.status_code in {403, 404}


def _extract_filter_int(expr: Any) -> int | None:
    if expr is None:
        return None
    if isinstance(expr, int):
        return expr
    value = getattr(expr, "value", None)
    if value is not None and not callable(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    for attr in ("right", "left", "element", "clause"):
        if hasattr(expr, attr):
            found = _extract_filter_int(getattr(expr, attr))
            if found is not None:
                return found
    return None


def _install_session_users(monkeypatch: pytest.MonkeyPatch, users_by_sid: dict[str, Any]) -> None:
    session_service = MagicMock()
    session_service.validate_session.side_effect = lambda sid: users_by_sid.get(str(sid or ""))
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_session_service",
        lambda: session_service,
    )
    monkeypatch.setattr(
        "app.application.desktop_admin_gate.assert_desktop_allows_session_id",
        lambda _sid: None,
    )


def _install_mobile_user_db(monkeypatch: pytest.MonkeyPatch, users_by_id: dict[int, Any]) -> None:
    class _Query:
        def __init__(self) -> None:
            self._uid: int | None = None

        def query(self, _model: Any) -> _Query:
            return self

        def filter(self, *criteria: Any) -> _Query:
            for item in criteria:
                found = _extract_filter_int(item)
                if found is not None:
                    self._uid = found
            return self

        def first(self) -> Any | None:
            if self._uid is None:
                return None
            return users_by_id.get(self._uid)

    @contextmanager
    def _get_db():
        yield _Query()

    monkeypatch.setattr("app.db.session.get_db", _get_db)
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda _sid: None,
    )


def _install_runtime_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def _runtime(request, raw=None) -> dict[str, Any]:
        from app.infrastructure.auth.dependencies import resolve_session_user
        from app.security.mobile_jwt import user_id_from_mobile_bearer

        user = resolve_session_user(request)
        if user is not None and getattr(user, "id", None) is not None:
            return {"user_id": int(user.id)}
        uid = user_id_from_mobile_bearer(request.headers.get("Authorization"))
        return {"user_id": int(uid or 0)}

    monkeypatch.setattr(
        "app.fastapi_routes.domains.agent.route_support.request_runtime_context",
        _runtime,
    )


def _build_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    observed: list[int | None],
) -> FastAPI:
    from app.fastapi_routes import im_ai_group_routes as admin_routes
    from app.fastapi_routes.mobile_api import get_mobile_user
    from app.fastapi_routes.mobile_extensions.admin_helpers import (
        _mobile_request_user_id,
        _mobile_session_meta,
        _require_mobile_admin_or_enterprise,
    )
    from app.fastapi_routes.mobile_extensions.routes_ai_groups import GroupRoutes, GroupRoutesPorts
    from app.middleware.industry_context import IndustryContextMiddleware

    monkeypatch.setattr(
        "app.application.group_chat.storage.get_app_data_dir",
        lambda **_k: str(tmp_path),
    )
    facade = admin_routes._facade()
    monkeypatch.setattr(facade, "_ai_group_guard", lambda _request: None)

    def _factory(*args: Any, **kwargs: Any) -> AiGroupChatService:
        observed.append(current_tenant_id())
        # Do not pass storage_root: production routes resolve through get_app_data_dir,
        # and an explicit root would incorrectly enable unscoped compatibility.
        kwargs.setdefault("completion_fn", _complete)
        kwargs.setdefault("department_loader", lambda: {})
        kwargs.setdefault(
            "employee_loader",
            lambda: [{"employee_id": "worker", "name": "同事", "department_key": ""}],
        )
        return AiGroupChatService(*args, **kwargs)

    monkeypatch.setattr(facade, "AiGroupChatService", _factory)
    _install_runtime_context(monkeypatch)

    app = FastAPI()
    app.add_middleware(IndustryContextMiddleware)
    app.include_router(admin_routes.router)
    routes = GroupRoutes(
        GroupRoutesPorts(
            mobile_request_user_id=_mobile_request_user_id,
            mobile_session_meta=_mobile_session_meta,
            require_mobile_admin_or_enterprise=_require_mobile_admin_or_enterprise,
            ai_group_service=_factory,
            mobile_group_mode=lambda request: (
                "admin"
                if str((_mobile_session_meta(request) or {}).get("account_kind") or "")
                .strip()
                .lower()
                == "admin"
                else "enterprise"
            ),
            mobile_group_uid=_mobile_request_user_id,
        ),
        get_mobile_user,
    )
    app.include_router(routes.router, prefix="/api/mobile/v1")
    return app


def test_bound_instance_keeps_tenant_after_context_and_worker_cleanup(tmp_path: Path) -> None:
    with tenant_scope(11):
        service = _service(tmp_path)
        group = service.create_group(user_id=1, name="甲的群")
        bound_root = service._storage._groups_path

    assert current_tenant_id() is None
    assert get_current_request() is None
    names = [row["name"] for row in service.list_groups(user_id=1)]
    assert names == ["甲的群"]

    async def _late_reply() -> None:
        def _worker() -> str:
            # Thread starts without the original request context; bound scope must restore it.
            return "ok"

        assert await asyncio.to_thread(_worker) == "ok"
        await service.post_message(user_id=1, group_id=group["id"], text="迟到回复")

    asyncio.run(_late_reply())
    assert current_tenant_id() is None
    bodies = [row["body"] for row in service.get_messages(user_id=1, group_id=group["id"])]
    assert "迟到回复" in bodies
    raw = bound_root.read_text(encoding="utf-8")
    assert "甲的群" in raw
    other = tmp_path / "tenants" / "22" / "ai_group_chat" / "groups.jsonl"
    assert not other.exists()


def test_concurrent_tenant_contexts_do_not_cross_write(tmp_path: Path) -> None:
    errors: list[BaseException] = []

    def _write(tid: int, name: str) -> None:
        try:
            with tenant_scope(tid):
                _service(tmp_path).create_group(user_id=1, name=name)
        except _THREAD_ERRORS as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_write, 11, "甲的群")
        second = pool.submit(_write, 22, "乙的群")
        first.result()
        second.result()

    assert errors == []
    a = (tmp_path / "tenants" / "11" / "ai_group_chat" / "groups.jsonl").read_text(encoding="utf-8")
    b = (tmp_path / "tenants" / "22" / "ai_group_chat" / "groups.jsonl").read_text(encoding="utf-8")
    assert "甲的群" in a and "乙的群" not in a
    assert "乙的群" in b and "甲的群" not in b
    assert current_tenant_id() is None


def test_sticky_instance_does_not_follow_later_tenant_scope(tmp_path: Path) -> None:
    with tenant_scope(11):
        sticky = _service(tmp_path)
        sticky.create_group(user_id=1, name="甲的群")
    with tenant_scope(22):
        names = [row["name"] for row in sticky.list_groups(user_id=1)]
        assert names == ["甲的群"]
        sticky.create_group(user_id=1, name="不应写入乙")
    a = (tmp_path / "tenants" / "11" / "ai_group_chat" / "groups.jsonl").read_text(encoding="utf-8")
    b_path = tmp_path / "tenants" / "22" / "ai_group_chat" / "groups.jsonl"
    assert "甲的群" in a
    assert "不应写入乙" in a
    assert not b_path.exists()


def test_admin_and_mobile_routes_establish_tenant_and_hide_cross_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.security.mobile_jwt import issue_mobile_tokens

    _legacy_shared(tmp_path)
    user_a = _user(user_id=101, tenant_id=11, username="alice")
    user_b = _user(user_id=202, tenant_id=22, username="bob")
    _install_session_users(
        monkeypatch,
        {"sess-a": user_a, "sess-b": user_b},
    )
    _install_mobile_user_db(monkeypatch, {101: user_a, 202: user_b})
    observed: list[int | None] = []
    app = _build_app(tmp_path, monkeypatch, observed=observed)
    secrets = ("甲的群", "甲的机密", "共享目录旧群")

    with TestClient(app) as client:

        def admin_headers(sid: str) -> dict[str, str]:
            return {"Cookie": f"session_id={sid}"}

        def mobile_headers(user_id: int, sid: str) -> dict[str, str]:
            tokens = issue_mobile_tokens(
                user_id=user_id, session_id=sid, account_kind="enterprise", username=f"u{user_id}"
            )
            return {"Authorization": f"Bearer {tokens['access_token']}"}

        # --- admin: tenant A via session cookie / middleware ---
        created = client.post(
            "/api/admin/ai-groups",
            json={"name": "甲的群"},
            headers=admin_headers("sess-a"),
        )
        assert created.status_code == 200, created.text
        assert created.json()["success"] is True
        group_id = created.json()["group"]["id"]

        added = client.post(
            f"/api/admin/ai-groups/{group_id}/members",
            json={"employee_id": "worker", "name": "同事"},
            headers=admin_headers("sess-a"),
        )
        assert added.status_code == 200, added.text

        posted = client.post(
            f"/api/admin/ai-groups/{group_id}/messages",
            json={"message": "甲的机密", "dispatch": False},
            headers=admin_headers("sess-a"),
        )
        assert posted.status_code == 200, posted.text

        listed = client.get("/api/admin/ai-groups", headers=admin_headers("sess-a"))
        assert listed.status_code == 200
        assert "甲的群" in _group_names(listed.json())
        messages = client.get(
            f"/api/admin/ai-groups/{group_id}/messages", headers=admin_headers("sess-a")
        )
        assert messages.status_code == 200
        bodies = [row.get("body") for row in messages.json().get("messages") or []]
        assert "甲的机密" in bodies

        # tenant B via a new request; middleware must switch tenant without tenant_scope
        other_list = client.get("/api/admin/ai-groups", headers=admin_headers("sess-b"))
        assert other_list.status_code == 200
        assert "甲的群" not in _group_names(other_list.json())
        _assert_no_existence_leak(other_list, *secrets)

        other_messages = client.get(
            f"/api/admin/ai-groups/{group_id}/messages", headers=admin_headers("sess-b")
        )
        assert other_messages.status_code in {200, 403, 404}
        other_bodies = [
            row.get("body")
            for row in (other_messages.json().get("messages") or [])
            if isinstance(row, dict)
        ]
        assert "甲的机密" not in other_bodies
        _assert_no_existence_leak(other_messages, *secrets)

        other_send = client.post(
            f"/api/admin/ai-groups/{group_id}/messages",
            json={"message": "试探", "dispatch": False},
            headers=admin_headers("sess-b"),
        )
        _assert_cross_tenant_denied(other_send, *secrets)

        other_member = client.post(
            f"/api/admin/ai-groups/{group_id}/members",
            json={"employee_id": "worker", "name": "同事"},
            headers=admin_headers("sess-b"),
        )
        _assert_cross_tenant_denied(other_member, *secrets)

        # --- mobile JWT only (no session cookie): bind must set request.state.tenant_id ---
        token_a = mobile_headers(101, "jwt-a")
        token_b = mobile_headers(202, "jwt-b")
        mobile_create = client.post(
            "/api/mobile/v1/ai-groups", json={"name": "甲的移动群"}, headers=token_a
        )
        assert mobile_create.status_code == 200, mobile_create.text
        mobile_group = (mobile_create.json().get("data") or {}).get("group") or {}
        mobile_id = str(mobile_group.get("id") or "")
        assert mobile_id

        mobile_add = client.post(
            f"/api/mobile/v1/ai-groups/{mobile_id}/members",
            json={"employee_id": "worker", "name": "同事"},
            headers=token_a,
        )
        assert mobile_add.status_code == 200, mobile_add.text
        mobile_post = client.post(
            f"/api/mobile/v1/ai-groups/{mobile_id}/messages",
            json={"message": "甲的机密", "dispatch": False},
            headers=token_a,
        )
        assert mobile_post.status_code == 200, mobile_post.text
        mobile_read = client.get(f"/api/mobile/v1/ai-groups/{mobile_id}/messages", headers=token_a)
        assert mobile_read.status_code == 200
        mobile_pin = client.put(f"/api/mobile/v1/ai-groups/{mobile_id}/pin", headers=token_a)
        assert mobile_pin.status_code == 200, mobile_pin.text
        mobile_mark = client.post(
            f"/api/mobile/v1/ai-groups/{mobile_id}/mark-read", headers=token_a
        )
        assert mobile_mark.status_code == 200, mobile_mark.text

        mobile_list_b = client.get("/api/mobile/v1/ai-groups", headers=token_b)
        assert mobile_list_b.status_code == 200
        assert "甲的移动群" not in _group_names(mobile_list_b.json())
        _assert_no_existence_leak(mobile_list_b, "甲的移动群", *secrets)

        for method, path in (
            ("GET", f"/api/mobile/v1/ai-groups/{mobile_id}/messages"),
            ("POST", f"/api/mobile/v1/ai-groups/{mobile_id}/messages"),
            ("POST", f"/api/mobile/v1/ai-groups/{mobile_id}/members"),
            ("PUT", f"/api/mobile/v1/ai-groups/{mobile_id}/pin"),
            ("POST", f"/api/mobile/v1/ai-groups/{mobile_id}/mark-read"),
            ("PUT", f"/api/mobile/v1/ai-groups/{mobile_id}/hidden"),
        ):
            kwargs: dict[str, Any] = {"headers": token_b}
            if method == "POST" and path.endswith("/messages"):
                kwargs["json"] = {"message": "试探", "dispatch": False}
            elif method == "POST" and path.endswith("/members"):
                kwargs["json"] = {"employee_id": "worker", "name": "同事"}
            resp = client.request(method, path, **kwargs)
            if method == "GET":
                assert resp.status_code in {200, 403, 404}
                payload = resp.json()
                data = payload.get("data") if isinstance(payload, dict) else {}
                bodies = [
                    row.get("body")
                    for row in ((data or {}).get("messages") or [])
                    if isinstance(row, dict)
                ]
                assert "甲的机密" not in bodies
                _assert_no_existence_leak(resp, "甲的移动群", *secrets)
            else:
                _assert_cross_tenant_denied(resp, "甲的移动群", *secrets)

        hide_ok = client.put(f"/api/mobile/v1/ai-groups/{mobile_id}/hidden", headers=token_a)
        assert hide_ok.status_code == 200, hide_ok.text

        assert current_tenant_id() is None
        assert get_current_request() is None

    assert 11 in observed
    assert 22 in observed
    assert None not in observed
    legacy = (tmp_path / "ai_group_chat" / "groups.jsonl").read_text(encoding="utf-8")
    assert "共享目录旧群" in legacy
    assert "甲的群" not in legacy
    assert "甲的移动群" not in legacy
    assert "试探" not in legacy


def test_authenticated_desktop_null_tenant_is_fail_closed_and_leaves_legacy_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _legacy_shared(tmp_path)
    bound = _user(user_id=301, tenant_id=11, username="desktop-bound")
    unbound = _user(user_id=302, tenant_id=None, username="desktop-null")
    _install_session_users(monkeypatch, {"sess-bound": bound, "sess-null": unbound})
    observed: list[int | None] = []
    app = _build_app(tmp_path, monkeypatch, observed=observed)

    with TestClient(app) as client:
        ok = client.post(
            "/api/admin/ai-groups",
            json={"name": "桌面合法群"},
            headers={"Cookie": "session_id=sess-bound"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["group"]["name"] == "桌面合法群"

        denied_list = client.get("/api/admin/ai-groups", headers={"Cookie": "session_id=sess-null"})
        assert denied_list.status_code == 200
        assert _group_names(denied_list.json()) == []
        _assert_no_existence_leak(denied_list, "桌面合法群", "共享目录旧群")

        denied_create = client.post(
            "/api/admin/ai-groups",
            json={"name": "不应写入"},
            headers={"Cookie": "session_id=sess-null"},
        )
        _assert_cross_tenant_denied(denied_create, "桌面合法群", "共享目录旧群")

        assert current_tenant_id() is None
        assert get_current_request() is None

    legacy = (tmp_path / "ai_group_chat" / "groups.jsonl").read_text(encoding="utf-8")
    assert "共享目录旧群" in legacy
    assert "不应写入" not in legacy
    assert "桌面合法群" not in legacy
    # observed includes None for the fail-closed authenticated-but-unbound request
    assert 11 in observed


def test_unauthenticated_request_does_not_relax_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _legacy_shared(tmp_path)
    _install_session_users(monkeypatch, {})
    observed: list[int | None] = []
    app = _build_app(tmp_path, monkeypatch, observed=observed)
    with TestClient(app) as client:
        listed = client.get("/api/admin/ai-groups")
        # missing identity may 401, or reach the handler and return empty
        if listed.status_code == 200:
            assert "共享目录旧群" not in _group_names(listed.json())
        else:
            assert listed.status_code in {401, 403}
        _assert_no_existence_leak(listed, "共享目录旧群")
    legacy = (tmp_path / "ai_group_chat" / "groups.jsonl").read_text(encoding="utf-8")
    assert "共享目录旧群" in legacy


def test_request_threads_clean_up_tenant_context(tmp_path: Path) -> None:
    barrier = threading.Barrier(2)
    seen: dict[str, int | None] = {}
    errors: list[BaseException] = []

    def _run(label: str, tid: int) -> None:
        try:
            with tenant_scope(tid):
                barrier.wait(timeout=5)
                seen[label] = current_tenant_id()
            seen[f"{label}-after"] = current_tenant_id()
        except _THREAD_ERRORS as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_run, "a", 11)
        second = pool.submit(_run, "b", 22)
        first.result()
        second.result()

    assert errors == []
    assert seen["a"] == 11
    assert seen["b"] == 22
    assert seen["a-after"] is None
    assert seen["b-after"] is None
    assert current_tenant_id() is None
