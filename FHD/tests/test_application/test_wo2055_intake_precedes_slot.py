"""产品上报先于业务快路径，并覆盖工单010069中的实测原话。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace as NS

import pytest

PART03 = "app.application.planner_compat_service_part03"
STREAM = "app.fastapi_routes.xcagi_compat_chat_stream"
DISPATCH = "app.application.normal_chat_dispatch"

DEFECT_MESSAGE = "保存采购订单报错，点保存没有任何反应。期望：保存成功。实际：报服务器内部错误。"


def _collect(agen) -> list[dict]:
    async def _run():
        return [chunk async for chunk in agen]

    return asyncio.run(_run())


@pytest.mark.parametrize(
    "message",
    [
        DEFECT_MESSAGE,
        "我要提交产品问题工单，问题名称：管理端基础设施展示不直观，请返回工单编号。",
        "我不是查询生产任务，请使用产品问题上报功能，处理本问题，没有能力请如实说明。",
    ],
)
@pytest.mark.parametrize(
    "guide",
    [
        {"state": "ROUTED", "work_order_id": "WO-fixed-path", "owner_ticket_no": "CI-fixed-path"},
        {"state": "OWNER_ROUTE_UNAVAILABLE", "work_order_id": "WO-fixed-path"},
        {"state": "NEEDS_MORE_EVIDENCE"},
    ],
)
def test_intake_precedes_normal_slot_fast_path(monkeypatch, guide, message):
    import importlib

    part03 = importlib.import_module(PART03)
    stream = importlib.import_module(STREAM)
    dispatch = importlib.import_module(DISPATCH)

    monkeypatch.setattr(
        dispatch,
        "try_normal_slot_read_payload",
        lambda message, **kwargs: {
            "response": "当前没有采购订单。",
            "data": {"intent": "purchase_query"},
        },
        raising=False,
    )

    async def _fake_intake_async(*a, **k):
        return dict(guide)

    monkeypatch.setattr(stream, "_classify_and_submit_client_issue_async", _fake_intake_async)

    body = NS(message=message, context={}, user_id="1", source="test", system_prompt="x")
    request = NS(
        state=NS(tutorial_active=False),
        headers={},
        cookies={},
        url=NS(path="/api/ai/chat/stream"),
        method="POST",
    )
    chunks = _collect(part03.compat_chat_stream_async(request, body, ai_tier="basic"))
    text = "".join(
        c.decode("utf-8", "ignore") if isinstance(c, (bytes, bytearray)) else str(c) for c in chunks
    )

    assert "当前没有采购订单。" not in text, "缺陷上报被 normal-slot 快路径吃掉"
    if guide["state"] == "NEEDS_MORE_EVIDENCE":
        assert "期望" in text and "实际" in text
    elif guide["state"] == "OWNER_ROUTE_UNAVAILABLE":
        assert "暂时无法确认受理结果" in text
        assert "WO-fixed-path" not in text
    else:
        assert "WO-fixed-path" in text
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    result = next(event["result"] for event in events if event["type"] == "done")
    assert result["success"] is (guide["state"] != "OWNER_ROUTE_UNAVAILABLE")
    if guide["state"] == "OWNER_ROUTE_UNAVAILABLE":
        assert "暂时无法确认受理结果" in result["message"]
        from app.application.agent_orchestrator import AgentOrchestrator

        run = AgentOrchestrator().get_run(result["run_id"])
        assert run is not None and run.status == "failed"
