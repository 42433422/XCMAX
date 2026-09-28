"""WO-18443017efd5 复现件（真实执行链）：受理必须先于 normal-slot 快路径。

客户原问题：缺陷上报只收到普通业务答复，拿不到工单编号。

真实链路（桌面端 /api/ai/chat/stream）：
  compat_routes.ai_unified_chat_stream
    → planner_compat_service.compat_chat_stream_async
      → planner_compat_service_part03.compat_chat_stream_async

part03 里的 try_normal_slot_read_payload 会在任何受理之前直接返回业务答复
（缺陷原话被当成 intent=purchase_query → 「当前没有采购订单。」）。本用例锁定：
命中缺陷上报时，必须先给出受理回执，绝不能被快路径吃掉。
"""

from __future__ import annotations

import asyncio
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


@pytest.mark.parametrize("guide", [{"state": "ROUTED", "work_order_id": "WO-fixed-path",
                                    "owner_ticket_no": "CI-fixed-path"}])
def test_intake_precedes_normal_slot_fast_path(monkeypatch, guide):
    import importlib

    part03 = importlib.import_module(PART03)
    stream = importlib.import_module(STREAM)
    dispatch = importlib.import_module(DISPATCH)

    # 快路径会返回业务答复——它绝不能在受理之前被采用
    monkeypatch.setattr(
        dispatch, "try_normal_slot_read_payload",
        lambda message, request=None: {"response": "当前没有采购订单。",
                                       "data": {"intent": "purchase_query"}},
        raising=False,
    )
    # 受理返回一条带工单号的真回执
    async def _fake_intake_async(*a, **k):
        return dict(guide)

    monkeypatch.setattr(stream, "_classify_and_submit_client_issue_async", _fake_intake_async)

    body = NS(message=DEFECT_MESSAGE, context={}, user_id="1", source="test", system_prompt="x")
    request = NS(
        state=NS(tutorial_active=False),
        headers={},
        cookies={},
        url=NS(path="/api/ai/chat/stream"),
        method="POST",
    )
    chunks = _collect(part03.compat_chat_stream_async(request, body, ai_tier="basic"))
    text = "".join(
        c.decode("utf-8", "ignore") if isinstance(c, (bytes, bytearray)) else str(c)
        for c in chunks
    )

    assert "当前没有采购订单。" not in text, "缺陷上报被 normal-slot 快路径吃掉"
    assert "WO-fixed-path" in text, "必须回执 Work Order 编号"