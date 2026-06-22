"""管理员在岗图执行 API：能力摘要与依赖图运行。"""

from __future__ import annotations

import types

from fastapi.testclient import TestClient

from modstore_server.api.app_factory import create_app, load_default_config
from modstore_server.api.deps import get_current_user


def _new_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "admin_duty_graph.sqlite"))
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()

    app = create_app(load_default_config())
    client = TestClient(app)
    return app, client


def test_admin_duty_graph_requires_admin(tmp_path, monkeypatch):
    app, client = _new_client(tmp_path, monkeypatch)
    user = types.SimpleNamespace(id=1, username="u", is_admin=False, email="u@u")
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        r = client.post("/api/admin/employees/execution-capabilities", json={})
        assert r.status_code == 403
        r = client.post(
            "/api/admin/duty-graph/runs",
            json={"target_employee_id": "x", "task": "t"},
        )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_admin_duty_graph_capability_and_run(tmp_path, monkeypatch):
    app, client = _new_client(tmp_path, monkeypatch)

    import modstore_server.admin_duty_graph_api as duty_api

    rows = [
        {"id": "dep-a", "name": "依赖A", "source": "catalog"},
        {"id": "target", "name": "目标员工", "source": "catalog"},
    ]
    monkeypatch.setattr(duty_api, "list_employees_exec", lambda: rows)

    def _fake_pack(_session, employee_id: str):
        if employee_id == "dep-a":
            return {
                "manifest": {
                    "employee_config_v2": {
                        "actions": {"handlers": ["echo"]},
                        "collaboration": {"depends_on": []},
                        "cognition": {
                            "agent": {"model": {"provider": "auto", "model_name": "auto"}}
                        },
                    }
                }
            }
        if employee_id == "target":
            return {
                "manifest": {
                    "employee_config_v2": {
                        "actions": {
                            "handlers": ["shell_exec"],
                            "shell_exec": {"command_id": "nginx-syntax-check"},
                        },
                        "collaboration": {"depends_on": ["dep-a"]},
                        "cognition": {
                            "agent": {"model": {"provider": "auto", "model_name": "auto"}}
                        },
                    }
                }
            }
        raise ValueError("not found")

    monkeypatch.setattr(duty_api, "load_employee_pack", _fake_pack)
    monkeypatch.setattr(duty_api, "employee_pack_runtime_issues", lambda _pack: [])
    monkeypatch.setattr(
        duty_api,
        "credential_status",
        lambda _session, _uid, provider: {
            "provider": provider,
            "has_platform_key": True,
            "has_user_override": False,
        },
    )
    monkeypatch.setattr(duty_api, "fernet_configured", lambda: True)

    class _FakeRuntime:
        def __init__(self):
            self.calls: list[str] = []

        def execute_task(
            self, *, employee_id, task, input_data=None, user_id=None, bench_llm_override=None
        ):
            _ = task, input_data, user_id, bench_llm_override
            self.calls.append(employee_id)
            return {"duration_ms": 12.3, "llm_tokens": 8, "result": {"employee_id": employee_id}}

    fake_runtime = _FakeRuntime()
    monkeypatch.setattr(duty_api, "get_default_employee_client", lambda: fake_runtime)

    admin = types.SimpleNamespace(id=99, username="admin", is_admin=True, email="a@a")
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        cap = client.get("/api/admin/employees/target/execution-capability")
        assert cap.status_code == 200, cap.text
        cap_body = cap.json()
        assert cap_body["employee_id"] == "target"
        assert cap_body["risk"]["high_risk"] is True
        assert cap_body["risk"]["requires_confirmation"] is True
        assert cap_body["declared_dependencies"] == ["dep-a"]

        run1 = client.post(
            "/api/admin/duty-graph/runs",
            json={
                "target_employee_id": "target",
                "task": "执行一次",
                "include_dependencies": True,
                "allow_high_risk_real_run": False,
            },
        )
        assert run1.status_code == 200, run1.text
        b1 = run1.json()
        assert b1["status"] == "completed"
        node_map1 = {n["employee_id"]: n for n in b1["nodes"]}
        assert node_map1["dep-a"]["status"] == "success"
        assert node_map1["target"]["status"] == "skipped"
        assert "高风险动作未确认" in node_map1["target"]["error"]
        assert fake_runtime.calls == ["dep-a"]

        run2 = client.post(
            "/api/admin/duty-graph/runs",
            json={
                "target_employee_id": "target",
                "task": "执行二次",
                "include_dependencies": True,
                "allow_high_risk_real_run": True,
            },
        )
        assert run2.status_code == 200, run2.text
        b2 = run2.json()
        node_map2 = {n["employee_id"]: n for n in b2["nodes"]}
        assert node_map2["dep-a"]["status"] == "success"
        assert node_map2["target"]["status"] == "success"
        assert fake_runtime.calls == ["dep-a", "dep-a", "target"]

        rid = b2["id"]
        rd = client.get(f"/api/admin/duty-graph/runs/{rid}")
        assert rd.status_code == 200
        assert rd.json()["id"] == rid
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_admin_duty_graph_cycle_detected(tmp_path, monkeypatch):
    app, client = _new_client(tmp_path, monkeypatch)
    import modstore_server.admin_duty_graph_api as duty_api

    rows = [
        {"id": "a", "name": "A", "source": "catalog"},
        {"id": "b", "name": "B", "source": "catalog"},
    ]
    monkeypatch.setattr(duty_api, "list_employees_exec", lambda: rows)

    def _fake_pack(_session, employee_id: str):
        deps = ["b"] if employee_id == "a" else ["a"]
        return {
            "manifest": {
                "employee_config_v2": {
                    "actions": {"handlers": ["echo"]},
                    "collaboration": {"depends_on": deps},
                    "cognition": {"agent": {"model": {"provider": "auto", "model_name": "auto"}}},
                }
            }
        }

    monkeypatch.setattr(duty_api, "load_employee_pack", _fake_pack)
    monkeypatch.setattr(
        duty_api,
        "credential_status",
        lambda _session, _uid, provider: {
            "provider": provider,
            "has_platform_key": True,
            "has_user_override": False,
        },
    )
    monkeypatch.setattr(duty_api, "fernet_configured", lambda: True)

    admin = types.SimpleNamespace(id=7, username="admin", is_admin=True, email="a@a")
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        r = client.post(
            "/api/admin/duty-graph/runs",
            json={
                "target_employee_id": "a",
                "task": "cycle",
                "include_dependencies": True,
            },
        )
        assert r.status_code == 400
        assert "循环" in r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
