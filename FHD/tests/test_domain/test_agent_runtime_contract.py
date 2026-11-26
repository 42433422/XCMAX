from __future__ import annotations

import copy

from app.application.agent_orchestrator.run_models import AgentRun
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    goal_evidence_snapshot,
    validate_goal_review,
)


def _batch_write_row(child: str, phase_count: int) -> dict:
    return {
        "tool_id": "employee",
        "action": "execute",
        "child_run_id": child,
        "child_task_id": f"task-{child}",
        "state": "completed",
        "read_only": False,
        "params": {
            "employee_id": "excel-template-write-employee",
            "input": {"plan": {"phases": [{"phase": f"p{i}"} for i in range(phase_count)]}},
        },
        "receipt": {
            "status": "completed",
            "success": True,
            "verified": True,
            "run_id": child,
            "task_id": f"task-{child}",
        },
    }


def _write_goal(goal_id: str, source: str, evidence_id: str) -> dict:
    return {
        "goal_id": goal_id,
        "source_id": "request",
        "source": source,
        "kind": "write",
        "status": "satisfied",
        "evidence_ids": [evidence_id],
        "reason": "同一批量动作的已核验 phase",
    }


def test_batch_write_receipt_backs_as_many_atomic_goals_as_its_phases():
    message = "写入日期，写入金额，设置金额公式"
    run = AgentRun(user_id="71", message=message, run_id="run-batch")
    contract = build_goal_contract(run)
    snapshot = goal_evidence_snapshot(contract, [_batch_write_row("run_child", 3)], "已完成")
    raw = {
        "goals": [
            _write_goal(f"g{index}", text, "run_child")
            for index, text in enumerate(["写入日期", "写入金额", "设置金额公式"])
        ],
        "violations": [],
        "uncovered_sources": [],
        "feedback": "",
    }
    reviewed, errors = validate_goal_review(raw, contract, snapshot, "已完成")
    assert errors == []
    assert all(goal["status"] == "satisfied" for goal in reviewed["goals"])

    over = copy.deepcopy(raw)
    over["goals"].append(_write_goal("g-over", "写入日期", "run_child"))
    _, over_errors = validate_goal_review(over, contract, snapshot, "已完成")
    assert any("重用了" in item for item in over_errors)


def test_single_phase_write_receipt_still_cannot_back_two_goals():
    message = "写入日期，写入金额"
    run = AgentRun(user_id="71", message=message, run_id="run-single")
    contract = build_goal_contract(run)
    snapshot = goal_evidence_snapshot(contract, [_batch_write_row("run_child", 1)], "已完成")
    raw = {
        "goals": [
            _write_goal("g1", "写入日期", "run_child"),
            _write_goal("g2", "写入金额", "run_child"),
        ],
        "violations": [],
        "uncovered_sources": [],
        "feedback": "",
    }
    _, errors = validate_goal_review(raw, contract, snapshot, "已完成")
    assert any("重用了" in item for item in errors)
