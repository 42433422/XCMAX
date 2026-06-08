# -*- coding: utf-8 -*-
"""manifest 快照 REST 与员工闭环 API 冒烟测试。"""

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


def test_snapshot_list_capture_restore(admin_client, library):
    create_mod("snap-mod", "Snap Mod", library)
    mid = "snap-mod"
    mod_dir = library / mid

    r0 = admin_client.get(f"/api/mods/{mid}/snapshots")
    assert r0.status_code == 200
    assert r0.json().get("ok") is True
    assert r0.json().get("snapshots") == []

    r1 = admin_client.post(f"/api/mods/{mid}/snapshots", json={"label": "test snap"})
    assert r1.status_code == 200
    snap_id = r1.json().get("snapshot", {}).get("snap_id")
    assert snap_id

    r2 = admin_client.get(f"/api/mods/{mid}/snapshots")
    assert len(r2.json().get("snapshots") or []) == 1

    man_path = mod_dir / "manifest.json"
    data = json.loads(man_path.read_text(encoding="utf-8"))
    data["version"] = "9.9.9"
    man_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    r3 = admin_client.post(f"/api/mods/{mid}/snapshots/{snap_id}/restore", json={})
    assert r3.status_code == 200
    restored = json.loads(man_path.read_text(encoding="utf-8"))
    assert restored.get("version") == "1.0.0"


def test_bump_patch_version(admin_client, library):
    create_mod("snap-bump", "Bump", library)
    mid = "snap-bump"
    r = admin_client.post(f"/api/mods/{mid}/manifest/bump-patch-version", json={})
    assert r.status_code == 200
    man = json.loads((library / mid / "manifest.json").read_text(encoding="utf-8"))
    assert man.get("version") == "1.0.1"


def test_workflow_employee_closure_empty_employees(admin_client, library):
    create_mod("snap-closure", "Closure", library)
    mid = "snap-closure"
    r = admin_client.post(
        f"/api/mods/{mid}/workflow-employee-closure",
        json={"register_missing": True, "patch_canvas": True, "industry": "通用"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "readiness_after" in body
