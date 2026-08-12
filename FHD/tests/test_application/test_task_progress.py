from __future__ import annotations

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.task_models import AgentTask, task_from_run
from app.application.agent_orchestrator.task_progress import task_progress_snapshot


def _step(name: str, status: str) -> AgentStep:
    return AgentStep(
        node_id=name,
        tool_id="customers",
        action="query",
        description=f"步骤 {name}",
        status=status,  # type: ignore[arg-type]
    )


def test_progress_is_derived_from_durable_steps_and_current_stage() -> None:
    run = AgentRun(
        user_id="owner",
        message="统一进度",
        status="running",
        steps=[_step("one", "completed"), _step("two", "running"), _step("three", "pending")],
    )
    run.metadata["task_context"] = {"attempt": 2}

    progress = task_progress_snapshot(run)

    assert progress == {
        "percent": 33,
        "completed_units": 1,
        "settled_units": 1,
        "total_units": 3,
        "current_unit": 2,
        "stage": "执行中",
        "detail": "步骤 two",
        "status": "running",
        "attempt": 2,
        "indeterminate": False,
        "basis": "steps",
        "updated_at": run.updated_at,
    }


def test_progress_preserves_control_stage_and_never_marks_cancelled_as_complete() -> None:
    run = AgentRun(
        user_id="owner",
        message="取消任务",
        status="cancelled",
        steps=[_step("one", "completed"), _step("two", "skipped")],
    )
    run.metadata["control_request"] = {"action": "cancel", "status": "requested"}

    progress = task_progress_snapshot(run)

    assert progress["percent"] == 99
    assert progress["completed_units"] == 1
    assert progress["settled_units"] == 2
    assert progress["stage"] == "正在请求取消"


def test_completed_and_legacy_tasks_have_complete_progress_contract() -> None:
    completed = AgentRun(user_id="owner", message="完成", status="completed")
    completed_progress = task_progress_snapshot(completed)
    assert completed_progress["percent"] == 100
    assert completed_progress["basis"] == "status"
    assert completed_progress["indeterminate"] is False

    legacy = AgentTask(task_id="legacy", user_id="owner", title="旧任务", status="running")
    legacy_progress = legacy.to_dict()["progress"]
    assert legacy_progress["percent"] == 0
    assert legacy_progress["stage"] == "执行中"
    assert legacy_progress["indeterminate"] is True

    inconsistent = AgentRun(
        user_id="owner",
        message="历史不一致任务",
        status="completed",
        steps=[_step("one", "completed"), _step("two", "running")],
    )
    assert task_progress_snapshot(inconsistent)["percent"] == 50


def test_task_from_run_persists_progress_for_lightweight_stream_snapshots() -> None:
    run = AgentRun(
        user_id="owner",
        message="流式进度",
        status="running",
        steps=[_step("one", "completed"), _step("two", "pending")],
    )
    run.metadata["task_context"] = {"task_id": "task-progress", "attempt": 1}

    task = task_from_run(run)

    assert task.metadata["progress"]["percent"] == 50
    assert task.to_dict()["progress"]["detail"] == "步骤 two"
