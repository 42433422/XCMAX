"""A definitively failed write must be retryable, not reported as unknown."""

from __future__ import annotations

from types import SimpleNamespace

from app.infrastructure.xiaox import receipts

FAILED_STEP = SimpleNamespace(
    status="failed",
    output={
        "data": {
            "result": {
                "outputs": [
                    {"output": {"ok": False, "error": "非法 Excel 表格名称：'销售明细表'"}}
                ]
            }
        }
    },
)


def child(*, status="blocked", artifacts=(), tool_calls=(), steps=(FAILED_STEP,)):
    return SimpleNamespace(
        status=status, artifacts=list(artifacts), tool_calls=list(tool_calls),
        steps=list(steps), metadata={},
    )


def test_blocked_child_without_effect_is_definite_failure():
    assert receipts._definitely_not_applied(child(), {"status": "failed", "accepted": False}) is True
    assert receipts._failed_step_detail(child()) == "非法 Excel 表格名称：'销售明细表'"


def test_completed_or_artifact_child_is_not_definite_failure():
    verification = {"status": "failed", "accepted": False}
    assert receipts._definitely_not_applied(child(status="completed"), verification) is False
    assert receipts._definitely_not_applied(
        child(artifacts=[SimpleNamespace(id="artifact")]), verification
    ) is False


def test_successful_tool_call_is_not_definite_failure():
    calls = [SimpleNamespace(output={"success": True})]
    assert receipts._definitely_not_applied(
        child(tool_calls=calls), {"status": "failed", "accepted": False}
    ) is False
