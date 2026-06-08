from __future__ import annotations

import types


def _create_minimal_workflow(client):
    r = client.post(
        "/api/workflow/",
        json={"name": "eligible-wf", "description": "sandbox gate"},
    )
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    r = client.post(
        f"/api/workflow/{wid}/nodes",
        json={
            "node_type": "start",
            "name": "start",
            "config": {},
            "position_x": 0,
            "position_y": 0,
        },
    )
    assert r.status_code == 200, r.text
    start_id = r.json()["id"]
    r = client.post(
        f"/api/workflow/{wid}/nodes",
        json={"node_type": "end", "name": "end", "config": {}, "position_x": 200, "position_y": 0},
    )
    assert r.status_code == 200, r.text
    end_id = r.json()["id"]
    r = client.post(
        f"/api/workflow/{wid}/edges",
        json={"source_node_id": start_id, "target_node_id": end_id, "condition": ""},
    )
    assert r.status_code == 200, r.text
    return wid, start_id


def test_sandbox_success_makes_workflow_employee_eligible_and_graph_changes_stale(client):
    from modstore_server.api.deps import get_current_user
    from modstore_server.app import app

    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=1, username="pytest", is_admin=True, email="t@t.local"
    )
    try:
        wid, start_id = _create_minimal_workflow(client)

        r = client.post(
            f"/api/workflow/{wid}/sandbox-run",
            json={"input_data": {}, "mock_employees": True, "validate_only": False},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["sandbox_passed_for_current_graph"] is True

        r = client.get("/api/workflow/employee-eligible")
        assert r.status_code == 200, r.text
        assert wid in [row["id"] for row in r.json()["workflows"]]

        r = client.put(
            f"/api/workflow/nodes/{start_id}",
            json={"name": "start changed", "config": {}, "position_x": 0, "position_y": 0},
        )
        assert r.status_code == 200, r.text

        r = client.get("/api/workflow/employee-eligible")
        assert r.status_code == 200, r.text
        body = r.json()
        assert wid not in [row["id"] for row in body["workflows"]]
        stale = next(row for row in body["all_workflows"] if row["id"] == wid)
        assert stale["sandbox_status"]["status"] == "stale"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_employee_v2_config_requires_current_graph_sandbox_pass(client):
    from modstore_server.api.deps import get_current_user
    from modstore_server.app import app

    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=2, username="pytest2", is_admin=True, email="t2@t.local"
    )
    try:
        wid, start_id = _create_minimal_workflow(client)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    cfg = {
        "identity": {"id": "emp-a", "name": "Emp A", "version": "1.0.0"},
        "collaboration": {"workflow": {"workflow_id": wid}},
    }

    from modstore_server.employee_config_v2 import validate_v2_config
    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    with sf() as db:
        errs = validate_v2_config(
            cfg,
            db=db,
            user_id=None,
            require_workflow_heart=True,
            require_workflow_sandbox=True,
        )
    assert any("尚未通过沙箱测试" in e for e in errs)

    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=2, username="pytest2", is_admin=True, email="t2@t.local"
    )
    try:
        r = client.post(
            f"/api/workflow/{wid}/sandbox-run",
            json={"input_data": {}, "mock_employees": True, "validate_only": False},
        )
        assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    with sf() as db:
        assert (
            validate_v2_config(
                cfg,
                db=db,
                user_id=None,
                require_workflow_heart=True,
                require_workflow_sandbox=True,
            )
            == []
        )

    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=2, username="pytest2", is_admin=True, email="t2@t.local"
    )
    try:
        r = client.put(
            f"/api/workflow/nodes/{start_id}",
            json={"name": "start changed", "config": {}, "position_x": 0, "position_y": 0},
        )
        assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    with sf() as db:
        errs = validate_v2_config(
            cfg,
            db=db,
            user_id=None,
            require_workflow_heart=True,
            require_workflow_sandbox=True,
        )
    assert any("已变更" in e for e in errs)
