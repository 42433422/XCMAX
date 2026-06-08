"""管理员员工执行指标 API：分页与权限。"""

from __future__ import annotations

import types

from fastapi.testclient import TestClient

from modstore_server.api.app_factory import create_app, load_default_config
from modstore_server.api.deps import get_current_user


def test_execution_metrics_requires_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "adm_exec.sqlite"))
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    app = create_app(load_default_config())
    client = TestClient(app)

    user = types.SimpleNamespace(id=1, username="u", is_admin=False, email="u@u")
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        r = client.get("/api/admin/employees/pack-a/execution-metrics")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_execution_metrics_empty_and_ordered(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "adm_exec2.sqlite"))
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    from modstore_server.models import EmployeeExecutionMetric, User

    sf = models.get_session_factory()
    with sf() as session:
        u = User(username="actor", email="a@a.a", password_hash="x", is_admin=False)
        session.add(u)
        session.commit()
        uid = u.id
        session.add_all(
            [
                EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id="pack-z",
                    task="older",
                    status="success",
                    duration_ms=200.0,
                    llm_tokens=10,
                ),
                EmployeeExecutionMetric(
                    user_id=uid,
                    employee_id="pack-z",
                    task="newer",
                    status="failed",
                    duration_ms=50.0,
                    llm_tokens=0,
                    error="boom",
                ),
            ]
        )
        session.commit()

    app = create_app(load_default_config())
    client = TestClient(app)

    admin = types.SimpleNamespace(id=99, username="admin", is_admin=True, email="a@a")
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        r = client.get("/api/admin/employees/missing-pack/execution-metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0

        r = client.get("/api/admin/employees/pack-z/execution-metrics?limit=10&offset=0")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        items = body["items"]
        assert len(items) == 2
        # id desc: row inserted last has larger id and appears first
        assert items[0]["task"] == "newer"
        assert items[0]["status"] == "failed"
        assert items[0]["error"] == "boom"
        assert items[1]["task"] == "older"
        assert items[1]["status"] == "success"

        r = client.get(f"/api/admin/employees/pack-z/execution-metrics?user_id={uid}")
        assert r.status_code == 200
        assert r.json()["total"] == 2

        r = client.get("/api/admin/employees/pack-z/execution-metrics?user_id=999999")
        assert r.status_code == 200
        assert r.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
