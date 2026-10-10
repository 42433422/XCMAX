"""Admin/write endpoints require real credentials; a forged bearer no longer skips CSRF."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server.application.auth import AuthApplicationService, AuthenticationError

ADMIN = {"Authorization": "Bearer admin-token"}
MEMBER = {"Authorization": "Bearer member-token"}


@pytest.fixture(autouse=True)
def _fake_tokens(monkeypatch):
    users = {
        "Bearer admin-token": SimpleNamespace(id=7, is_admin=True),
        "Bearer member-token": SimpleNamespace(id=8, is_admin=False),
    }

    def _resolve(_self, authorization):
        if authorization not in users:
            raise AuthenticationError("凭证无效或已过期")
        return users[authorization]

    monkeypatch.setattr(AuthApplicationService, "current_user_from_authorization", _resolve)


def _client(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_production_line_mutations_require_admin_and_ignore_body_identity() -> None:
    from modstore_server.production_line_api import router

    client = _client(router)
    for path in ("/run", "/stop", "/steps/P1/approve", "/steps/P1/reject"):
        url = f"/api/admin/production-line{path}"
        assert client.post(url, json={}).status_code == 401
        assert client.post(url, json={}, headers={"Authorization": "Bearer x"}).status_code == 401
        assert client.post(url, json={}, headers=MEMBER).status_code == 403

    step = SimpleNamespace(step_id="P1", status=SimpleNamespace(value="approved"))
    approve = AsyncMock(return_value=step)
    with patch(
        "modstore_server.production_line_orchestrator.approve_production_line_step", approve
    ):
        r = client.post(
            "/api/admin/production-line/steps/P1/approve",
            json={"admin_user_id": 999},
            headers=ADMIN,
        )
    assert r.status_code == 200
    approve.assert_awaited_once_with("P1", admin_user_id=7)

    orch = MagicMock()
    with patch(
        "modstore_server.production_line_orchestrator.get_production_line_orchestrator",
        return_value=orch,
    ):
        assert client.post("/api/admin/production-line/stop", headers=ADMIN).status_code == 200
    orch.stop_pipeline.assert_called_once()


def test_put_config_requires_admin(monkeypatch) -> None:
    from modstore_server.api import config

    saved = []
    monkeypatch.setattr(config.library_paths, "save_config", saved.append)
    monkeypatch.setattr(config, "get_config", lambda: {"ok": True})
    client = _client(config.router)
    body = {"xcagi_backend_url": "http://attacker.invalid"}

    assert client.put("/api/config", json=body).status_code == 401
    assert client.put("/api/config", json=body, headers=MEMBER).status_code == 403
    assert saved == []
    assert client.put("/api/config", json=body, headers=ADMIN).status_code == 200
    assert saved[0].xcagi_backend_url == "http://attacker.invalid"


def test_sync_receive_requires_shared_secret(monkeypatch, tmp_path) -> None:
    from modstore_server import xcmax_admin_api
    from modstore_server.xcmax_admin_api import router

    monkeypatch.setenv("XCMAX_SYNC_DB_PATH", str(tmp_path / "sync.db"))
    monkeypatch.setattr(xcmax_admin_api, "_schema_ready", False)
    client = _client(router)
    item = {"entity_type": "personnel", "entity_id": "1", "operation": "insert"}
    url = "/api/xcmax/sync/receive"

    monkeypatch.delenv("XCMAX_SYNC_SHARED_SECRET", raising=False)
    assert client.post(url, json=item, headers={"X-XCMAX-Sync-Token": ""}).status_code == 503

    monkeypatch.setenv("XCMAX_SYNC_SHARED_SECRET", "node-secret")
    assert client.post(url, json=item).status_code == 401
    assert client.post(url, json=item, headers={"X-XCMAX-Sync-Token": "nope"}).status_code == 401
    ok = client.post(url, json=item, headers={"X-XCMAX-Sync-Token": "node-secret"})
    assert ok.status_code == 200
    assert ok.json()["received"] == 1


def test_csrf_bearer_bypass_requires_valid_token(monkeypatch) -> None:
    from modstore_server.api.csrf import CSRFMiddleware

    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    app = FastAPI()

    @app.post("/api/write")
    def write() -> dict:
        return {"ok": True}

    app.add_middleware(CSRFMiddleware)
    client = TestClient(app)
    client.cookies.set("csrf_token", "cookie-token")

    assert client.post("/api/write", headers={"Authorization": "Bearer bogus"}).status_code == 403
    assert client.post("/api/write", headers=ADMIN).status_code == 200
    forged = {"Authorization": "Bearer bogus", "X-CSRF-Token": "cookie-token"}
    assert client.post("/api/write", headers=forged).status_code == 200

    client.cookies.clear()
    assert client.post("/api/write", headers={"Authorization": "Bearer svc"}).status_code == 200
    assert client.post("/api/write").status_code == 403


PL = "/api/admin/production-line"
PL_READS = [
    "/five-line-status",
    "/status",
    "/operations-health",
    "/event-rail/status",
    "/time-rail/graph",
    "/time-rail/status",
    "/webhook-outbox/status",
    "/steps",
]
PL_ADMIN_WRITES = [
    "/time-rail/maintenance/sync",
    "/webhook-outbox/process",
    "/webhook-outbox/replay/1",
]


def test_production_line_reads_need_admin_or_internal_key(monkeypatch) -> None:
    from modstore_server.production_line_api import router

    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "internal-key")
    client = _client(router)
    for path in PL_READS:
        assert client.get(PL + path).status_code == 401, path
        assert client.get(PL + path, headers=MEMBER).status_code == 403, path
        bad_key = {"X-Internal-Api-Key": "nope"}
        assert client.get(PL + path, headers=bad_key).status_code == 401, path

    target = "modstore_server.production_line_orchestrator.get_five_line_status"
    with patch(target, return_value={"lines": 5}):
        for headers in (ADMIN, {"X-Internal-Api-Key": "internal-key"}):
            r = client.get(PL + "/five-line-status", headers=headers)
            assert r.status_code == 200
            assert r.json()["data"] == {"lines": 5}


def test_production_line_admin_writes(monkeypatch) -> None:
    from modstore_server.production_line_api import router

    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "internal-key")
    client = _client(router)
    for path in PL_ADMIN_WRITES:
        assert client.post(PL + path).status_code == 401, path
        assert client.post(PL + path, headers=MEMBER).status_code == 403, path
        internal = {"X-Internal-Api-Key": "internal-key"}
        assert client.post(PL + path, headers=internal).status_code == 401, path

    target = "modstore_server.cs_webhook_outbox.process_pending_outbox"
    with patch(target, return_value={"sent": 0}) as process:
        r = client.post(PL + "/webhook-outbox/process", headers=ADMIN)
    assert r.status_code == 200
    process.assert_called_once_with(limit=20)


@pytest.mark.parametrize("path", ["/event", "/incident"])
def test_ops_line_hooks_need_shared_secret_or_admin(monkeypatch, path) -> None:
    from modstore_server.production_line_api import router

    client = _client(router)
    body = {"step_id": "O1", "status": "done"}
    routed = {"routed": False}
    monkeypatch.delenv("XCAGI_OPS_LINE_HOOK_SECRET", raising=False)
    assert client.post(PL + path, json=body).status_code == 503

    monkeypatch.setenv("XCAGI_OPS_LINE_HOOK_SECRET", "ops-secret")
    assert client.post(PL + path, json=body).status_code == 401
    wrong = {"X-Ops-Line-Secret": "nope"}
    assert client.post(PL + path, json=body, headers=wrong).status_code == 401
    assert client.post(PL + path, json=body, headers=MEMBER).status_code == 403
    with (
        patch(
            "modstore_server.six_line_event_router.handle_operations_line_event",
            return_value=routed,
        ),
        patch("modstore_server.incident_bus.publish_unified_incident", return_value=True),
    ):
        for headers in ({"X-Ops-Line-Secret": "ops-secret"}, ADMIN):
            assert client.post(PL + path, json=body, headers=headers).status_code == 200


SYNC = "/api/xcmax/sync"
SYNC_PEER_CALLS = [
    ("get", "/status"),
    ("get", "/changes"),
    ("post", "/push"),
    ("post", "/pull"),
    ("get", "/conflicts"),
    ("get", "/stream"),
]


def test_sync_routes_need_shared_secret_or_admin(monkeypatch, tmp_path) -> None:
    from modstore_server import xcmax_admin_api
    from modstore_server.xcmax_admin_api import router

    monkeypatch.setenv("XCMAX_SYNC_DB_PATH", str(tmp_path / "sync.db"))
    monkeypatch.setattr(xcmax_admin_api, "_schema_ready", False)
    client = _client(router)
    good = {"X-XCMAX-Sync-Token": "node-secret"}

    monkeypatch.delenv("XCMAX_SYNC_SHARED_SECRET", raising=False)
    for method, path in SYNC_PEER_CALLS:
        assert getattr(client, method)(SYNC + path).status_code == 503, path

    monkeypatch.setenv("XCMAX_SYNC_SHARED_SECRET", "node-secret")
    for method, path in SYNC_PEER_CALLS:
        call = getattr(client, method)
        assert call(SYNC + path).status_code == 401, path
        assert call(SYNC + path, headers={"X-XCMAX-Sync-Token": "x"}).status_code == 401, path
        assert call(SYNC + path, headers=MEMBER).status_code == 403, path
    for method, path in SYNC_PEER_CALLS[:-1]:
        for headers in (good, ADMIN):
            r = getattr(client, method)(SYNC + path, headers=headers)
            assert r.status_code == 200, (path, headers)


def test_sync_conflict_resolve_is_admin_only(monkeypatch, tmp_path) -> None:
    from modstore_server import xcmax_admin_api
    from modstore_server.xcmax_admin_api import router

    monkeypatch.setenv("XCMAX_SYNC_DB_PATH", str(tmp_path / "sync.db"))
    monkeypatch.setattr(xcmax_admin_api, "_schema_ready", False)
    monkeypatch.setenv("XCMAX_SYNC_SHARED_SECRET", "node-secret")
    client = _client(router)
    url = SYNC + "/conflicts/1/resolve"
    body = {"action": "skip"}
    assert client.post(url, json=body).status_code == 401
    peer = {"X-XCMAX-Sync-Token": "node-secret"}
    assert client.post(url, json=body, headers=peer).status_code == 401
    assert client.post(url, json=body, headers=MEMBER).status_code == 403
    assert client.post(url, json=body, headers=ADMIN).status_code == 200


def test_config_read_and_export_require_admin(monkeypatch, tmp_path) -> None:
    from modstore_server.api import config

    fhd = tmp_path / "FHD"
    fhd.mkdir()
    monkeypatch.setattr(config.library_paths, "fhd_repo_root", lambda: fhd)
    monkeypatch.setattr(config.library_paths, "lib", lambda: tmp_path)
    monkeypatch.setattr(config, "write_fhd_shell_mods_json", lambda *a, **k: 0)
    client = _client(config.router)
    calls = [("get", "/api/config"), ("post", "/api/export/fhd-shell-mods")]
    for method, path in calls:
        assert getattr(client, method)(path).status_code == 401, path
        assert getattr(client, method)(path, headers=MEMBER).status_code == 403, path
    assert client.post("/api/export/fhd-shell-mods", headers=ADMIN).status_code == 200


def test_legacy_registry_has_no_config_routes() -> None:
    from modstore_server.routes_registry import api_router

    paths = {getattr(r, "path", "") for r in api_router.routes}
    assert not paths & {"/api/config", "/api/export/fhd-shell-mods"}


def _mount_generated(source: str, monkeypatch, host_auth) -> TestClient:
    import sys
    import types

    if host_auth is None:
        monkeypatch.setitem(sys.modules, "app.infrastructure.auth.dependencies", None)
    else:
        fake = types.ModuleType("app.infrastructure.auth.dependencies")
        fake.require_identified_user = host_auth
        monkeypatch.setitem(sys.modules, "app.infrastructure.auth.dependencies", fake)
    module = types.ModuleType("generated_blueprints")
    exec(compile(source, "generated_blueprints.py", "exec"), module.__dict__)
    monkeypatch.setattr(module, "_dispatch_run", AsyncMock(return_value={"ok": True}))
    app = FastAPI()
    module.register_fastapi_routes(app, "pack")
    return TestClient(app)


def _host_auth(request, x_user_id=None):
    from fastapi import HTTPException

    if request.headers.get("cookie") != "session_id=ok":
        raise HTTPException(401, "请先登录后再执行此操作。")
    return SimpleNamespace(user_id=1)


@pytest.mark.parametrize("kind", ["employee_pack", "mod_suite"])
def test_generated_employee_run_routes_require_host_login(monkeypatch, kind) -> None:
    from modstore_server.employee_pack_blueprints_template import (
        render_employee_pack_blueprints_py,
    )
    from modstore_server.mod_suite_blueprints_template import render_suite_blueprints_py

    if kind == "employee_pack":
        src = render_employee_pack_blueprints_py(
            pack_id="pack", employee_id="emp", stem="emp", label="Emp"
        )
    else:
        src = render_suite_blueprints_py("pack", "Pack", [{"id": "emp", "label": "Emp"}])
    url = "/api/mod/pack/employees/emp/run"

    client = _mount_generated(src, monkeypatch, _host_auth)
    assert client.post(url, json={}).status_code == 401
    ok = client.post(url, json={}, headers={"Cookie": "session_id=ok"})
    assert ok.status_code == 200

    no_host = _mount_generated(src, monkeypatch, None)
    assert no_host.post(url, json={}, headers={"Cookie": "session_id=ok"}).status_code == 401
