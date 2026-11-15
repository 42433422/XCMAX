"""审批执行结果的边界判定：仍在执行 / 结果未知都不算确定失败。"""

from types import SimpleNamespace

from app.application.approval_workspace.workflow_bridge import _unknown_tool_outcome


def _run(*outputs):
    return SimpleNamespace(steps=[SimpleNamespace(output=output) for output in outputs])


def test_unknown_outcome_detected_from_reconciliation_flag():
    assert _unknown_tool_outcome(_run({"outcome": "unknown", "reconciliation_required": True}))


def test_plain_failure_is_not_treated_as_unknown():
    assert not _unknown_tool_outcome(_run({"success": False, "error_code": "x"}))
    assert not _unknown_tool_outcome(_run(None))
    assert not _unknown_tool_outcome(SimpleNamespace(steps=[]))
