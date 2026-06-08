"""员工编排入口 plan_and_dispatch。"""

from __future__ import annotations

import types


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
