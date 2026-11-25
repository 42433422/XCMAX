"""扩展覆盖：ai_chat_app_service 缺失分支（静态方法 + process_chat 错误路径）。"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.utils.operational_errors import RECOVERABLE_ERRORS
from tests.fixtures.planner_model import goal_review_response
from tests.test_application.ai_chat_test_helpers import (
    _make_svc,
)

# helpers
# process_chat — neuro_notify 异常不中断流程
# _customer_hint_from_preview_grid
# _default_purchase_unit_for_import
# _guess_default_purchase_unit
# _resolve_force_header_row_1based
# _resolve_sheet_name_for_reimport
# _try_structured_reload_records
from tests.test_application.test_owned_planner_attachments import owned as owned


@pytest.mark.parametrize("event", ["received", "completed"])
def test_neuro_failure_does_not_replace_fixed_executor(event):
    from app.infrastructure.xiaox.policy import RuntimeSettings

    svc = _make_svc()
    with (
        patch(
            f"app.neuro_bus.application_neuro_bridge.neuro_notify_chat_{event}",
            side_effect=RuntimeError("bus down"),
        ),
        patch(
            "app.application.agent_runtime.gateway.runtime_settings", return_value=RuntimeSettings()
        ),
        patch(
            "app.application.agent_runtime.gateway.run_runtime_task",
            return_value={
                "ok": True,
                "run_id": "parent",
                "exit_status": "reply_completed",
                "output": "已读取",
            },
        ) as execute,
        patch.object(svc, "_persist_chat_turn"),
        patch.object(svc, "_persist_recallable_chat_turn"),
    ):
        result = svc.process_chat("u1", "说明工作方式")
    assert result["response"] == "已读取"
    assert result["runtime"] == "xiaox"
    execute.assert_called_once()
    assert execute.call_args.kwargs["completion_mode"] == "auto"
    assert not hasattr(svc, "workflow_planner")


@pytest.mark.parametrize("sheet_name", [None, "Sheet2"])
def test_registered_upload_reaches_runtime_goal_without_implicit_import(owned, sheet_name):
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_runtime.xiaox_runtime import _input_text
    from app.application.agent_runtime.goal_admission import prepare_runtime_goal

    context, _ = owned
    context = {**context, "file_context": {"sheet_name": sheet_name}}
    run = AgentRun(
        user_id=str(context["user_id"]), message="说明附件", metadata={"runtime_context": context}
    )
    goal = prepare_runtime_goal(SimpleNamespace(run=run, context=context))
    assert "paint" in _input_text(run.message, None, None, goal=goal.contract)
    assert goal.artifacts[0]["uri"] == ""
    assert goal.artifacts[0]["metadata"]["skip_dataset_ingest"] is True
    assert not run.tool_calls
