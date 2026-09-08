from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.ai_chat_app_service_dynamic_workflow_pending_mixin import (
    _DynamicWorkflowPendingResumeMixin,
)


@pytest.mark.parametrize(
    "item,expected",
    [
        (
            {
                "reason": "missing_required",
                "field": "name_or_model",
                "missing_fields": ["name_or_model"],
                "question": "请提供产品名称或型号。",
            },
            "请提供产品名称或型号。",
        ),
        ({"reason": "missing_required"}, "请补充所需字段后再继续。"),
        (
            {"reason": "ambiguous_target", "candidates": [{"id": 1}]},
            "仍无法唯一确定操作目标，请回复候选序号或唯一 ID。",
        ),
    ],
)
def test_retry_keeps_original_clarification_context(item, expected):
    pending = {"kind": "clarification", "clarification": item}
    service = SimpleNamespace(
        _pending_workflows={"u": pending}, _continue_after_clarification=Mock(return_value=None)
    )
    handled, response = _DynamicWorkflowPendingResumeMixin._resume_pending_dynamic_workflow(
        service, "u", "?", "?"
    )
    assert handled and response["response"] == expected
    assert response["data"]["text"] == expected
    assert response["data"]["data"]["field"] == item.get("field")
    assert response["data"]["data"]["candidates"] == item.get("candidates", [])
    assert service._pending_workflows["u"] is pending
