"""market_api：编制在岗员工包删除保护。"""

from __future__ import annotations

import types


def test_admin_delete_employee_pack_forbidden_for_duty_roster_id(client):
    from modstore_server import market_auth_api as ma
    from modstore_server.app import app

    admin = types.SimpleNamespace(id=1, username="a", is_admin=True, email="a@a")
    app.dependency_overrides[ma._require_admin] = lambda: admin
    try:
        r = client.delete("/api/admin/employee-packs/flask-entry-keeper")
        assert r.status_code == 403, r.text
        assert "编制" in r.text
    finally:
        app.dependency_overrides.pop(ma._require_admin, None)


def test_admin_delete_employee_pack_not_duty_forbidden_for_random_id(client, monkeypatch):
    """非编制 id：不得触发 duty 403。"""
    from modstore_server import catalog_store
    from modstore_server import market_auth_api as ma
    from modstore_server.app import app

    admin = types.SimpleNamespace(id=1, username="a", is_admin=True, email="a@a")
    app.dependency_overrides[ma._require_admin] = lambda: admin
    pid = "pytest-orphan-pack-not-in-duty-roster-xyz"
    try:
        monkeypatch.setattr(catalog_store, "remove_package", lambda _p, version=None: 0)
        r = client.delete(f"/api/admin/employee-packs/{pid}")
        assert r.status_code != 403, r.text
    finally:
        app.dependency_overrides.pop(ma._require_admin, None)
