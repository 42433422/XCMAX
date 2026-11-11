"""Confirmed workflow turns must survive the 20s first-event watch."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes import xcagi_compat_chat_helpers as ch


def _payloads(chunks: list[bytes]) -> list[dict]:
    return [json.loads(chunk.decode("utf-8")[len("data: ") :].strip()) for chunk in chunks]


@pytest.mark.asyncio
async def test_silence_before_the_first_event_still_times_out(monkeypatch):
    monkeypatch.setattr(ch, "_xcagi_stream_first_token_timeout_seconds", lambda: 0.2)
    monkeypatch.setattr(ch, "_xcagi_chat_timeout_seconds", lambda: 2.0)

    def silent(*_args, **_kwargs):
        time.sleep(0.45)
        yield ch._sse_event_line({"type": "done", "result": {"success": True, "response": "太晚"}})

    monkeypatch.setattr(ch, "_xcagi_planner_stream_bytes", silent)
    chunks = [
        chunk
        async for chunk in ch._xcagi_planner_stream_bytes_async(
            MagicMock(), ch.XcagiCompatChatBody(message="hello"), ai_tier="standard"
        )
    ]
    events = _payloads(chunks)
    assert events[-1]["type"] == "error"
    assert events[-1]["execution_outcome"] == "unknown"


@pytest.mark.asyncio
async def test_running_progress_extends_the_chat_budget(monkeypatch):
    monkeypatch.setattr(ch, "_xcagi_stream_first_token_timeout_seconds", lambda: 0.2)
    monkeypatch.setattr(ch, "_xcagi_chat_timeout_seconds", lambda: 0.3)

    def working(*_args, **_kwargs):
        yield ch._sse_event_line(
            {"type": "tool_progress", "phase": "running", "label": "正在执行已确认的任务"}
        )
        time.sleep(0.22)
        yield ch._sse_event_line(
            {"type": "tool_progress", "phase": "running", "label": "正在执行已确认的任务"}
        )
        time.sleep(0.22)
        yield ch._sse_event_line({"type": "done", "result": {"success": True, "response": "完成"}})

    monkeypatch.setattr(ch, "_xcagi_planner_stream_bytes", working)
    chunks = [
        chunk
        async for chunk in ch._xcagi_planner_stream_bytes_async(
            MagicMock(), ch.XcagiCompatChatBody(message="确认"), ai_tier="standard"
        )
    ]
    events = _payloads(chunks)
    assert events[-1]["type"] == "done"
    assert events[-1]["result"]["response"] == "完成"


@pytest.mark.asyncio
async def test_confirm_reports_progress_before_slow_knowledge_init(monkeypatch):
    """office-docking rebuild confirmation used to die at the 20s first-event cap."""
    monkeypatch.setattr(ch, "_xcagi_stream_first_token_timeout_seconds", lambda: 0.2)
    monkeypatch.setattr(ch, "_xcagi_chat_timeout_seconds", lambda: 2.0)
    order: list[str] = []

    def slow_evidence(_request, ctx, _message):
        order.append("evidence")
        time.sleep(0.45)
        return dict(ctx or {})

    service = MagicMock()

    def process_chat(**_kwargs):
        order.append("chat")
        return {"success": True, "response": "索引重建已开始", "data": {"action": "workflow_started"}}

    service.process_chat.side_effect = process_chat
    request = MagicMock(headers={}, cookies={})
    body = ch.XcagiCompatChatBody(
        message="确认", user_id="web_pro_session", source="normal", mode="online"
    )
    with (
        patch("app.application.get_ai_chat_app_service", return_value=service),
        patch("app.application.ai_chat.chat_evidence.prepare_chat_evidence", slow_evidence),
        patch.object(
            ch,
            "_runtime_context_with_authenticated_actor",
            side_effect=lambda _r, c: {**dict(c or {}), "local_user_id": 17},
        ),
        patch.object(ch, "runtime_context_with_tier", side_effect=lambda c, _t: c),
        patch.object(ch, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(ch, "_message_requires_db_read_token", return_value=False),
        patch.object(ch, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(ch, "_ensure_vector_index_if_needed", return_value=None),
    ):
        chunks = [
            chunk
            async for chunk in ch._xcagi_planner_stream_bytes_async(
                request, body, ai_tier="standard"
            )
        ]
    events = _payloads(chunks)
    assert events[0]["type"] == "tool_progress"
    assert events[0]["phase"] == "running"
    assert order == ["evidence", "chat"]
    assert events[-1]["type"] == "done"
    assert events[-1]["result"]["response"] == "索引重建已开始"
    assert not any(event.get("type") == "error" for event in events)
