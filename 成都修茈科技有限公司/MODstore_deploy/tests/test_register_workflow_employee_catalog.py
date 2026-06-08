"""POST /api/mods/{id}/register-workflow-employee-catalog 一键登记本地 Catalog。"""

from __future__ import annotations

import json
import types

import pytest

from modman.scaffold import create_mod

pytest.importorskip("fastapi")


@pytest.fixture
def admin_client(client):
    """已登录管理员，可访问库内任意 Mod（不依赖 /api/auth/register）。"""
    from modstore_server.app import _require_user, app

    u = types.SimpleNamespace(id=1, username="pytest", is_admin=True, email="t@t.local")
    app.dependency_overrides[_require_user] = lambda: u
    yield client
    app.dependency_overrides.pop(_require_user, None)


def test_register_workflow_employee_catalog_audit_fail(
    monkeypatch, tmp_path, admin_client, library
):
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(cat))
    from modstore_server.catalog_store import save_store

    save_store({"packages": []})

    create_mod("wf-audit-fail", "Audit Fail", library)
    manifest = json.loads((library / "wf-audit-fail" / "manifest.json").read_text(encoding="utf-8"))
    manifest["workflow_employees"] = [
        {
            "id": "emp-x",
            "label": "Employee X",
            "panel_title": "X",
            "panel_summary": "Summary with enough characters for metadata checks.",
        }
    ]
    (library / "wf-audit-fail" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    async def fake_audit(*args, **kwargs):
        return {
            "ok": True,
            "summary": {"pass": False, "average": 20.0},
            "dimensions": {},
            "functional_tests": [],
        }

    monkeypatch.setattr("modstore_server.api.authoring.run_package_audit_async", fake_audit)

    r2 = admin_client.post(
        "/api/mods/wf-audit-fail/register-workflow-employee-catalog",
        json={"workflow_index": 0},
    )
    assert r2.status_code == 400, r2.text
    assert "detail" in r2.json()


def test_register_workflow_employee_catalog_ok(monkeypatch, tmp_path, admin_client, library):
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(cat))
    from modstore_server.catalog_store import save_store

    save_store({"packages": []})

    create_mod("wf-reg-ok", "Reg OK", library)
    manifest = json.loads((library / "wf-reg-ok" / "manifest.json").read_text(encoding="utf-8"))
    manifest["description"] = "Mod description long enough for any cross-check."
    manifest["workflow_employees"] = [
        {
            "id": "emp-catalog",
            "label": "Catalog Employee",
            "panel_title": "CE",
            "panel_summary": "Workflow employee summary with sufficient length for sandbox metadata.",
        }
    ]
    (library / "wf-reg-ok" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    r2 = admin_client.post(
        "/api/mods/wf-reg-ok/register-workflow-employee-catalog",
        json={"workflow_index": 0, "industry": "通用", "price": 0, "release_channel": "stable"},
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data.get("ok") is True
    assert data.get("package", {}).get("id")
    assert data.get("package", {}).get("version")

    idx = admin_client.get("/v1/packages?limit=20").json()
    ids = [p.get("id") for p in idx.get("packages") or []]
    assert data["package"]["id"] in ids
