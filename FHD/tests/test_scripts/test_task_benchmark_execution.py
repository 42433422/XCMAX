"""A clarification must suspend all subsequent business effects in a trial."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("prefix", [[], [("products", "query")]])
def test_unanswered_clarification_never_executes_later_writes(monkeypatch, prefix):
    from app.services import tools_workflow_registered

    calls = []

    def execute(tool, action, params):
        calls.append((tool, action))
        return {"success": True}

    monkeypatch.setattr(tools_workflow_registered, "execute_registered_workflow_tool", execute)
    runner = runpy.run_path(
        str(Path(__file__).parents[1] / "benchmarks" / "task_success_runner.py")
    )
    actions = [*prefix, ("clarify", "ask"), ("business_db", "write")]
    nodes = [SimpleNamespace(tool_id=tool, action=action, params={}) for tool, action in actions]
    success, reason, executed = runner["_execute_nodes"](nodes)
    assert success and not reason
    assert calls == prefix
    assert executed[-1] == {"tool_id": "clarify", "action": "ask", "waiting_user": True}
    assert len(executed) == len(prefix) + 1
