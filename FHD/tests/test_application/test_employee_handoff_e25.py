"""E25 employee handoff uses the registered handoff and a real child run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.employee_runtime.executor import execute_employee_task_local
from app.application.employee_runtime.task_continuity import (
    TaskContinuityRuntime,
    ledger_path,
    load_employee_task_ledger,
)
from app.application.tools.workflow import execute_workflow_tool
from app.db.models.customer import Customer
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.task_lifecycle import TaskLifecycleRecord

CUSTOMER = "交接客户甲"


def test_handoff_identity_projects_only_ids_and_keeps_scope_checks():
    from app.application.employee_runtime.handoff_commit import _handoff_identity_ids

    expected = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "employee_id": "employee-a",
        "task_id": "task-a",
    }
    context = {
        **expected,
        "password": "test-password",
        "token": "test-token",
        "cookie": "test-cookie",
    }
    identity_ids, rejection = _handoff_identity_ids({}, context)
    assert rejection is None
    assert identity_ids == expected
    assert context["token"] == "test-token"
    for key in ("tenant_id", "user_id", "task_id", "source"):
        identity_ids, rejection = _handoff_identity_ids({key: "another-identity"}, context)
        assert identity_ids is None
        assert rejection["error_code"] == "handoff_unauthorized"


@pytest.fixture()
def customers_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'business.sqlite'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PurchaseUnit.__table__.create(engine)
    TaskLifecycleRecord.__table__.create(engine)
    Customer.__table__.create(engine)
    SalesOrder.__table__.create(engine)
    SalesOrderItem.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", lambda: factory()
    )
    monkeypatch.setattr(
        "app.application.employee_runtime.handoff_commit.get_agent_run_repository",
        lambda: SQLAlchemyAgentRunRepository(session_factory=factory),
    )
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("SECRET_KEY", "employee-handoff-test-secret-32bytes")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    session = factory()
    session.add(PurchaseUnit(id=42, unit_name=CUSTOMER, tenant_id=11, is_active=True))
    session.commit()
    session.close()
    return engine


@pytest.fixture
def signed_handoff_actor(customers_db, monkeypatch):
    from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
    from tests.fixtures.employee_test_identity import seed_employee_identity

    factory = seed_employee_identity(
        customers_db, session_id="handoff-session", username="handoff-actor"
    )
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setenv("DATABASE_URL", str(customers_db.url))
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    binding = bind_agent_actor_scope(session_id="handoff-session", user_id="11")
    return {"tenant_id": "11", "user_id": "11", "actor_id": "11", "_actor_authorization": binding}


def _card(
    workspace: Path,
    employee: str,
    *,
    available: bool = True,
    tenant_id: str = "11",
    identity: bool = True,
) -> None:
    folder = workspace / "employees"
    folder.mkdir(parents=True, exist_ok=True)
    body: dict = {"available": available}
    if identity:
        body["employee_id"] = employee
        body["tenant_id"] = tenant_id
    (folder / f"{employee}.json").write_text(json.dumps(body), encoding="utf-8")


def _start(workspace: Path) -> dict:
    return execute_employee_task_local(
        "employee-a",
        "查询客户",
        {
            "continuity_action": "start",
            "workspace_root": str(workspace),
            "tenant_id": "11",
            "user_id": "11",
            "goal": "查询客户并交接",
            "steps": [{"tool": "list_customers", "params": {}}],
        },
        workspace_root=str(workspace),
    )


def _handoff(workspace: Path, task_id: str, *, runtime_context=None, **extra) -> dict:
    payload = {
        "continuity_action": "handoff",
        "workspace_root": str(workspace),
        "tenant_id": "11",
        "user_id": "11",
        "task_id": task_id,
        "target_employee": "employee-b",
        "permissions": ["customers.query", "sales.query"],
        "delegated_tool": "customers",
        "delegated_action": "query",
        "delegated_params": {
            "keyword": CUSTOMER,
            "customer_id": 42,
            "date_from": "2026-11-01",
            "date_to": "2026-11-30",
        },
        "effect": {"keyword": CUSTOMER},
    }
    payload.update(extra)
    return execute_employee_task_local(
        "employee-a",
        "交给员工乙",
        payload,
        user_id=11,
        workspace_root=str(workspace),
        runtime_context=runtime_context,
    )


def _children(workspace: Path, parent_id: str) -> list[dict]:
    state = load_employee_task_ledger(workspace)
    return [task for task in state["tasks"].values() if task.get("parent_task_id") == parent_id]


def test_employee_a_hands_off_to_employee_b(
    customers_db, tmp_path: Path, signed_handoff_actor
) -> None:
    workspace = tmp_path / "handoff"
    workspace.mkdir()
    _card(workspace, "employee-a")
    _card(workspace, "employee-b")
    started = _start(workspace)
    parent_id = str(started["task_id"])
    handed = _handoff(workspace, parent_id, runtime_context=signed_handoff_actor)
    handoff = handed["handoff"]
    assert handoff["status"] == "succeeded", (
        handoff.get("error_code"),
        handoff.get("error_message"),
    )
    payload = handoff["result_payload"]
    child_id = str(payload["child_task_id"])
    assert handoff["status"] == "succeeded"
    assert handoff["target_employee"] == "employee-b"
    assert handoff["goal"]
    assert payload["parent_task_id"] == parent_id
    assert child_id and child_id != parent_id
    assert payload["execution_status"] == "completed"
    assert payload["result"]["tool_id"] == "customers"
    assert payload["result"]["action"] == "query"
    assert payload["result"]["params"]["customer_id"] == 42
    assert payload["result"]["params"]["date_from"] == "2026-11-01"
    assert payload["result"]["params"]["date_to"] == "2026-11-30"
    assert CUSTOMER in json.dumps(payload["result"], ensure_ascii=False)
    assert child_id in handed["task"]["child_task_ids"]
    assert handed["business_success"] is False
    assert handed["task"]["status"] != "completed"
    state = load_employee_task_ledger(workspace)
    child = state["tasks"][child_id]
    stored = state["handoffs"][handoff["handoff_id"]]
    assert child["parent_task_id"] == parent_id
    assert child["owner_employee"] == "employee-b"
    assert child["result_payload"]["parent_task_id"] == parent_id
    assert child["result_payload"]["child_task_id"] == child_id
    assert stored["status"] == "completed"
    assert stored["result_payload"]["result"]["parent_task_id"] == parent_id
    assert "customers.query" in payload["delegated_tools"]
    assert "sales.query" in payload["delegated_tools"]


def test_unknown_target_employee_is_rejected(customers_db, tmp_path: Path) -> None:
    workspace = tmp_path / "unknown"
    workspace.mkdir()
    _card(workspace, "employee-a")
    started = _start(workspace)
    handed = _handoff(workspace, started["task_id"])
    assert handed["handoff"]["status"] == "failed"
    assert handed["handoff"]["error_code"] == "handoff_unknown_employee"
    assert handed["business_success"] is False
    assert handed["task"]["status"] == "failed"
    assert _children(workspace, started["task_id"]) == []


def test_unauthorized_handoff_is_rejected(customers_db, tmp_path: Path) -> None:
    workspace = tmp_path / "denied"
    workspace.mkdir()
    _card(workspace, "employee-a")
    _card(workspace, "employee-b")
    started = _start(workspace)
    handed = _handoff(
        workspace,
        started["task_id"],
        permissions=["not_a_tool.query"],
        delegated_tool="not_a_tool",
        delegated_action="query",
    )
    assert handed["handoff"]["error_code"] == "tool_contract_unavailable"
    assert handed["business_success"] is False
    assert handed["task"]["status"] == "failed"
    assert _children(workspace, started["task_id"]) == []
    state = load_employee_task_ledger(workspace)
    state["tasks"][started["task_id"]]["grants"]["employee-a"] = ["sales.query"]
    ledger_path(workspace).write_text(json.dumps(state), encoding="utf-8")
    raw = json.loads(
        execute_workflow_tool(
            "handoff_commit",
            {
                "tenant_id": "11",
                "user_id": "11",
                "task_id": started["task_id"],
                "source": "employee-a",
                "target": "employee-b",
                "permissions": ["customers.query"],
                "parent_grant": ["*"],
                "delegated_tool": "customers",
                "delegated_action": "query",
                "delegated_params": {},
                "goal": "越权交接",
            },
            str(workspace),
            runtime_context={
                "tenant_id": "11",
                "user_id": "11",
                "employee_id": "employee-a",
                "task_id": started["task_id"],
            },
        )
    )
    assert raw["success"] is False
    assert raw["error_code"] == "handoff_unauthorized"
    assert not raw.get("child_task_id")


def test_cross_tenant_handoff_is_blocked(customers_db, tmp_path: Path) -> None:
    workspace = tmp_path / "tenant"
    workspace.mkdir()
    _card(workspace, "employee-a")
    _card(workspace, "employee-b", tenant_id="22")
    started = _start(workspace)
    handed = _handoff(workspace, started["task_id"], target_tenant_id="11")
    assert handed["handoff"]["error_code"] == "handoff_cross_tenant"
    assert handed["business_success"] is False
    assert handed["task"]["status"] == "failed"
    assert _children(workspace, started["task_id"]) == []


def test_missing_handoff_context_is_rejected(tmp_path: Path) -> None:
    raw = json.loads(
        execute_workflow_tool(
            "handoff_commit",
            {"goal": "缺少上下文", "source": "employee-a", "target": "employee-b"},
            str(tmp_path),
        )
    )
    assert raw["success"] is False
    assert raw["error_code"] == "handoff_context_missing"
    assert not raw.get("child_task_id")


def test_repeated_handoff_does_not_create_a_second_child(
    customers_db, tmp_path: Path, signed_handoff_actor
) -> None:
    workspace = tmp_path / "repeat"
    workspace.mkdir()
    _card(workspace, "employee-a")
    _card(workspace, "employee-b")
    started = _start(workspace)
    parent_id = started["task_id"]
    first = _handoff(workspace, parent_id, runtime_context=signed_handoff_actor)
    second = _handoff(workspace, parent_id, runtime_context=signed_handoff_actor)
    child_id = first["handoff"]["result_payload"]["child_task_id"]
    assert second["handoff"]["duplicate_prevented"] is True
    assert second["handoff"]["result_payload"]["child_task_id"] == child_id
    assert len(_children(workspace, parent_id)) == 1


def test_handoff_record_survives_process_reentry(
    customers_db, tmp_path: Path, signed_handoff_actor
) -> None:
    workspace = tmp_path / "restart"
    workspace.mkdir()
    _card(workspace, "employee-a")
    _card(workspace, "employee-b")
    started = _start(workspace)
    parent_id = started["task_id"]
    handed = _handoff(workspace, parent_id, runtime_context=signed_handoff_actor)
    child_id = handed["handoff"]["result_payload"]["child_task_id"]
    reloaded = TaskContinuityRuntime(ledger_path(workspace), workspace=workspace)
    reloaded._read()
    assert reloaded.state["tasks"][child_id]["parent_task_id"] == parent_id
    script = """
import json, sys
from pathlib import Path
from app.application.employee_runtime.task_continuity import TaskContinuityRuntime, ledger_path
workspace = Path(sys.argv[1])
parent_id = sys.argv[2]
runtime = TaskContinuityRuntime(ledger_path(workspace), workspace=workspace)
runtime._read()
parent = runtime.state["tasks"][parent_id]
child_id = parent["child_task_ids"][0]
child = runtime.state["tasks"][child_id]
handoff = runtime.state["handoffs"][parent["handoff_ids"][-1]]
print(json.dumps({
    "parent_task_id": parent["task_id"],
    "child_task_id": child["task_id"],
    "link": child["parent_task_id"],
    "handoff_status": handoff["status"],
    "result_parent": handoff["result_payload"]["parent_task_id"],
    "result_child": handoff["result_payload"]["child_task_id"],
    "execution_status": handoff["result_payload"]["execution_status"],
    "saw_customer": "交接客户甲" in json.dumps(handoff["result_payload"], ensure_ascii=False),
}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    completed = subprocess.run(
        [sys.executable, "-c", script, str(workspace), parent_id],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    found = json.loads(completed.stdout)
    assert found["parent_task_id"] == parent_id
    assert found["child_task_id"] == child_id
    assert found["link"] == parent_id
    assert found["result_parent"] == parent_id
    assert found["result_child"] == child_id
    assert found["handoff_status"] == "completed"
    assert found["execution_status"] == "completed"
    assert found["saw_customer"] is True


def test_empty_roster_and_unverifiable_employee_are_rejected(customers_db, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    started = _start(empty)
    handed = _handoff(empty, started["task_id"])
    assert handed["handoff"]["error_code"] == "handoff_identity_unverified"
    assert handed["business_success"] is False
    assert handed["task"]["status"] == "failed"
    assert _children(empty, started["task_id"]) == []

    unavailable = tmp_path / "unavailable"
    unavailable.mkdir()
    _card(unavailable, "employee-a")
    _card(unavailable, "employee-b", available=False)
    started = _start(unavailable)
    handed = _handoff(unavailable, started["task_id"])
    assert handed["handoff"]["status"] == "failed"
    assert handed["handoff"]["error_code"] in {"employee_unavailable", "handoff_unknown_employee"}
    assert handed["business_success"] is False
    assert handed["task"]["status"] == "failed"

    unverified = tmp_path / "unverified"
    unverified.mkdir()
    _card(unverified, "employee-a")
    _card(unverified, "employee-b", identity=False)
    started = _start(unverified)
    handed = _handoff(unverified, started["task_id"])
    assert handed["handoff"]["error_code"] == "handoff_identity_unverified"
    assert handed["business_success"] is False
    assert handed["task"]["status"] == "failed"
    assert _children(unverified, started["task_id"]) == []


def _direct(workspace: Path, task_id: str, **extra) -> dict:
    args = {
        "tenant_id": "11",
        "user_id": "11",
        "task_id": task_id,
        "source": "employee-a",
        "target": "employee-b",
        "permissions": ["customers.query"],
        "delegated_tool": "customers",
        "delegated_action": "query",
        "delegated_params": {"keyword": CUSTOMER, "customer_id": 42},
        "parent_grant": ["*"],
        "target_tenant_id": "11",
    }
    args.update(extra)
    context = {
        "tenant_id": "11",
        "user_id": "11",
        "employee_id": str(extra.get("source") or "employee-a"),
        "task_id": task_id,
    }
    if "context_task_id" in extra:
        context["task_id"] = str(extra["context_task_id"])
    if "context_employee_id" in extra:
        context["employee_id"] = str(extra["context_employee_id"])
    if "context_tenant_id" in extra:
        context["tenant_id"] = str(extra["context_tenant_id"])
    return json.loads(
        execute_workflow_tool("handoff_commit", args, str(workspace), runtime_context=context)
    )


def test_forged_handoff_identity_is_rejected(customers_db, tmp_path: Path) -> None:
    workspace = tmp_path / "forged"
    workspace.mkdir()
    _card(workspace, "employee-a")
    _card(workspace, "employee-b")
    first = _start(workspace)
    second = _start(workspace)
    forged_task = _direct(workspace, second["task_id"], context_task_id=first["task_id"])
    assert forged_task["success"] is False
    assert forged_task["error_code"] == "handoff_unauthorized"
    assert _children(workspace, first["task_id"]) == []
    assert _children(workspace, second["task_id"]) == []

    forged_employee = _direct(
        workspace, first["task_id"], source="employee-b", context_employee_id="employee-b"
    )
    assert forged_employee["success"] is False
    assert forged_employee["error_code"] == "handoff_unauthorized"
    assert not forged_employee.get("child_task_id")

    forged_tenant = _direct(workspace, first["task_id"], tenant_id="22", target_tenant_id="22")
    assert forged_tenant["success"] is False
    assert forged_tenant["error_code"] == "handoff_unauthorized"
    assert _children(workspace, first["task_id"]) == []


def test_permission_order_does_not_change_the_delegated_call(
    customers_db, tmp_path: Path, signed_handoff_actor
) -> None:
    params = {
        "keyword": CUSTOMER,
        "customer_id": 42,
        "date_from": "2026-11-01",
        "date_to": "2026-11-30",
    }
    executed = []
    for name, permissions in (
        ("forward", ["customers.query", "sales.query"]),
        ("reverse", ["sales.query", "customers.query"]),
    ):
        workspace = tmp_path / name
        workspace.mkdir()
        _card(workspace, "employee-a")
        _card(workspace, "employee-b")
        started = _start(workspace)
        handed = _handoff(
            workspace,
            started["task_id"],
            runtime_context=signed_handoff_actor,
            permissions=permissions,
            delegated_params=params,
        )
        payload = handed["handoff"]["result_payload"]["result"]
        assert payload["parent_task_id"] == started["task_id"]
        assert CUSTOMER in json.dumps(payload["final_output"], ensure_ascii=False)
        executed.append((payload["tool_id"], payload["action"], payload["params"]))
    assert executed[0] == executed[1] == ("customers", "query", params)
