"""MODstore HTTP API 集成测试（TestClient）。"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert "deploy_tier" in j and j["deploy_tier"]
    assert "git_sha" in j
    assert "hostname" in j
    assert "tavily_configured" in j and isinstance(j["tavily_configured"], bool)


def test_openapi_schema(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "XC AGI"
    paths = spec.get("paths", {})
    assert "/api/mods" in paths
    assert "/api/debug/sandbox" in paths


def test_create_list_get_mod(client, library: Path, auth_headers: dict):
    r = client.post(
        "/api/mods/create",
        json={"mod_id": "api-test-mod", "display_name": "API Test"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert (library / "api-test-mod" / "manifest.json").is_file()

    r = client.get("/api/mods", headers=auth_headers)
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()["data"]]
    assert "api-test-mod" in ids

    r = client.get("/api/mods/api-test-mod", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == "api-test-mod"


def test_mod_file_get_put(client, library: Path, auth_headers: dict):
    client.post(
        "/api/mods/create",
        json={"mod_id": "file-mod", "display_name": "F"},
        headers=auth_headers,
    )
    r = client.put(
        "/api/mods/file-mod/file",
        json={"path": "notes.md", "content": "# hi\n"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert (library / "file-mod" / "notes.md").read_text(encoding="utf-8") == "# hi\n"

    r = client.get("/api/mods/file-mod/file", params={"path": "notes.md"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["content"] == "# hi\n"


def test_debug_sandbox_copy(client, library: Path, project_home: Path, auth_headers: dict):
    client.post(
        "/api/mods/create",
        json={"mod_id": "sand-mod", "display_name": "S"},
        headers=auth_headers,
    )
    r = client.post(
        "/api/debug/sandbox",
        json={"mod_id": "sand-mod", "mode": "copy"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    root = Path(data["mods_root"])
    assert root.is_dir()
    assert root.parent.parent.parent == project_home
    assert (root / "sand-mod" / "manifest.json").is_file()


def test_focus_primary(client, library: Path, auth_headers: dict):
    client.post(
        "/api/mods/create", json={"mod_id": "p-a", "display_name": "A"}, headers=auth_headers
    )
    client.post(
        "/api/mods/create", json={"mod_id": "p-b", "display_name": "B"}, headers=auth_headers
    )
    r = client.post("/api/debug/focus-primary", json={"mod_id": "p-b"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    ma = json.loads((library / "p-a" / "manifest.json").read_text(encoding="utf-8"))
    mb = json.loads((library / "p-b" / "manifest.json").read_text(encoding="utf-8"))
    assert ma.get("primary") is False
    assert mb.get("primary") is True


def test_import_zip(client, library: Path, auth_headers: dict):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "id": "zip-mod",
            "name": "Z",
            "version": "1.0.0",
            "backend": {"entry": "blueprints", "init": "mod_init"},
            "frontend": {"routes": "frontend/routes.js"},
        }
        zf.writestr(
            "zip-mod/manifest.json",
            json.dumps(manifest, ensure_ascii=False),
        )
        zf.writestr("zip-mod/readme.md", "x")
    buf.seek(0)
    r = client.post(
        "/api/mods/import",
        files={"file": ("z.zip", buf.getvalue(), "application/zip")},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert (library / "zip-mod" / "manifest.json").is_file()


def test_sync_push_pull(tmp_path, monkeypatch):
    """使用真实目录结构验证 deploy / pull。"""
    import uuid

    library = tmp_path / "lib"
    library.mkdir()
    xcagi = tmp_path / "xcagi"
    (xcagi / "mods").mkdir(parents=True)

    from fastapi.testclient import TestClient

    from modman.repo_config import RepoConfig
    from modstore_server.app import app

    cfg = RepoConfig(library_root=str(library), xcagi_root=str(xcagi))

    monkeypatch.setattr("modstore_server.app.load_config", lambda: cfg)
    monkeypatch.setattr("modstore_server.app.save_config", lambda c: None)
    monkeypatch.setattr("modstore_server.app.project_root", lambda: tmp_path / "ph")

    monkeypatch.setattr("modstore_server.market_api.assert_email_outbound_configured", lambda: None)
    monkeypatch.setattr("modstore_server.market_api.generate_verification_code", lambda: "999999")
    monkeypatch.setattr(
        "modstore_server.market_api.send_verification_email",
        lambda *args, **kwargs: None,
    )

    c = TestClient(app)
    u = f"sync_user_{uuid.uuid4().hex[:10]}"
    em = f"sync_{uuid.uuid4().hex[:8]}@pytest.local"
    r = c.post("/api/auth/send-register-code", json={"email": em})
    assert r.status_code == 202, r.text
    r = c.post(
        "/api/auth/register",
        json={
            "username": u,
            "password": "sync-pass-12",
            "email": em,
            "verification_code": "999999",
        },
    )
    assert r.status_code == 200, r.text
    reg = r.json()
    tok = reg.get("access_token") or reg.get("token")
    assert tok, reg
    h = {"Authorization": f"Bearer {tok}"}

    r = c.post("/api/mods/create", json={"mod_id": "sync-m", "display_name": "S"}, headers=h)
    assert r.status_code == 200

    r = c.post("/api/sync/push", json={"mod_ids": ["sync-m"]}, headers=h)
    assert r.status_code == 200
    assert (xcagi / "mods" / "sync-m" / "manifest.json").is_file()

    shutil.rmtree(library / "sync-m", ignore_errors=True)
    r = c.post("/api/sync/pull", json={"mod_ids": ["sync-m"]}, headers=h)
    assert r.status_code == 200
    assert (library / "sync-m" / "manifest.json").is_file()


@patch("modstore_server.api.debug.httpx.Client")
def test_xcagi_loading_status_mocked(mock_client_cls, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "data": {"mods_loaded": 0}}
    inst = MagicMock()
    inst.__enter__.return_value.get.return_value = mock_resp
    mock_client_cls.return_value = inst

    r = client.get("/api/xcagi/loading-status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["success"] is True


def test_delete_mod(client, auth_headers: dict):
    client.post(
        "/api/mods/create", json={"mod_id": "del-me", "display_name": "D"}, headers=auth_headers
    )
    r = client.delete("/api/mods/del-me", headers=auth_headers)
    assert r.status_code == 200
    r = client.get("/api/mods/del-me", headers=auth_headers)
    # 删除后用户不再拥有该 mod，所有权校验先于「目录是否存在」
    assert r.status_code == 403


def test_admin_reset_user_password_requires_token(client, monkeypatch):
    monkeypatch.setenv("MODSTORE_ADMIN_RECHARGE_TOKEN", "")
    r = client.post(
        "/api/admin/reset-user-password",
        json={"username": "nobody", "new_password": "new-pass-99"},
        headers={"X-Modstore-Recharge-Token": "x"},
    )
    assert r.status_code == 503


def test_admin_reset_user_password_wrong_token(client, monkeypatch):
    monkeypatch.setenv("MODSTORE_ADMIN_RECHARGE_TOKEN", "secret-admin")
    r = client.post(
        "/api/admin/reset-user-password",
        json={"username": "nobody", "new_password": "new-pass-99"},
        headers={"X-Modstore-Recharge-Token": "wrong"},
    )
    assert r.status_code == 403


def test_admin_reset_user_password_then_login(client, monkeypatch):
    import uuid

    monkeypatch.setattr("modstore_server.market_api.assert_email_outbound_configured", lambda: None)
    monkeypatch.setattr("modstore_server.market_api.generate_verification_code", lambda: "999999")
    monkeypatch.setattr(
        "modstore_server.market_api.send_verification_email",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setenv("MODSTORE_ADMIN_RECHARGE_TOKEN", "secret-admin")

    username = f"rst_{uuid.uuid4().hex[:12]}"
    email = f"rst{uuid.uuid4().hex[:8]}@pytest.local"
    assert client.post("/api/auth/send-register-code", json={"email": email}).status_code == 202
    reg = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "old-pass-12",
            "email": email,
            "verification_code": "999999",
        },
    )
    assert reg.status_code == 200, reg.text

    r = client.post(
        "/api/admin/reset-user-password",
        json={"username": username, "new_password": "fresh-pass-34"},
        headers={"X-Modstore-Recharge-Token": "secret-admin"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True

    login = client.post("/api/auth/login", json={"username": username, "password": "fresh-pass-34"})
    assert login.status_code == 200, login.text
    login_old = client.post(
        "/api/auth/login", json={"username": username, "password": "old-pass-12"}
    )
    assert login_old.status_code == 401
