"""A31–A40 acceptance: employee multi-turn handoff and context continuity."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.application.employee_runtime.agent import EmployeeAgent
from app.application.employee_runtime.task_continuity import (
    CONTINUE_TEXT,
    bound_continuity_runtime,
    execute_continuity_turn,
)

EVIDENCE_KEYS = (
    "E01_task_id",
    "E02_parent_task_id",
    "E02_child_task_id",
    "E03_handoff_id",
    "E04_source_employee",
    "E04_target_employee",
    "E05_context_snapshot",
    "E06_context_version",
    "E07_conversation_id",
    "E08_tool_call_id",
    "E09_execution_status",
    "E10_retry_count",
    "E11_idempotency_key",
    "E12_result_payload",
    "E13_error_code",
    "E13_error_message",
    "E14_recovery_record",
    "E15_event_timestamp",
    "E16_restart_recovery_record",
)


def _assert_evidence(result: dict) -> None:
    evidence = result["evidence"]
    for key in EVIDENCE_KEYS:
        assert key in evidence
    for event in result.get("events") or []:
        for key in EVIDENCE_KEYS:
            assert key in event["evidence"]
        assert event["evidence"]["E15_event_timestamp"]


def _turn(
    runtime,
    employee: str,
    op: str,
    *,
    tenant: str,
    user: str,
    session: str = "s",
    text: str = "",
    **extra,
):
    payload = {
        "invoke_mode": "task_continuity",
        "op": op,
        "continuity_runtime_id": runtime.runtime_id,
        "tenant_id": tenant,
        "user_id": user,
        "session_id": session,
        **extra,
    }
    result = EmployeeAgent(employee).run(text, payload, session_id=session)
    if op != "metrics" and op != "set_employee":
        _assert_evidence(result)
    return result


def _metrics(runtime, *, tenant: str = "t", user: str = "u") -> dict:
    return _turn(runtime, "auditor", "metrics", tenant=tenant, user=user)


def _counter(bucket: dict[str, int], name: str):
    def _run(params, task_id):
        bucket[name] = bucket.get(name, 0) + 1
        bucket.setdefault("seen", []).append((name, task_id, dict(params)))
        return {"ok": True, "tool": name, "task_id": task_id, "params": params}

    return _run


def test_non_continuity_turn_is_not_captured() -> None:
    assert execute_continuity_turn("clerk", "hello", {"invoke_mode": "chat"}) is None


def scenario_a31(tmp_path: Path) -> dict:
    calls: dict = {}
    with bound_continuity_runtime(tmp_path / "a31.json") as runtime:
        runtime.register_tool("pack", _counter(calls, "pack"))
        started = _turn(
            runtime,
            "clerk",
            "start",
            tenant="t1",
            user="ua",
            session="sa",
            text="打包并发运",
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
        assert started["task"]["completed_steps"] == ["s1"]
        paused = _turn(runtime, "clerk", "pause", tenant="t1", user="ua", task_id=task_id)
        assert paused["task"]["status"] == "paused"
        wrong = _turn(
            runtime, "clerk", "resume", tenant="t1", user="ua", task_id=task_id, text="继续"
        )
        assert wrong["success"] is False
        assert calls["pack"] == 1
        resumed = _turn(
            runtime, "clerk", "resume", tenant="t1", user="ua", task_id=task_id, text=CONTINUE_TEXT
        )
        assert resumed["task_id"] == task_id
        assert calls["pack"] == 3
        assert resumed["task"]["status"] == "completed"
        added = _turn(
            runtime,
            "clerk",
            "append_requirements",
            tenant="t1",
            user="ua",
            task_id=task_id,
            requirements=["补保险"],
            tool="pack",
        )
        assert added["task"]["status"] == "paused"
        finished = _turn(
            runtime, "clerk", "resume", tenant="t1", user="ua", task_id=task_id, text=CONTINUE_TEXT
        )
        assert finished["task_id"] == task_id
        assert calls["pack"] == 4
        assert finished["task"]["requirements"] == ["先打包", "补保险"]
        left = _turn(runtime, "clerk", "leave", tenant="t1", user="ua", task_id=task_id)
        assert left["task_id"] == task_id
        cache_key = "t1:ua:conv-a31"
        assert cache_key not in runtime._session_cache
        back = _turn(
            runtime,
            "clerk",
            "reenter",
            tenant="t1",
            user="ua",
            conversation_id="conv-a31",
        )
        assert back["task_id"] == task_id
        assert back["task"]["completed_steps"] == ["s1", "s2", "s3", "s4"]
        kinds = [event["kind"] for event in back["events"]]
        assert kinds[0] == "task_created"
        assert "task_resumed" in kinds
        return _metrics(runtime)


def scenario_a32(tmp_path: Path) -> dict:
    with bound_continuity_runtime(tmp_path / "a32.json") as runtime:
        started = _turn(
            runtime,
            "analyst",
            "start",
            tenant="t1",
            user="ua",
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
        handed = _turn(
            runtime,
            "analyst",
            "handoff",
            tenant="t1",
            user="ua",
            task_id=task_id,
            target_employee="executor",
            permissions=["note"],
            conditions={"priority": "low", "window": "night"},
            idempotency_key="a32-handoff",
        )
        assert handed["task_id"] == task_id
        viewed = _turn(runtime, "executor", "read", tenant="t1", user="ua", task_id=task_id)
        snapshot = viewed["evidence"]["E05_context_snapshot"]
        assert snapshot["goal"] == "按原条件发货"
        assert snapshot["business_data"]["sku"] == "SKU-9"
        assert snapshot["constraints"] == ["不得改地址"]
        assert snapshot["completed_steps"] == ["done"]
        assert "left" in snapshot["remaining_steps"]
        assert snapshot["conditions"]["channel"] == "sea"
        assert snapshot["conditions"]["window"] == "night"
        assert snapshot["conditions"]["priority"]["kept"] == "high"
        assert snapshot["conditions"]["priority"]["added"] == "low"
        assert viewed["evidence"]["E04_source_employee"] == "analyst"
        assert viewed["evidence"]["E04_target_employee"] == "executor"
        return _metrics(runtime)


def scenario_a33(tmp_path: Path) -> dict:
    seen: list = []

    def _tool(params, task_id):
        seen.append((task_id, dict(params)))
        return {"ok": True, "task_id": task_id, "params": params}

    with bound_continuity_runtime(tmp_path / "a33.json") as runtime:
        runtime.register_tool("ship", _tool)

        def _start(user, tenant, session, marker, color):
            return _turn(
                runtime,
                "clerk",
                "start",
                tenant=tenant,
                user=user,
                session=session,
                goal="处理相似订单",
                business_data={"isolation_marker": marker, "color": color},
                steps=[
                    {"step_id": "s1", "tool": "ship", "params": {"color": color, "marker": marker}}
                ],
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(_start, "ua", "tenant-a", "sa", "marker-a", "red")
            second = pool.submit(_start, "ub", "tenant-a", "sb", "marker-b", "blue")
            task_a = first.result()
            task_b = second.result()
        task_c = _start("ua", "tenant-b", "sc", "marker-c", "green")
        assert len({task_a["task_id"], task_b["task_id"], task_c["task_id"]}) == 3
        denied_user = _turn(
            runtime, "clerk", "read", tenant="tenant-a", user="ub", task_id=task_a["task_id"]
        )
        denied_tenant = _turn(
            runtime, "clerk", "read", tenant="tenant-b", user="ua", task_id=task_a["task_id"]
        )
        denied_employee = _turn(
            runtime, "intruder", "read", tenant="tenant-a", user="ua", task_id=task_a["task_id"]
        )
        for denied in (denied_user, denied_tenant, denied_employee):
            assert denied["success"] is False
            assert denied["error_code"] == "unauthorized"
            assert denied["evidence"]["E05_context_snapshot"] == {}
            assert "marker-a" not in json.dumps(denied["evidence"], ensure_ascii=False)
        own = _turn(
            runtime,
            "clerk",
            "read",
            tenant="tenant-a",
            user="ua",
            session="sb",
            task_id=task_a["task_id"],
        )
        other = _turn(
            runtime,
            "clerk",
            "read",
            tenant="tenant-a",
            user="ub",
            session="sa",
            task_id=task_b["task_id"],
        )
        assert own["task"]["business_data"]["color"] == "red"
        assert other["task"]["business_data"]["color"] == "blue"
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(
                pool.map(
                    lambda item: _turn(
                        runtime, "clerk", "run_tools", tenant=item[0], user=item[1], task_id=item[2]
                    ),
                    (
                        ("tenant-a", "ua", task_a["task_id"]),
                        ("tenant-a", "ub", task_b["task_id"]),
                        ("tenant-b", "ua", task_c["task_id"]),
                    ),
                )
            )
        by_task = {task_id: params["color"] for task_id, params in seen}
        assert by_task[task_a["task_id"]] == "red"
        assert by_task[task_b["task_id"]] == "blue"
        assert by_task[task_c["task_id"]] == "green"
        return _metrics(runtime)


def scenario_a34(tmp_path: Path) -> dict:
    calls: dict = {}
    with bound_continuity_runtime(tmp_path / "a34.json") as runtime:
        runtime.register_tool("analyze", _counter(calls, "analyze"))
        runtime.register_tool("ship", _counter(calls, "ship"))
        started = _turn(
            runtime,
            "A",
            "start",
            tenant="t1",
            user="ua",
            goal="分析后由执行员工发货",
            business_data={"isolation_marker": "a34"},
            steps=[
                {"step_id": "analyze", "tool": "analyze", "params": {"phase": "analyze"}},
                {"step_id": "ship", "tool": "ship", "params": {"phase": "ship"}},
            ],
        )
        task_id = started["task_id"]
        before = len(runtime.state["tasks"])
        analyzed = _turn(
            runtime,
            "A",
            "run_tools",
            tenant="t1",
            user="ua",
            task_id=task_id,
            only_steps=["analyze"],
        )
        assert analyzed["task"]["completed_steps"] == ["analyze"]
        handed = _turn(
            runtime,
            "A",
            "handoff",
            tenant="t1",
            user="ua",
            task_id=task_id,
            target_employee="B",
            permissions=["ship"],
            idempotency_key="a34-once",
        )
        probed = _turn(
            runtime, "B", "run_tools", tenant="t1", user="ua", task_id=task_id, probe_tool="purge"
        )
        assert probed["probe_denied"] is True
        assert calls.get("ship", 0) == 0
        executed = _turn(
            runtime, "B", "run_tools", tenant="t1", user="ua", task_id=task_id, only_steps=["ship"]
        )
        assert executed["task_id"] == task_id
        assert len(runtime.state["tasks"]) == before
        assert calls["analyze"] == 1
        assert calls["ship"] == 1
        assert executed["business_success"] is True
        assert executed["evidence"]["E03_handoff_id"]
        assert executed["evidence"]["E04_source_employee"] == "A"
        assert executed["evidence"]["E04_target_employee"] == "B"
        assert executed["task"]["goal"] == "分析后由执行员工发货"
        return _metrics(runtime)


def scenario_a35(tmp_path: Path) -> dict:
    with bound_continuity_runtime(tmp_path / "a35.json") as runtime:
        parent = _turn(
            runtime,
            "lead",
            "start",
            tenant="t1",
            user="ua",
            goal="汇总三个子任务",
            completion_condition="all_children_success",
            business_data={"isolation_marker": "a35-parent"},
        )
        split = _turn(
            runtime,
            "lead",
            "split",
            tenant="t1",
            user="ua",
            task_id=parent["task_id"],
            children=[
                {"employee_id": "e1", "isolation_marker": "a35-c1"},
                {"employee_id": "e2", "isolation_marker": "a35-c2"},
                {"employee_id": "e3", "isolation_marker": "a35-c3"},
            ],
        )
        child_ids = split["task"]["child_task_ids"]
        assert len(child_ids) == 3
        workers = (
            ("e1", child_ids[0], True, "tok-1"),
            ("e2", child_ids[1], False, "tok-2"),
            ("e3", child_ids[2], True, "tok-3"),
        )
        with ThreadPoolExecutor(max_workers=3) as pool:
            returned = list(
                pool.map(
                    lambda item: _turn(
                        runtime,
                        item[0],
                        "child_return",
                        tenant="t1",
                        user="ua",
                        task_id=item[1],
                        ok=item[2],
                        token=item[3],
                        error_code="child_failed",
                        error_message="子任务失败",
                    ),
                    workers,
                )
            )
        by_token = {
            item["task"]["result_payload"]["token"]: item["task"]["status"] for item in returned
        }
        assert by_token == {"tok-1": "completed", "tok-2": "failed", "tok-3": "completed"}
        viewed = _turn(runtime, "lead", "read", tenant="t1", user="ua", task_id=parent["task_id"])
        assert viewed["task"]["aggregate"] == {"success": 2, "failure": 1, "incomplete": 0}
        assert viewed["task"]["status"] == "failed"
        assert viewed["business_success"] is False
        assert viewed["evidence"]["E02_parent_task_id"] == ""
        assert viewed["evidence"]["E02_child_task_id"] in child_ids
        ok_parent = _turn(
            runtime,
            "lead",
            "start",
            tenant="t1",
            user="ua",
            goal="全部成功才完成",
            completion_condition="all_children_success",
            business_data={"isolation_marker": "a35-ok"},
        )
        ok_split = _turn(
            runtime,
            "lead",
            "split",
            tenant="t1",
            user="ua",
            task_id=ok_parent["task_id"],
            children=[
                {"employee_id": "e1", "isolation_marker": "a35-d1"},
                {"employee_id": "e2", "isolation_marker": "a35-d2"},
                {"employee_id": "e3", "isolation_marker": "a35-d3"},
            ],
        )
        for employee, child_id, token in zip(
            ("e1", "e2", "e3"), ok_split["task"]["child_task_ids"], ("d1", "d2", "d3"), strict=True
        ):
            _turn(
                runtime,
                employee,
                "child_return",
                tenant="t1",
                user="ua",
                task_id=child_id,
                ok=True,
                token=token,
            )
        done = _turn(runtime, "lead", "read", tenant="t1", user="ua", task_id=ok_parent["task_id"])
        assert done["task"]["status"] == "completed"
        assert done["business_success"] is True
        return _metrics(runtime)


def scenario_a36(tmp_path: Path) -> dict:
    with bound_continuity_runtime(tmp_path / "a36.json") as runtime:
        started = _turn(
            runtime,
            "A",
            "start",
            tenant="t1",
            user="ua",
            goal="原始目标保持不变",
            business_data={"isolation_marker": "a36"},
            requirements=["沿链传递"],
        )
        task_id = started["task_id"]
        chained = _turn(
            runtime,
            "A",
            "chain",
            tenant="t1",
            user="ua",
            task_id=task_id,
            employees=["A", "B", "C", "D"],
            permissions=["continue"],
        )
        assert chained["task_id"] == task_id
        assert chained["business_success"] is True
        assert len(chained["task"]["handoff_ids"]) == 3
        handoffs = [runtime.state["handoffs"][item] for item in chained["task"]["handoff_ids"]]
        assert [(item["source_employee"], item["target_employee"]) for item in handoffs] == [
            ("A", "B"),
            ("B", "C"),
            ("C", "D"),
        ]
        assert {item["task_id"] for item in handoffs} == {task_id}
        viewed = _turn(runtime, "D", "read", tenant="t1", user="ua", task_id=task_id)
        snapshot = viewed["task"]["context_snapshot"]
        assert snapshot["goal"] == "原始目标保持不变"
        employees = [item["employee"] for item in snapshot["prior_results"]]
        assert employees == ["A", "B", "C", "D"]
        assert viewed["task"]["result_payload"]["employee"] == "D"
        assert viewed["evidence"]["E01_task_id"] == task_id
        return _metrics(runtime)


def scenario_a37(tmp_path: Path) -> dict:
    with bound_continuity_runtime(tmp_path / "a37.json") as runtime:
        started = _turn(
            runtime,
            "A",
            "start",
            tenant="t1",
            user="ua",
            goal="交给 B 执行一次",
            business_data={"isolation_marker": "a37"},
        )
        task_id = started["task_id"]
        _turn(
            runtime,
            "A",
            "set_employee",
            tenant="t1",
            user="ua",
            target_employee="B",
            available=False,
        )
        missing = _turn(
            runtime,
            "A",
            "handoff",
            tenant="t1",
            user="ua",
            task_id=task_id,
            target_employee="B",
            permissions=["run"],
            idempotency_key="a37-effect",
        )
        assert missing["business_success"] is False
        assert missing["task"]["error_code"] == "employee_unavailable"
        retried = _turn(runtime, "A", "retry_handoff", tenant="t1", user="ua", task_id=task_id)
        assert retried["business_success"] is False
        assert retried["inherited"]["goal"] == "交给 B 执行一次"
        assert "a37-effect" not in runtime.state["side_effects"]
        _turn(
            runtime,
            "A",
            "set_employee",
            tenant="t1",
            user="ua",
            target_employee="B",
            available=True,
            timeout=True,
        )
        timed = _turn(runtime, "A", "retry_handoff", tenant="t1", user="ua", task_id=task_id)
        assert timed["task"]["error_code"] == "employee_timeout"
        _turn(
            runtime,
            "A",
            "set_employee",
            tenant="t1",
            user="ua",
            target_employee="B",
            timeout=False,
            crash=True,
        )
        crashed = _turn(runtime, "A", "retry_handoff", tenant="t1", user="ua", task_id=task_id)
        assert crashed["business_success"] is False
        assert crashed["task"]["status"] == "failed"
        rolled = _turn(
            runtime,
            "A",
            "retry_handoff",
            tenant="t1",
            user="ua",
            task_id=task_id,
            policy="rollback",
        )
        assert rolled["task"]["status"] == "failed"
        assert rolled["task"]["error_code"] == "rolled_back"
        _turn(
            runtime,
            "A",
            "set_employee",
            tenant="t1",
            user="ua",
            target_employee="B",
            crash=False,
            unrecoverable=True,
        )
        stuck = _turn(runtime, "A", "retry_handoff", tenant="t1", user="ua", task_id=task_id)
        assert stuck["business_success"] is False
        assert stuck["task"]["error_code"] == "employee_crashed"
        crash_records = [
            item
            for item in runtime.state["handoffs"].values()
            if item["error_code"] == "employee_crashed"
        ]
        assert crash_records and crash_records[0]["status"] == "failed"
        _turn(
            runtime,
            "A",
            "set_employee",
            tenant="t1",
            user="ua",
            target_employee="B",
            available=True,
            timeout=False,
            crash=False,
            unrecoverable=False,
        )
        restored = _turn(runtime, "A", "retry_handoff", tenant="t1", user="ua", task_id=task_id)
        assert restored["business_success"] is True
        assert restored["task"]["status"] == "completed"
        assert runtime.state["side_effects"]["a37-effect"]["invocations"] == 1
        duplicate = _turn(runtime, "A", "retry_handoff", tenant="t1", user="ua", task_id=task_id)
        assert duplicate["handoff"]["duplicate_prevented"] is True
        assert runtime.state["side_effects"]["a37-effect"]["invocations"] == 1
        assert len(runtime.state["tasks"]) == 1
        assert crash_records[0]["status"] == "failed"
        return _metrics(runtime)


def scenario_a38(tmp_path: Path) -> dict:
    calls = {"t1": 0, "t2": 0, "t3": 0, "t4": 0}
    fail = {"t2": True}

    def _make(name: str):
        def _run(params, task_id):
            calls[name] += 1
            if name == "t2" and fail["t2"]:
                return {"ok": False, "error_code": "tool_failed", "error_message": "t2 failed"}
            return {"ok": True, "tool": name, "task_id": task_id}

        return _run

    with bound_continuity_runtime(tmp_path / "a38.json") as runtime:
        for name in calls:
            runtime.register_tool(name, _make(name))
        started = _turn(
            runtime,
            "clerk",
            "start",
            tenant="t1",
            user="ua",
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
        partial = _turn(
            runtime,
            "clerk",
            "run_tools",
            tenant="t1",
            user="ua",
            task_id=task_id,
            model_text="全部工具都已成功",
        )
        assert partial["business_success"] is False
        assert partial["task"]["status"] == "partial_success"
        assert calls == {"t1": 1, "t2": 1, "t3": 1, "t4": 0}
        summary = {item["step_id"]: item["status"] for item in partial["execution_summary"]}
        assert summary == {"s1": "success", "s2": "failed", "s3": "success", "s4": "blocked"}
        records = {
            item["step_id"]: item["status"]
            for item in runtime.state["tool_calls"].values()
            if item["task_id"] == task_id
        }
        assert records["s1"] == "success"
        assert records["s2"] == "failed"
        assert records["s3"] == "success"
        assert "s4" not in records
        assert "全部工具都已成功" in partial["task"]["speculative"]
        fail["t2"] = False
        retried = _turn(
            runtime, "clerk", "retry_step", tenant="t1", user="ua", task_id=task_id, step_id="s2"
        )
        assert calls == {"t1": 1, "t2": 2, "t3": 1, "t4": 0}
        assert retried["task"]["steps"][1]["status"] == "success"
        continued = _turn(runtime, "clerk", "run_tools", tenant="t1", user="ua", task_id=task_id)
        assert calls == {"t1": 1, "t2": 2, "t3": 1, "t4": 1}
        assert continued["business_success"] is True
        assert all(item["invocations"] == 1 for item in runtime.state["side_effects"].values())
        return _metrics(runtime)


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


def scenario_a39(tmp_path: Path) -> dict:
    calls = {"done": 0, "left": 0}
    with bound_continuity_runtime(tmp_path / "a39.json") as runtime:
        runtime.register_tool("done", _counter(calls, "done"))
        runtime.register_tool("left", _counter(calls, "left"))
        runtime.summary_provider = _SummaryProvider()
        os.environ["MODEL_USAGE_LEDGER_PATH"] = str(tmp_path / "usage.json")
        started = _turn(
            runtime,
            "clerk",
            "start",
            tenant="t1",
            user="ua",
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
        _turn(
            runtime,
            "clerk",
            "run_tools",
            tenant="t1",
            user="ua",
            task_id=task_id,
            only_steps=["done"],
        )
        done_call = next(item["tool_call_id"] for item in runtime.state["tool_calls"].values())
        turns = [
            (
                "user",
                "目标是完成未发货步骤",
                {
                    "key": "goal",
                    "value": "完成未发货步骤",
                    "confidence": "confirmed",
                    "kind": "goal",
                },
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
            _turn(
                runtime,
                "clerk",
                "append_turn",
                tenant="t1",
                user="ua",
                task_id=task_id,
                role=role,
                content=content,
                fact=fact,
            )
        before_calls = len(runtime.state["tool_calls"])
        compressed = _turn(runtime, "clerk", "compress", tenant="t1", user="ua", task_id=task_id)
        assert compressed["compression_strategy"] == "summarize"
        assert runtime.summary_provider.calls == 1
        assert compressed["post_message_count"] < compressed["pre_message_count"]
        assert compressed["facts_after"]["goal"] == "完成未发货步骤"
        assert compressed["facts_after"]["params"]["sku"] == "SKU-REAL"
        assert "SKU-FAKE" not in json.dumps(compressed["facts_after"], ensure_ascii=False)
        assert "礼品包装" not in json.dumps(
            compressed["task"]["confirmed_facts"], ensure_ascii=False
        )
        assert compressed["task"]["rejected_claims"]
        assert len(runtime.state["tool_calls"]) == before_calls
        again = _turn(runtime, "clerk", "compress", tenant="t1", user="ua", task_id=task_id)
        assert again["facts_stable"] is True
        assert again["facts_after"] == compressed["facts_after"]
        assert runtime.summary_provider.calls == 2
        continued = _turn(
            runtime, "clerk", "continue_compressed", tenant="t1", user="ua", task_id=task_id
        )
        restated = continued["restatement"]
        assert restated["goal"] == "完成未发货步骤"
        assert restated["params"]["sku"] == "SKU-REAL"
        assert restated["constraints"] == ["不得超卖"]
        assert [item["tool_call_id"] for item in restated["completed_ops"]] == [done_call]
        assert calls["done"] == 1
        assert calls["left"] == 1
        assert continued["task"]["steps"][1]["status"] == "success"
        assert "全部发货已成功" not in json.dumps(
            continued["task"]["confirmed_facts"], ensure_ascii=False
        )
        return _metrics(runtime)


def scenario_a40(tmp_path: Path) -> dict:
    calls = {"done": 0, "wait": 0, "fly": 0}
    with bound_continuity_runtime(tmp_path / "a40.json") as runtime:
        for name in calls:
            runtime.register_tool(name, _counter(calls, name))
        started = _turn(
            runtime,
            "clerk",
            "start",
            tenant="t1",
            user="ua",
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
            step["result_payload"] for step in started["task"]["steps"] if step["step_id"] == "done"
        )
        _turn(
            runtime,
            "clerk",
            "handoff",
            tenant="t1",
            user="ua",
            task_id=task_id,
            target_employee="relay",
            permissions=["wait"],
            idempotency_key="a40-handoff",
        )
        _turn(
            runtime,
            "clerk",
            "seed_inflight",
            tenant="t1",
            user="ua",
            task_id=task_id,
            step_id="fly",
        )
        split = _turn(
            runtime,
            "clerk",
            "split",
            tenant="t1",
            user="ua",
            task_id=task_id,
            children=[
                {"employee_id": "c1", "isolation_marker": "a40-c1"},
                {"employee_id": "c2", "isolation_marker": "a40-c2"},
                {"employee_id": "c3", "isolation_marker": "a40-c3"},
            ],
        )
        children = list(split["task"]["child_task_ids"])
        _turn(
            runtime,
            "clerk",
            "append_turn",
            tenant="t1",
            user="ua",
            task_id=task_id,
            content="暂停前的业务备注",
            fact={
                "confidence": "confirmed",
                "kind": "note",
                "key": "note",
                "value": "暂停前的业务备注",
            },
        )
        paused = _turn(runtime, "clerk", "pause", tenant="t1", user="ua", task_id=task_id)
        assert paused["task"]["status"] == "paused"
        handoff_id = paused["task"]["handoff_ids"][-1]
        message_count = len(runtime.state["tasks"][task_id]["messages"])
        causes = ("client_close", "client_crash", "backend_restart", "scheduler_restart")
        snapshots = []
        for cause in causes:
            recovered = _turn(
                runtime, "clerk", "restart", tenant="t1", user="ua", task_id=task_id, cause=cause
            )
            assert recovered["business_success"] is False
            assert recovered["restart"]["memory_dropped"] is True
            assert recovered["restart"]["cause"] == cause
            snapshots.append(recovered["task"])
        assert calls["done"] == 1
        assert calls["wait"] == 0
        assert calls["fly"] == 0
        restored = snapshots[-1]
        assert restored["task_id"] == task_id
        assert restored["child_task_ids"] == children
        assert all(runtime.state["tasks"][child]["parent_task_id"] == task_id for child in children)
        assert all(runtime.state["tasks"][child]["status"] != "completed" for child in children)
        by_step = {step["step_id"]: step for step in restored["steps"]}
        assert by_step["done"]["status"] == "success"
        assert by_step["done"]["result_payload"] == done_result
        assert by_step["wait"]["status"] == "pending"
        assert by_step["fly"]["status"] == "recovering"
        fly_call = next(
            item for item in runtime.state["tool_calls"].values() if item["step_id"] == "fly"
        )
        assert fly_call["status"] == "recovering"
        assert fly_call["resubmitted"] is False
        assert restored["status"] == "recovering"
        assert restored["handoff_ids"][-1] == handoff_id
        assert len(runtime.state["tasks"][task_id]["messages"]) == message_count
        assert runtime.orphans() == []
        assert snapshots[1:] == snapshots[:-1] or snapshots[1] == snapshots[2] == snapshots[3]
        assert (
            len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in snapshots[1:]})
            == 1
        )
        assert len(runtime.state["restarts"]) == 4
        return _metrics(runtime)


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
def test_checklist_scenario(scenario, tmp_path: Path) -> None:
    metrics = scenario(tmp_path)
    assert metrics["pollution"] == 0
    assert metrics["duplicate_side_effects"] == 0
    assert metrics["orphan_count"] == 0


def test_section_e_quantitative(tmp_path: Path) -> None:
    passed = 0
    pollution = 0
    duplicates = 0
    for scenario in SCENARIOS:
        metrics = scenario(tmp_path / scenario.__name__)
        assert metrics["pollution"] == 0
        assert metrics["duplicate_side_effects"] == 0
        pollution += metrics["pollution"]
        duplicates += metrics["duplicate_side_effects"]
        passed += 1
    assert passed == 10
    assert passed / len(SCENARIOS) == 1.0
    assert pollution == 0
    assert duplicates == 0
