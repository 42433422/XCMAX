"""Mod 员工从名片到可执行包的可用性诊断。"""

from __future__ import annotations

import json
import types

import pytest

from modman.scaffold import create_mod

pytest.importorskip("fastapi")


@pytest.fixture
def admin_client(client):
    from modstore_server.app import _require_user, app

    u = types.SimpleNamespace(id=1, username="pytest", is_admin=True, email="t@t.local")
    app.dependency_overrides[_require_user] = lambda: u
    yield client
    app.dependency_overrides.pop(_require_user, None)


def _reset_db(monkeypatch, tmp_path):
    from modstore_server import models

    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "modstore.db"))
    models._engine = None
    models._SessionFactory = None
    models.init_db()
    return models.get_session_factory()


def _write_workflow_employee(library, mod_id: str, row: dict) -> None:
    manifest_path = library / mod_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["description"] = "Readiness test mod"
    manifest["workflow_employees"] = [row]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def test_mod_employee_readiness_flags_shell_employee(monkeypatch, tmp_path, admin_client, library):
    _reset_db(monkeypatch, tmp_path)
    create_mod("shell-mod", "Shell Mod", library)
    _write_workflow_employee(
        library,
        "shell-mod",
        {
            "id": "contract-review",
            "label": "合同预审",
            "panel_summary": "只声明了员工名片，还没有可执行包和工作流绑定。",
        },
    )

    res = admin_client.get("/api/mods/shell-mod/authoring-summary")
    assert res.status_code == 200, res.text
    readiness = res.json()["employee_readiness"]
    assert readiness["ok"] is False
    assert readiness["summary"] == {"total": 1, "ready": 0, "blocked": 1}
    gaps = "\n".join(readiness["gaps"])
    assert "未登记可执行员工包" in gaps
    assert "未写入 workflow_id" in gaps


def test_mod_employee_readiness_requires_pack_id_match(
    monkeypatch, tmp_path, admin_client, library
):
    sf = _reset_db(monkeypatch, tmp_path)
    create_mod("ready-mod", "Ready Mod", library)

    from modstore_server.models import CatalogItem, Workflow, WorkflowNode

    with sf() as db:
        wf = Workflow(user_id=1, name="员工工作流", description="", is_active=True)
        db.add(wf)
        db.flush()
        db.add(
            WorkflowNode(
                workflow_id=wf.id,
                node_type="employee",
                name="执行员工",
                config=json.dumps(
                    {"employee_id": "worker", "task": "处理任务"}, ensure_ascii=False
                ),
            )
        )
        db.add(
            CatalogItem(
                pkg_id="ready-mod-worker",
                version="1.0.0",
                name="Worker",
                artifact="employee_pack",
                author_id=1,
            )
        )
        db.commit()
        workflow_id = wf.id

    _write_workflow_employee(
        library,
        "ready-mod",
        {
            "id": "worker",
            "label": "Worker",
            "workflow_id": workflow_id,
            "panel_summary": "已登记员工包，但工作流节点先故意填错 employee_id。",
        },
    )

    res = admin_client.get("/api/mods/ready-mod/authoring-summary")
    assert res.status_code == 200, res.text
    row = res.json()["employee_readiness"]["employees"][0]
    assert row["catalog_registered"] is True
    assert row["ready"] is False
    assert "工作流 employee 节点未使用可执行包 id" in row["gaps"][0]

    with sf() as db:
        node = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).first()
        node.config = json.dumps(
            {"employee_id": "ready-mod-worker", "task": "处理任务"}, ensure_ascii=False
        )
        db.commit()

    res = admin_client.get("/api/mods/ready-mod/authoring-summary")
    assert res.status_code == 200, res.text
    readiness = res.json()["employee_readiness"]
    assert readiness["ok"] is True
    assert readiness["summary"]["ready"] == 1
    assert readiness["employees"][0]["ready"] is True


def test_register_workflow_employee_catalog_writes_runtime_catalog(
    monkeypatch, tmp_path, admin_client, library
):
    sf = _reset_db(monkeypatch, tmp_path)
    cat = tmp_path / "catalog"
    cat.mkdir()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(cat))
    from modstore_server.catalog_store import save_store

    save_store({"packages": []})

    async def fake_audit(*args, **kwargs):
        return {"ok": True, "summary": {"pass": True}, "dimensions": {}, "functional_tests": []}

    monkeypatch.setattr("modstore_server.routes_registry.run_package_audit_async", fake_audit)

    create_mod("reg-ready", "Reg Ready", library)
    _write_workflow_employee(
        library,
        "reg-ready",
        {
            "id": "agent",
            "label": "Agent",
            "panel_summary": "用于确认一键登记会同步写入运行时 CatalogItem。",
        },
    )

    res = admin_client.post(
        "/api/mods/reg-ready/register-workflow-employee-catalog",
        json={"workflow_index": 0},
    )
    assert res.status_code == 200, res.text
    pkg_id = res.json()["package"]["id"]
    assert pkg_id == "reg-ready-agent"

    from modstore_server.models import CatalogItem

    with sf() as db:
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).first()
        assert row is not None
        assert row.artifact == "employee_pack"
