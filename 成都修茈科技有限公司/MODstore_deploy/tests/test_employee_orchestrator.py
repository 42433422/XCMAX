"""员工编排入口 plan_and_dispatch。"""

from __future__ import annotations


def test_plan_and_dispatch_delegates_to_duty_graph(monkeypatch):
    captured: dict = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "id": 42, "nodes": []}

    monkeypatch.setattr(
        "modstore_server.admin_duty_graph_api.execute_duty_graph_programmatic",
        fake_execute,
    )
    from modstore_server.employee_orchestrator import plan_and_dispatch

    out = plan_and_dispatch(
        "hello task",
        {"project_root": "/tmp"},
        created_by_user_id=7,
        target_employee_id="daily-orchestrator",
        allow_high_risk_real_run=True,
        bench_llm_override=("openai", "gpt-4"),
    )
    assert out.get("ok") is True
    assert captured["target_employee_id"] == "daily-orchestrator"
    assert captured["created_by_user_id"] == 7
    assert captured["bench_llm_override"] == ("openai", "gpt-4")


def test_dispatch_subtasks_blocks_downstream_when_upstream_handler_failed(monkeypatch):
    calls: list[str] = []

    def fake_execute(employee_id, task_brief, input_data, **kwargs):
        calls.append(employee_id)
        return {"handler_failed": True, "error": "boom"}

    monkeypatch.setattr(
        "modstore_server.employee_executor.execute_employee_task", fake_execute
    )
    monkeypatch.setattr(
        "modstore_server.employee_orchestrator._record_dispatch_metric", lambda **_: None
    )
    from modstore_server.employee_orchestrator import dispatch_subtasks
    from modstore_server.task_router import SubTask

    out = dispatch_subtasks(
        [
            SubTask(employee_id="a", task_brief="first"),
            SubTask(employee_id="b", task_brief="second", depends_on=["a"]),
        ],
        created_by_user_id=1,
    )

    assert calls == ["a"]
    assert out["ok"] is False
    results = {r["employee_id"]: r for r in out["results"]}
    assert results["a"]["status"] == "failed"
    assert "handler_failed" in results["a"]["error"]
    assert results["b"]["status"] == "skipped"
    assert "上游未成功" in results["b"]["error"]
