"""COVERAGE_RAMP Phase 1 (p0-core): routes/domains static, rbac, mobile ext (mocked TestClient)."""

from __future__ import annotations

import base64
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import mobile_api as mobile_api_mod
from app.fastapi_routes import rbac as rbac_routes
from app.fastapi_routes.domains.static import routes as static_routes
from app.infrastructure.auth import tenant_context

# mobile_api 末尾才挂载 extension_router，须先 import mobile_api 打破循环依赖
import app.fastapi_routes.mobile_api_extensions as mobile_ext  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user() -> SimpleNamespace:
    return SimpleNamespace(id=1, username="admin", role="admin")


@pytest.fixture
def rbac_client(admin_user: SimpleNamespace) -> TestClient:
    app = FastAPI()
    app.include_router(rbac_routes.router)
    app.dependency_overrides[rbac_routes._require_admin] = lambda: admin_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def static_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    vue_dist = tmp_path / "templates" / "vue-dist"
    static_dir = vue_dist / "static"
    static_dir.mkdir(parents=True)
    (vue_dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (vue_dist / "vite.svg").write_text("<svg/>", encoding="utf-8")
    (vue_dist / "brand-xc-logo.png").write_bytes(b"\x89PNG")
    (vue_dist / "sw.js").write_text("// sw", encoding="utf-8")
    (vue_dist / "workflow-employees.json").write_text("{}", encoding="utf-8")
    (static_dir / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setattr(static_routes, "get_base_dir", lambda: str(tmp_path))
    app = FastAPI()
    app.include_router(static_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mobile_ext_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes.mobile_api import get_mobile_user

    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    app.dependency_overrides[get_mobile_user] = lambda: SimpleNamespace(id=1, username="mobile")
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# RBAC routes
# ---------------------------------------------------------------------------


def test_rbac_list_tenants(rbac_client: TestClient) -> None:
    r = rbac_client.get("/api/rbac/tenants")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_rbac_list_roles(rbac_client: TestClient) -> None:
    r = rbac_client.get("/api/rbac/roles")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_rbac_create_role(rbac_client: TestClient) -> None:
    r = rbac_client.post(
        "/api/rbac/roles",
        json={"name": "editor", "description": "编辑", "permissions": ["read"]},
    )
    assert r.status_code == 201
    assert r.json()["data"]["name"] == "editor"


def test_rbac_get_role(rbac_client: TestClient) -> None:
    r = rbac_client.get("/api/rbac/roles/3")
    assert r.status_code == 200
    assert r.json()["data"]["id"] == 3


def test_rbac_update_role(rbac_client: TestClient) -> None:
    r = rbac_client.put("/api/rbac/roles/2", json={"description": "新描述"})
    assert r.status_code == 200


def test_rbac_delete_role(rbac_client: TestClient) -> None:
    r = rbac_client.delete("/api/rbac/roles/9")
    assert r.status_code == 200


def test_rbac_permissions_list(rbac_client: TestClient) -> None:
    r = rbac_client.get("/api/rbac/permissions")
    assert r.status_code == 200


def test_rbac_permission_create(rbac_client: TestClient) -> None:
    r = rbac_client.post(
        "/api/rbac/permissions",
        json={"code": "erp.read", "name": "读取 ERP"},
    )
    assert r.status_code == 201


def test_rbac_user_permissions(rbac_client: TestClient) -> None:
    r = rbac_client.get("/api/rbac/users/5/permissions")
    assert r.status_code == 200


def test_rbac_assign_user_role(rbac_client: TestClient) -> None:
    r = rbac_client.put("/api/rbac/users/5/role", json={"role": "editor"})
    assert r.status_code == 200


def test_rbac_seed_permissions(rbac_client: TestClient) -> None:
    r = rbac_client.post("/api/rbac/seed-missing-permissions")
    assert r.status_code == 200
    assert "added" in r.json()


def test_rbac_tenant_data_scopes(rbac_client: TestClient) -> None:
    r = rbac_client.get("/api/rbac/tenants/1/data-scopes")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Static / SPA routes
# ---------------------------------------------------------------------------


def test_static_index_serves_spa(static_client: TestClient) -> None:
    r = static_client.get("/")
    assert r.status_code == 200
    assert "spa" in r.text


def test_static_serve_js(static_client: TestClient) -> None:
    r = static_client.get("/static/app.js")
    assert r.status_code == 200


def test_static_missing_asset_404(static_client: TestClient) -> None:
    r = static_client.get("/static/missing.js")
    assert r.status_code == 404


def test_static_vite_svg(static_client: TestClient) -> None:
    r = static_client.get("/vite.svg")
    assert r.status_code == 200


def test_static_brand_logo_png(static_client: TestClient) -> None:
    r = static_client.get("/brand-xc-logo.png")
    assert r.status_code == 200


def test_static_favicon(static_client: TestClient) -> None:
    r = static_client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_static_sw_js(static_client: TestClient) -> None:
    r = static_client.get("/sw.js")
    assert r.status_code == 200


def test_static_workflow_employees_json(static_client: TestClient) -> None:
    r = static_client.get("/workflow-employees.json")
    assert r.status_code == 200


def test_static_console_route(static_client: TestClient) -> None:
    r = static_client.get("/console")
    assert r.status_code == 200


def test_static_traditional_list(monkeypatch: pytest.MonkeyPatch, static_client: TestClient) -> None:
    monkeypatch.setattr(
        static_routes,
        "list_files_response",
        lambda path: ({"success": True, "files": []}, 200),
    )
    r = static_client.get("/api/traditional-mode/list")
    assert r.status_code == 200


def test_static_traditional_root(monkeypatch: pytest.MonkeyPatch, static_client: TestClient) -> None:
    monkeypatch.setattr(static_routes, "root_info_response", lambda: {"root": "/"})
    r = static_client.get("/api/traditional-mode/root")
    assert r.status_code == 200


def test_static_traditional_write_empty_body(static_client: TestClient) -> None:
    r = static_client.post("/api/traditional-mode/write", json={})
    assert r.status_code == 400


def test_static_traditional_write_forbidden_path(
    monkeypatch: pytest.MonkeyPatch, static_client: TestClient
) -> None:
    monkeypatch.setattr(static_routes, "resolve_safe_path", lambda rel: None)
    r = static_client.post(
        "/api/traditional-mode/write",
        json={"file": "../etc/passwd", "type": "excel", "data": {}},
    )
    assert r.status_code == 403


def test_static_traditional_agent_write_text(
    monkeypatch: pytest.MonkeyPatch, static_client: TestClient
) -> None:
    monkeypatch.setattr(
        static_routes,
        "write_text_response",
        lambda f, c, append=False: ({"success": True}, 200),
    )
    r = static_client.post(
        "/api/traditional-mode/agent/write-text",
        json={"file": "a.txt", "content": "hi"},
    )
    assert r.status_code == 200


def test_static_traditional_agent_write_base64(
    monkeypatch: pytest.MonkeyPatch, static_client: TestClient
) -> None:
    payload = base64.b64encode(b"hello").decode()
    monkeypatch.setattr(
        static_routes,
        "write_base64_response",
        lambda f, c: ({"success": True}, 200),
    )
    r = static_client.post(
        "/api/traditional-mode/agent/write-base64",
        json={"file": "a.bin", "content_base64": payload},
    )
    assert r.status_code == 200


def test_static_traditional_agent_move_copy(
    monkeypatch: pytest.MonkeyPatch, static_client: TestClient
) -> None:
    monkeypatch.setattr(
        static_routes,
        "move_response",
        lambda src, dst, overwrite=False: ({"success": True}, 200),
    )
    monkeypatch.setattr(
        static_routes,
        "copy_response",
        lambda src, dst, overwrite=False: ({"success": True}, 200),
    )
    assert static_client.post(
        "/api/traditional-mode/agent/move",
        json={"src": "a", "dst": "b"},
    ).status_code == 200
    assert static_client.post(
        "/api/traditional-mode/agent/copy",
        json={"src": "a", "dst": "b"},
    ).status_code == 200


def test_static_outputs_missing(tmp_path, monkeypatch: pytest.MonkeyPatch, static_client: TestClient) -> None:
    monkeypatch.setattr(
        "app.utils.path_utils.get_app_data_dir",
        lambda: str(tmp_path / "missing_outputs"),
    )
    monkeypatch.setattr(
        "app.utils.path_utils.get_resource_path",
        lambda *a, **k: str(tmp_path / "also_missing"),
    )
    r = static_client.get("/outputs/file.xlsx")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Mobile API extensions
# ---------------------------------------------------------------------------


def test_mobile_approval_list_unauthorized() -> None:
    from app.fastapi_routes.mobile_api import get_mobile_user

    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    app.dependency_overrides[get_mobile_user] = lambda: None
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/approval/requests")
    assert r.status_code == 401


@patch("app.db.session.get_db")
def test_mobile_approval_list_success(mock_get_db: MagicMock, mobile_ext_client: TestClient) -> None:
    mock_db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_db
    cm.__exit__.return_value = None
    mock_get_db.return_value = cm
    row = SimpleNamespace(
        id=1,
        title="请假",
        status="pending",
        request_no="R001",
        applicant_id=2,
        created_at=None,
    )
    q = MagicMock()
    q.filter.return_value = q
    q.count.return_value = 1
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = [row]
    mock_db.query.return_value = q
    r = mobile_ext_client.get("/approval/requests")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_mobile_pairing_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mobile_ext,
        "issue_pairing_nonce",
        lambda host, port: {"nonce": "abc", "code": "123456"},
    )
    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/pairing/issue", json={"host": "127.0.0.1", "port": 5000})
    assert r.status_code == 200


def test_mobile_pairing_lookup_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobile_ext, "lookup_by_shortcode", lambda code: None)
    app = FastAPI()
    app.include_router(mobile_ext.extension_router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/pairing/lookup", json={"code": "000000"})
    assert r.status_code == 404


def test_tenant_context_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    req = MagicMock()
    monkeypatch.setattr(tenant_context, "session_id_from_request", lambda r: "sid")
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda sid: {"tenant_id": 7},
    )
    assert tenant_context.resolve_tenant_id(req) == 7
    assert tenant_context.tenant_id_for_user(SimpleNamespace(tenant_id=3)) == 3


def test_tenant_context_resolve_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    req = MagicMock()
    monkeypatch.setattr(tenant_context, "session_id_from_request", lambda r: "sid")

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        _boom,
    )
    assert tenant_context.resolve_tenant_id(req) is None
