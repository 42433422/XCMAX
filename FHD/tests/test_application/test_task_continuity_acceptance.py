"""A31–A40 acceptance through the production employee task entry.

Scenarios call ``execute_employee_task_local`` (the function
``CanonicalEmployeeBackend.execute`` uses) and read the workspace ledger
back from disk. They do not bind a runtime, register callables, or assert
evidence that the test itself wrote into the result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.application.employee_runtime.agent import EmployeeAgent
from app.application.employee_runtime.executor import execute_employee_task_local
from app.application.employee_runtime.task_continuity import (
    CONTINUE_TEXT,
    SOURCE,
    audit_employee_task_ledger,
    ledger_path,
    load_employee_task_ledger,
)

_TOOL = """
import json
import sys
from pathlib import Path

req = json.loads(sys.stdin.read() or "{}")
params = req.get("params") or {}
workspace = Path(req["workspace"])
name = Path(sys.argv[0]).stem
flag = workspace / "fail" / name
if params.get("fail") or flag.is_file():
    message = flag.read_text(encoding="utf-8") if flag.is_file() else "工具失败"
    json.dump(
        {
            "ok": False,
            "error_code": params.get("error_code") or "tool_failed",
            "error_message": params.get("error_message") or message,
            "token": params.get("token"),
        },
        sys.stdout,
    )
    raise SystemExit(0)
log = workspace / "effects.jsonl"
record = {"tool": name, "params": params, "task_id": req.get("task_id")}
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, ensure_ascii=False) + "\\n")
json.dump(
    {"ok": True, "tool": name, "task_id": record["task_id"], "params": params, "token": params.get("token")},
    sys.stdout,
    ensure_ascii=False,
)
"""

_KILL = """
import os
import signal
import sys

os.kill(os.getppid(), signal.SIGKILL)
raise SystemExit(0)
"""

_CRASH_DRIVER = """
import json
import sys
from pathlib import Path
from app.application.employee_runtime.executor import execute_employee_task_local

payload = json.loads(sys.argv[1])
result = execute_employee_task_local(
    "clerk",
    "提交未完成工具",
    payload,
    workspace_root=sys.argv[2],
    session_id=payload.get("session_id") or "s",
)
Path(sys.argv[2], "crash_result.json").write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
"""


def _install(workspace: Path, *names: str, kill: tuple[str, ...] = ()) -> None:
    folder = workspace / "tools"
    folder.mkdir(parents=True, exist_ok=True)
    for name in (*names, *kill):
        source = _KILL if name in kill else _TOOL
        (folder / f"{name}.py").write_text(source, encoding="utf-8")


def _effects(workspace: Path, tool: str | None = None) -> list[dict]:
    path = workspace / "effects.jsonl"
    if not path.is_file():
        return []
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if tool is None:
        return rows
    return [row for row in rows if row["tool"] == tool]


def _employee_flags(workspace: Path, employee: str, **flags: bool) -> None:
    folder = workspace / "employees"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{employee}.json").write_text(
        json.dumps({"employee_id": employee, "tenant_id": "t1", **flags}), encoding="utf-8"
    )


def _run(workspace: Path, employee: str, text: str = "", **payload):
    body = {"workspace_root": str(workspace), **payload}
    return execute_employee_task_local(
        employee,
        text,
        body,
        workspace_root=str(workspace),
        session_id=str(body.get("session_id") or ""),
    )


def _ledger(workspace: Path) -> dict:
    return load_employee_task_ledger(workspace)


def _stored(workspace: Path, task_id: str) -> dict:
    task = _ledger(workspace)["tasks"][task_id]
    assert task["task_id"] == task_id
    return task


def _assert_stored_evidence(workspace: Path, task_id: str) -> None:
    events = [item for item in _ledger(workspace)["events"] if item["task_id"] == task_id]
    assert events
    evidence = events[-1]["evidence"]
    assert evidence["E01_task_id"] == task_id
    assert evidence["E15_event_timestamp"]
    assert evidence["E09_execution_status"] == _stored(workspace, task_id)["status"]


def test_ordinary_employee_run_does_not_short_circuit(tmp_path: Path) -> None:
    result = EmployeeAgent("clerk").run(
        "hello", {"invoke_mode": "chat"}, workspace_root=str(tmp_path)
    )
    assert result.get("source") != SOURCE
    assert not ledger_path(tmp_path).is_file()


def scenario_a31(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "pack", "handoff_commit")
    started = _run(
        workspace,
        "clerk",
        "打包并发运",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        session_id="sa",
        goal="打包并发运",
        conversation_id="conv-a31",
        business_data={"sku": "SKU-1", "isolation_marker": "a31"},
        constraints=["不加急"],
        requirements=["先打包"],
        execute_limit=1,
        steps=[
            {"step_id": "s1", "tool": "pack", "params": {"step": "s1"}},
            {"step_id": "s2", "tool": "pack", "params": {"step": "s2"}},
            {"step_id": "s3", "tool": "pack", "params": {"step": "s3"}},
        ],
    )
    task_id = started["task_id"]
    assert _stored(workspace, task_id)["completed_steps"] == ["s1"]
    assert len(_effects(workspace, "pack")) == 1
    paused = _run(
        workspace, "clerk", continuity_action="pause", tenant_id="t1", user_id="ua", task_id=task_id
    )
    assert _stored(workspace, task_id)["status"] == "paused"
    assert paused["task_id"] == task_id
    wrong = _run(
        workspace,
        "clerk",
        "继续",
        continuity_action="resume",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert wrong["success"] is False
    assert len(_effects(workspace, "pack")) == 1
    resumed = _run(
        workspace,
        "clerk",
        CONTINUE_TEXT,
        continuity_action="resume",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert resumed["task_id"] == task_id
    assert len(_effects(workspace, "pack")) == 3
    assert _stored(workspace, task_id)["status"] == "completed"
    added = _run(
        workspace,
        "clerk",
        continuity_action="append_requirements",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        requirements=["补保险"],
        tool="pack",
    )
    assert _stored(workspace, task_id)["status"] == "paused"
    finished = _run(
        workspace,
        "clerk",
        CONTINUE_TEXT,
        continuity_action="resume",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert len(_effects(workspace, "pack")) == 4
    assert _stored(workspace, task_id)["requirements"] == ["先打包", "补保险"]
    assert finished["task_id"] == task_id
    _run(
        workspace, "clerk", continuity_action="leave", tenant_id="t1", user_id="ua", task_id=task_id
    )
    assert _ledger(workspace)["conversations"]["t1:ua:conv-a31"]["active"] is False
    back = _run(
        workspace,
        "clerk",
        continuity_action="reenter",
        tenant_id="t1",
        user_id="ua",
        conversation_id="conv-a31",
    )
    assert back["task_id"] == task_id
    assert _stored(workspace, task_id)["completed_steps"] == ["s1", "s2", "s3", "s4"]
    assert _ledger(workspace)["conversations"]["t1:ua:conv-a31"]["active"] is True
    kinds = [event["kind"] for event in _ledger(workspace)["events"] if event["task_id"] == task_id]
    assert kinds[0] == "task_created"
    assert "task_resumed" in kinds
    _assert_stored_evidence(workspace, task_id)
    return audit_employee_task_ledger(workspace)


def scenario_a32(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "note", "handoff_commit")
    for employee in ("analyst", "executor"):
        _employee_flags(workspace, employee)
    started = _run(
        workspace,
        "analyst",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="按原条件发货",
        conversation_id="conv-a32",
        conditions={"priority": "high", "channel": "sea"},
        constraints=["不得改地址"],
        business_data={"sku": "SKU-9", "qty": 2, "isolation_marker": "a32"},
        execute_limit=1,
        steps=[
            {"step_id": "done", "tool": "note", "params": {"phase": "done"}},
            {"step_id": "left", "tool": "note", "params": {"phase": "left"}},
        ],
    )
    task_id = started["task_id"]
    assert len(_effects(workspace, "note")) == 1
    _run(
        workspace,
        "analyst",
        continuity_action="handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        target_employee="executor",
        permissions=["note"],
        conditions={"priority": "low", "window": "night"},
        idempotency_key="a32-handoff",
    )
    assert len(_effects(workspace, "handoff_commit")) == 1
    viewed = _run(
        workspace,
        "executor",
        continuity_action="read",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    snapshot = _stored(workspace, task_id)["context_snapshot"]
    assert snapshot["goal"] == "按原条件发货"
    assert snapshot["business_data"]["sku"] == "SKU-9"
    assert snapshot["constraints"] == ["不得改地址"]
    assert snapshot["completed_steps"] == ["done"]
    assert "left" in snapshot["remaining_steps"]
    assert snapshot["conditions"]["channel"] == "sea"
    assert snapshot["conditions"]["window"] == "night"
    assert snapshot["conditions"]["priority"]["kept"] == "high"
    assert snapshot["conditions"]["priority"]["added"] == "low"
    handoff = next(iter(_ledger(workspace)["handoffs"].values()))
    assert handoff["source_employee"] == "analyst"
    assert handoff["target_employee"] == "executor"
    assert viewed["evidence"]["E04_source_employee"] == "analyst"
    assert _effects(workspace, "note")[0]["params"]["phase"] == "done"
    return audit_employee_task_ledger(workspace)


def scenario_a33(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "ship")

    def _start(user, tenant, session, marker, color):
        return _run(
            workspace,
            "clerk",
            continuity_action="start",
            tenant=tenant,
            tenant_id=tenant,
            user_id=user,
            session_id=session,
            goal="处理相似订单",
            business_data={"isolation_marker": marker, "color": color},
            steps=[{"step_id": "s1", "tool": "ship", "params": {"color": color, "marker": marker}}],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_start, "ua", "tenant-a", "sa", "marker-a", "red")
        second = pool.submit(_start, "ub", "tenant-a", "sb", "marker-b", "blue")
        task_a = first.result()["task_id"]
        task_b = second.result()["task_id"]
    task_c = _start("ua", "tenant-b", "sc", "marker-c", "green")["task_id"]
    assert len({task_a, task_b, task_c}) == 3
    denied_user = _run(
        workspace,
        "clerk",
        continuity_action="read",
        tenant_id="tenant-a",
        user_id="ub",
        task_id=task_a,
    )
    denied_tenant = _run(
        workspace,
        "clerk",
        continuity_action="read",
        tenant_id="tenant-b",
        user_id="ua",
        task_id=task_a,
    )
    denied_employee = _run(
        workspace,
        "intruder",
        continuity_action="read",
        tenant_id="tenant-a",
        user_id="ua",
        task_id=task_a,
    )
    for denied in (denied_user, denied_tenant, denied_employee):
        assert denied["success"] is False
        assert denied["error_code"] == "unauthorized"
        assert denied["evidence"]["E05_context_snapshot"] == {}
        assert "marker-a" not in json.dumps(denied["evidence"], ensure_ascii=False)
    assert _stored(workspace, task_a)["business_data"]["color"] == "red"
    assert "marker-a" not in json.dumps(_stored(workspace, task_b), ensure_ascii=False)
    assert "marker-b" not in json.dumps(_stored(workspace, task_a), ensure_ascii=False)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(
            pool.map(
                lambda item: _run(
                    workspace,
                    "clerk",
                    continuity_action="run_tools",
                    tenant_id=item[0],
                    user_id=item[1],
                    task_id=item[2],
                ),
                (
                    ("tenant-a", "ua", task_a),
                    ("tenant-a", "ub", task_b),
                    ("tenant-b", "ua", task_c),
                ),
            )
        )
    rows = _effects(workspace, "ship")
    by_task = {row["task_id"]: row["params"]["color"] for row in rows}
    assert by_task.get(task_a) == "red", rows
    assert by_task[task_b] == "blue"
    assert by_task[task_c] == "green"
    return audit_employee_task_ledger(workspace)


def scenario_a34(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "analyze", "ship", "handoff_commit")
    for employee in ("A", "B"):
        _employee_flags(workspace, employee)
    started = _run(
        workspace,
        "A",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="分析后由执行员工发货",
        business_data={"isolation_marker": "a34"},
        steps=[
            {"step_id": "analyze", "tool": "analyze", "params": {"phase": "analyze"}},
            {"step_id": "ship", "tool": "ship", "params": {"phase": "ship"}},
        ],
    )
    task_id = started["task_id"]
    before = len(_ledger(workspace)["tasks"])
    _run(
        workspace,
        "A",
        continuity_action="run_tools",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        only_steps=["analyze"],
    )
    assert _stored(workspace, task_id)["completed_steps"] == ["analyze"]
    _run(
        workspace,
        "A",
        continuity_action="handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        target_employee="B",
        permissions=["ship"],
        idempotency_key="a34-once",
    )
    probed = _run(
        workspace,
        "B",
        continuity_action="run_tools",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        probe_tool="purge",
    )
    assert probed["probe_denied"] is True
    assert _effects(workspace, "ship") == []
    executed = _run(
        workspace,
        "B",
        continuity_action="run_tools",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        only_steps=["ship"],
    )
    assert executed["task_id"] == task_id
    assert len(_ledger(workspace)["tasks"]) == before
    assert len(_effects(workspace, "analyze")) == 1
    assert len(_effects(workspace, "ship")) == 1
    assert executed["business_success"] is True
    handoff = _ledger(workspace)["handoffs"][_stored(workspace, task_id)["handoff_ids"][-1]]
    assert handoff["source_employee"] == "A"
    assert handoff["target_employee"] == "B"
    assert _stored(workspace, task_id)["goal"] == "分析后由执行员工发货"
    return audit_employee_task_ledger(workspace)


def scenario_a35(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "child_work")
    parent = _run(
        workspace,
        "lead",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="汇总三个子任务",
        completion_condition="all_children_success",
        business_data={"isolation_marker": "a35-parent"},
    )
    split = _run(
        workspace,
        "lead",
        continuity_action="split",
        tenant_id="t1",
        user_id="ua",
        task_id=parent["task_id"],
        children=[
            {
                "employee_id": "e1",
                "isolation_marker": "a35-c1",
                "tool": "child_work",
                "params": {"token": "tok-1"},
            },
            {
                "employee_id": "e2",
                "isolation_marker": "a35-c2",
                "tool": "child_work",
                "params": {
                    "token": "tok-2",
                    "fail": True,
                    "error_code": "child_failed",
                    "error_message": "子任务失败",
                },
            },
            {
                "employee_id": "e3",
                "isolation_marker": "a35-c3",
                "tool": "child_work",
                "params": {"token": "tok-3"},
            },
        ],
    )
    child_ids = _stored(workspace, parent["task_id"])["child_task_ids"]
    assert child_ids == split["task"]["child_task_ids"]
    assert len(child_ids) == 3
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(
            pool.map(
                lambda item: _run(
                    workspace,
                    item[0],
                    continuity_action="child_return",
                    tenant_id="t1",
                    user_id="ua",
                    task_id=item[1],
                ),
                (("e1", child_ids[0]), ("e2", child_ids[1]), ("e3", child_ids[2])),
            )
        )
    by_token = {
        _stored(workspace, child_id)["result_payload"]["token"]: _stored(workspace, child_id)[
            "status"
        ]
        for child_id in child_ids
    }
    assert by_token == {"tok-1": "completed", "tok-2": "failed", "tok-3": "completed"}
    assert len(_effects(workspace, "child_work")) == 2
    viewed = _run(
        workspace,
        "lead",
        continuity_action="read",
        tenant_id="t1",
        user_id="ua",
        task_id=parent["task_id"],
    )
    stored_parent = _stored(workspace, parent["task_id"])
    assert stored_parent["aggregate"] == {"success": 2, "failure": 1, "incomplete": 0}
    assert stored_parent["status"] == "failed"
    assert viewed["business_success"] is False
    assert viewed["evidence"]["E02_child_task_id"] in child_ids
    ok_parent = _run(
        workspace,
        "lead",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="全部成功才完成",
        completion_condition="all_children_success",
        business_data={"isolation_marker": "a35-ok"},
    )
    ok_split = _run(
        workspace,
        "lead",
        continuity_action="split",
        tenant_id="t1",
        user_id="ua",
        task_id=ok_parent["task_id"],
        children=[
            {
                "employee_id": "e1",
                "isolation_marker": "a35-d1",
                "tool": "child_work",
                "params": {"token": "d1"},
            },
            {
                "employee_id": "e2",
                "isolation_marker": "a35-d2",
                "tool": "child_work",
                "params": {"token": "d2"},
            },
            {
                "employee_id": "e3",
                "isolation_marker": "a35-d3",
                "tool": "child_work",
                "params": {"token": "d3"},
            },
        ],
    )
    for employee, child_id in zip(
        ("e1", "e2", "e3"), ok_split["task"]["child_task_ids"], strict=True
    ):
        _run(
            workspace,
            employee,
            continuity_action="child_return",
            tenant_id="t1",
            user_id="ua",
            task_id=child_id,
        )
    done = _stored(workspace, ok_parent["task_id"])
    assert done["status"] == "completed"
    assert {item["token"] for item in done["result_payload"]["children"]} == {"d1", "d2", "d3"}
    return audit_employee_task_ledger(workspace)


def scenario_a36(tmp_path: Path) -> dict:
    from tests.fixtures.employee_business_chain import EMPLOYEES, run_business_chain

    workspace = tmp_path / "business-chain"
    proof = run_business_chain(workspace)
    assert proof["complete"], proof
    task_id = proof["task_id"]
    stored = _stored(workspace, task_id)
    assert len(stored["handoff_ids"]) == 4
    handoffs = [_ledger(workspace)["handoffs"][item] for item in stored["handoff_ids"]]
    assert [item["target_employee"] for item in handoffs] == EMPLOYEES
    assert {item["task_id"] for item in handoffs} == {task_id}
    viewed = _run(
        workspace,
        EMPLOYEES[-1],
        continuity_action="read",
        tenant_id="11",
        user_id="11",
        task_id=task_id,
    )
    snapshot = _stored(workspace, task_id)["context_snapshot"]
    assert snapshot["goal"] == stored["goal"]
    employees = [item["employee"] for item in snapshot["prior_results"]]
    assert employees == EMPLOYEES
    assert viewed["task"]["result_payload"]["employee"] == EMPLOYEES[-1]
    assert all(item["result"]["ok"] is True for item in snapshot["prior_results"])
    assert proof["artifacts"] and proof["summary"]["total_amount"] == 200
    return audit_employee_task_ledger(workspace)


def scenario_a37(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "handoff_commit")
    _employee_flags(workspace, "A")
    started = _run(
        workspace,
        "A",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="交给 B 执行一次",
        business_data={"isolation_marker": "a37"},
    )
    task_id = started["task_id"]
    _employee_flags(
        workspace, "B", available=False, timeout=False, crash=False, unrecoverable=False
    )
    missing = _run(
        workspace,
        "A",
        continuity_action="handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        target_employee="B",
        permissions=["run"],
        idempotency_key="a37-effect",
    )
    assert missing["business_success"] is False
    assert _stored(workspace, task_id)["error_code"] == "employee_unavailable"
    retried = _run(
        workspace,
        "A",
        continuity_action="retry_handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert retried["business_success"] is False
    assert retried["inherited"]["goal"] == "交给 B 执行一次"
    assert "a37-effect" not in _ledger(workspace)["side_effects"]
    _employee_flags(workspace, "B", available=True, timeout=True, crash=False, unrecoverable=False)
    timed = _run(
        workspace,
        "A",
        continuity_action="retry_handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert _stored(workspace, task_id)["error_code"] == "employee_timeout"
    _employee_flags(workspace, "B", available=True, timeout=False, crash=True, unrecoverable=False)
    crashed = _run(
        workspace,
        "A",
        continuity_action="retry_handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert crashed["business_success"] is False
    assert _stored(workspace, task_id)["status"] == "failed"
    rolled = _run(
        workspace,
        "A",
        continuity_action="retry_handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        policy="rollback",
    )
    assert _stored(workspace, task_id)["status"] == "failed"
    assert _stored(workspace, task_id)["error_code"] == "rolled_back"
    _employee_flags(workspace, "B", available=True, timeout=False, crash=False, unrecoverable=True)
    stuck = _run(
        workspace,
        "A",
        continuity_action="retry_handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert stuck["business_success"] is False
    assert _stored(workspace, task_id)["error_code"] == "employee_crashed"
    crash_records = [
        item
        for item in _ledger(workspace)["handoffs"].values()
        if item["error_code"] == "employee_crashed"
    ]
    assert crash_records and crash_records[0]["status"] == "failed"
    _employee_flags(workspace, "B", available=True, timeout=False, crash=False, unrecoverable=False)
    restored = _run(
        workspace,
        "A",
        continuity_action="retry_handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert restored["business_success"] is True
    assert _stored(workspace, task_id)["status"] == "completed"
    assert _ledger(workspace)["side_effects"]["a37-effect"]["invocations"] == 1
    assert len(_effects(workspace, "handoff_commit")) == 1
    duplicate = _run(
        workspace,
        "A",
        continuity_action="retry_handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert duplicate["handoff"]["duplicate_prevented"] is True
    assert _ledger(workspace)["side_effects"]["a37-effect"]["invocations"] == 1
    assert len(_effects(workspace, "handoff_commit")) == 1
    assert len(_ledger(workspace)["tasks"]) == 1
    assert crash_records[0]["status"] == "failed"
    return audit_employee_task_ledger(workspace)


def scenario_a38(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "t1", "t2", "t3", "t4")
    (workspace / "fail").mkdir()
    (workspace / "fail" / "t2").write_text("t2 failed", encoding="utf-8")
    started = _run(
        workspace,
        "clerk",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="三工具部分成功",
        business_data={"isolation_marker": "a38"},
        steps=[
            {"step_id": "s1", "tool": "t1", "params": {"n": 1}, "idempotent": False},
            {"step_id": "s2", "tool": "t2", "params": {"n": 2}, "idempotent": False},
            {"step_id": "s3", "tool": "t3", "params": {"n": 3}, "idempotent": False},
            {
                "step_id": "s4",
                "tool": "t4",
                "params": {"n": 4},
                "depends_on": ["s2"],
                "idempotent": False,
            },
        ],
    )
    task_id = started["task_id"]
    partial = _run(
        workspace,
        "clerk",
        "全部工具都已成功",
        continuity_action="run_tools",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        model_text="全部工具都已成功",
    )
    stored = _stored(workspace, task_id)
    assert partial["business_success"] is False
    assert stored["status"] == "partial_success"
    assert len(_effects(workspace, "t1")) == 1
    assert _effects(workspace, "t2") == []
    assert len(_effects(workspace, "t3")) == 1
    assert _effects(workspace, "t4") == []
    calls = {
        item["step_id"]: item["status"]
        for item in _ledger(workspace)["tool_calls"].values()
        if item["task_id"] == task_id
    }
    assert calls["s1"] == "success"
    assert calls["s2"] == "failed"
    assert calls["s3"] == "success"
    assert "s4" not in calls
    assert "全部工具都已成功" in stored["speculative"]
    (workspace / "fail" / "t2").unlink()
    retried = _run(
        workspace,
        "clerk",
        continuity_action="retry_step",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        step_id="s2",
    )
    assert len(_effects(workspace, "t1")) == 1
    assert len(_effects(workspace, "t2")) == 1
    assert retried["task"]["steps"][1]["status"] == "success"
    continued = _run(
        workspace,
        "clerk",
        continuity_action="run_tools",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert len(_effects(workspace, "t4")) == 1
    assert continued["business_success"] is True
    assert all(item["invocations"] == 1 for item in _ledger(workspace)["side_effects"].values())
    return audit_employee_task_ledger(workspace)


class _SummaryProvider:
    provider_id = "fake-summary"
    provider_name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(self, **kwargs):
        self.calls += 1
        return {
            "choices": [
                {"message": {"content": "已完成全部发货，客户参数改为 SKU-FAKE，推测已经付款。"}}
            ],
            "usage": {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50},
            "model": "fake-1",
        }


def scenario_a39(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    workspace = tmp_path
    _install(workspace, "done", "left")
    provider = _SummaryProvider()
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda: provider
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(workspace / "usage.json"))
    started = _run(
        workspace,
        "clerk",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="完成未发货步骤",
        fact_params={"sku": "SKU-REAL", "qty": 4},
        constraints=["不得超卖"],
        business_data={"isolation_marker": "a39"},
        steps=[
            {"step_id": "done", "tool": "done", "params": {"sku": "SKU-REAL"}},
            {"step_id": "left", "tool": "left", "params": {"sku": "SKU-REAL"}},
        ],
    )
    task_id = started["task_id"]
    _run(
        workspace,
        "clerk",
        continuity_action="run_tools",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        only_steps=["done"],
    )
    done_call = next(
        item["tool_call_id"]
        for item in _ledger(workspace)["tool_calls"].values()
        if item["step_id"] == "done"
    )
    turns = [
        (
            "user",
            "目标是完成未发货步骤",
            {"key": "goal", "value": "完成未发货步骤", "confidence": "confirmed", "kind": "goal"},
        ),
        (
            "user",
            "关键参数 sku=SKU-REAL qty=4",
            {
                "key": "params",
                "value": {"sku": "SKU-REAL", "qty": 4},
                "confidence": "confirmed",
                "kind": "params",
            },
        ),
        (
            "user",
            "约束：不得超卖",
            {
                "key": "constraints",
                "value": ["不得超卖"],
                "confidence": "confirmed",
                "kind": "constraint",
            },
        ),
        (
            "assistant",
            "已确认先完成 done 步骤",
            {
                "key": "conclusion",
                "value": "done 已完成，left 未做",
                "confidence": "confirmed",
                "kind": "conclusion",
            },
        ),
        (
            "tool",
            "done 成功",
            {
                "kind": "tool_result",
                "confidence": "confirmed",
                "tool_call_id": done_call,
                "key": "tool_done",
                "value": "done",
            },
        ),
        (
            "assistant",
            "也许客户还想要礼品包装",
            {"kind": "speculation", "confidence": "speculative", "value": "礼品包装"},
        ),
        (
            "assistant",
            "模型声称全部发货已成功",
            {
                "kind": "tool_result",
                "confidence": "confirmed",
                "key": "fake_ship",
                "value": "全部发货已成功",
            },
        ),
    ]
    for index in range(100):
        if index < len(turns):
            role, content, fact = turns[index]
        else:
            role, content, fact = ("user", f"第{index}轮业务对话 " + ("明细" * 40), {})
        _run(
            workspace,
            "clerk",
            content,
            continuity_action="append_turn",
            tenant_id="t1",
            user_id="ua",
            task_id=task_id,
            role=role,
            content=content,
            fact=fact,
        )
    before_calls = len(_ledger(workspace)["tool_calls"])
    compressed = _run(
        workspace,
        "clerk",
        continuity_action="compress",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert compressed["compression_strategy"] == "summarize"
    assert provider.calls == 1
    assert compressed["post_message_count"] < compressed["pre_message_count"]
    stored = _stored(workspace, task_id)
    assert stored["confirmed_facts"]["goal"] == "完成未发货步骤"
    assert stored["confirmed_facts"]["params"]["sku"] == "SKU-REAL"
    assert "SKU-FAKE" not in json.dumps(stored["confirmed_facts"], ensure_ascii=False)
    assert "礼品包装" not in json.dumps(stored["confirmed_facts"], ensure_ascii=False)
    assert stored["rejected_claims"]
    assert len(_ledger(workspace)["tool_calls"]) == before_calls
    again = _run(
        workspace,
        "clerk",
        continuity_action="compress",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    assert again["facts_stable"] is True
    assert provider.calls == 2
    continued = _run(
        workspace,
        "clerk",
        continuity_action="continue_compressed",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
    )
    restated = continued["restatement"]
    assert restated["goal"] == "完成未发货步骤"
    assert restated["params"]["sku"] == "SKU-REAL"
    assert restated["constraints"] == ["不得超卖"]
    assert [item["tool_call_id"] for item in restated["completed_ops"]] == [done_call]
    assert len(_effects(workspace, "done")) == 1
    assert len(_effects(workspace, "left")) == 1
    assert _stored(workspace, task_id)["steps"][1]["status"] == "success"
    assert "全部发货已成功" not in json.dumps(
        _stored(workspace, task_id)["confirmed_facts"], ensure_ascii=False
    )
    return audit_employee_task_ledger(workspace)


def _crash_worker(workspace: Path, task_id: str) -> None:
    payload = {
        "continuity_action": "run_tools",
        "tenant_id": "t1",
        "user_id": "ua",
        "session_id": "s",
        "task_id": task_id,
        "only_steps": ["fly"],
        "workspace_root": str(workspace),
    }
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", _CRASH_DRIVER, json.dumps(payload), str(workspace)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    detail = (
        (workspace / "crash_result.json").read_text(encoding="utf-8")
        if (workspace / "crash_result.json").is_file()
        else proc.stderr
    )
    assert proc.returncode != 0, detail


def scenario_a40(tmp_path: Path) -> dict:
    workspace = tmp_path
    _install(workspace, "done", "wait", "handoff_commit", "child_work", kill=("fly",))
    for employee in ("clerk", "relay"):
        _employee_flags(workspace, employee)
    started = _run(
        workspace,
        "clerk",
        continuity_action="start",
        tenant_id="t1",
        user_id="ua",
        goal="中途可恢复的复合任务",
        conversation_id="conv-a40",
        business_data={"isolation_marker": "a40"},
        execute_limit=1,
        steps=[
            {"step_id": "done", "tool": "done", "params": {"phase": "done"}},
            {"step_id": "wait", "tool": "wait", "params": {"phase": "wait"}},
            {"step_id": "fly", "tool": "fly", "params": {"phase": "fly"}},
        ],
    )
    task_id = started["task_id"]
    done_result = next(
        step["result_payload"]
        for step in _stored(workspace, task_id)["steps"]
        if step["step_id"] == "done"
    )
    _run(
        workspace,
        "clerk",
        continuity_action="handoff",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        target_employee="relay",
        permissions=["wait"],
        idempotency_key="a40-handoff",
    )
    _crash_worker(workspace, task_id)
    assert (
        next(
            item["status"]
            for item in _ledger(workspace)["tool_calls"].values()
            if item["step_id"] == "fly"
        )
        == "running"
    )
    split = _run(
        workspace,
        "clerk",
        continuity_action="split",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        children=[
            {
                "employee_id": "c1",
                "isolation_marker": "a40-c1",
                "tool": "child_work",
                "params": {"token": "c1"},
            },
            {
                "employee_id": "c2",
                "isolation_marker": "a40-c2",
                "tool": "child_work",
                "params": {"token": "c2"},
            },
            {
                "employee_id": "c3",
                "isolation_marker": "a40-c3",
                "tool": "child_work",
                "params": {"token": "c3"},
            },
        ],
    )
    children = list(_stored(workspace, task_id)["child_task_ids"])
    assert children == split["task"]["child_task_ids"]
    _run(
        workspace,
        "clerk",
        continuity_action="append_turn",
        tenant_id="t1",
        user_id="ua",
        task_id=task_id,
        content="暂停前的业务备注",
        fact={
            "confidence": "confirmed",
            "kind": "note",
            "key": "note",
            "value": "暂停前的业务备注",
        },
    )
    message_count = len(_stored(workspace, task_id)["messages"])
    handoff_id = _stored(workspace, task_id)["handoff_ids"][-1]
    paused = _run(
        workspace, "clerk", continuity_action="pause", tenant_id="t1", user_id="ua", task_id=task_id
    )
    assert paused["task"]["status"] == "paused"
    causes = ("client_close", "client_crash", "backend_restart", "scheduler_restart")
    snapshots = []
    for cause in causes:
        recovered = _run(
            workspace,
            "clerk",
            continuity_action="restart",
            tenant_id="t1",
            user_id="ua",
            task_id=task_id,
            cause=cause,
        )
        assert recovered["business_success"] is False
        assert recovered["restart"]["memory_dropped"] is True
        assert recovered["restart"]["reloaded_from"].endswith("employee_task_ledger.json")
        assert recovered["restart"]["cause"] == cause
        snapshots.append(_stored(workspace, task_id))
    assert len(_effects(workspace, "done")) == 1
    assert _effects(workspace, "wait") == []
    assert _effects(workspace, "fly") == []
    restored = snapshots[-1]
    assert restored["task_id"] == task_id
    assert restored["child_task_ids"] == children
    assert all(
        _ledger(workspace)["tasks"][child]["parent_task_id"] == task_id for child in children
    )
    assert all(_ledger(workspace)["tasks"][child]["status"] != "completed" for child in children)
    by_step = {step["step_id"]: step for step in restored["steps"]}
    assert by_step["done"]["status"] == "success"
    assert by_step["done"]["result_payload"] == done_result
    assert by_step["wait"]["status"] == "pending"
    assert by_step["fly"]["status"] == "recovering"
    fly_call = next(
        item for item in _ledger(workspace)["tool_calls"].values() if item["step_id"] == "fly"
    )
    assert fly_call["status"] == "recovering"
    assert fly_call["resubmitted"] is False
    assert restored["status"] == "recovering"
    assert restored["handoff_ids"][-1] == handoff_id
    assert len(_stored(workspace, task_id)["messages"]) == message_count
    assert (
        len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in snapshots[1:]}) == 1
    )
    assert len(_ledger(workspace)["restarts"]) == 4
    return audit_employee_task_ledger(workspace)


SCENARIOS = (
    scenario_a31,
    scenario_a32,
    scenario_a33,
    scenario_a34,
    scenario_a35,
    scenario_a36,
    scenario_a37,
    scenario_a38,
    scenario_a39,
    scenario_a40,
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[fn.__name__ for fn in SCENARIOS])
def test_checklist_scenario(scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = scenario(tmp_path, monkeypatch) if scenario is scenario_a39 else scenario(tmp_path)
    assert metrics["pollution"] == 0
    assert metrics["duplicate_side_effects"] == 0
    assert metrics["orphan_count"] == 0


def test_section_e_quantitative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    passed = 0
    pollution = 0
    duplicates = 0
    for scenario in SCENARIOS:
        metrics = (
            scenario(tmp_path / scenario.__name__, monkeypatch)
            if scenario is scenario_a39
            else scenario(tmp_path / scenario.__name__)
        )
        assert metrics["pollution"] == 0
        assert metrics["duplicate_side_effects"] == 0
        pollution += metrics["pollution"]
        duplicates += metrics["duplicate_side_effects"]
        passed += 1
    assert passed == 10
    assert passed / len(SCENARIOS) == 1.0
    assert pollution == 0
    assert duplicates == 0
