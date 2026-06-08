"""sandbox-tester / workflow_sandbox 失败路径与信号。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_invalid_workflow_sandbox_report_shape():
    from modstore_server.craft_failure_signals import invalid_workflow_sandbox_report

    report = invalid_workflow_sandbox_report(None)
    assert report["ok"] is False
    assert report["status"] == "fail"
    assert report["summary"] == "输入 workflow_id 无效"
    assert report["structure_validation"]["status"] == "fail"
    assert report["errors"]


def test_resolve_craft_step_id_accepts_employee_id():
    from modstore_server.craft_failure_signals import resolve_craft_step_id

    step, emp = resolve_craft_step_id("sandbox-tester")
    assert step == "workflow_sandbox"
    assert emp == "sandbox-tester"


@pytest.mark.asyncio
async def test_craft_workflow_sandbox_rejects_zero_workflow_id():
    from modstore_server.craft_steps import _craft_workflow_sandbox

    with patch("modstore_server.craft_failure_signals.emit_craft_step_failure") as emit:
        out = await _craft_workflow_sandbox(
            workflow_id=0,
            brief="t",
            user_id=1,
            db=MagicMock(),
        )
    assert out["report"]["status"] == "fail"
    assert out["summary"] == "输入 workflow_id 无效"
    emit.assert_called_once()


def test_dispatch_craft_step_unknown_returns_fail_dict():
    import asyncio

    from modstore_server.craft_executor import dispatch_craft_step

    with patch("modstore_server.craft_failure_signals.emit_craft_step_failure"):
        out = asyncio.run(dispatch_craft_step("not-a-real-step", user_id=0))
    assert isinstance(out, dict)
    assert out.get("ok") is False
    assert out.get("summary")


def test_emit_craft_step_failure_publishes_on_error():
    from modstore_server.craft_failure_signals import emit_craft_step_failure

    with patch("modstore_server.craft_executor._record_craft_execution") as rec:
        with patch("modstore_server.incident_bus.publish") as pub:
            with patch(
                "modstore_server.all_hands_report._load_yuangon_employee_meta",
                return_value={"sla": {"escalate_to_human": True}},
            ):
                emit_craft_step_failure(
                    step_id="workflow_sandbox",
                    error="测试失败",
                    user_id=1,
                )
    rec.assert_called_once()
    on_error_calls = [c for c in pub.call_args_list if c.args[0] == "on_error"]
    assert len(on_error_calls) == 1
    args, kwargs = on_error_calls[0]
    assert kwargs.get("source") == "sandbox-tester"
    payload = args[1]
    assert payload.get("escalate_to_human") is True
    assert "测试失败" in payload.get("summary", "")
