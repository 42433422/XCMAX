"""M13 回归：AI 执行链必须能从日志侧区分分发路径，并按 run_id 串起工具调用与产物。

修复前本文件的三条断言全部失败：槽位路径命中/未命中都不写任何日志，
工具调用与产物也只在响应体 legacy_tool_records 中回传、不落日志。
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch

from app.application.agent_orchestrator import AgentArtifact, AgentRun
from app.application.agent_orchestrator.chat_trace import (
    _append_artifacts_to_run,
    _append_legacy_tool_records_to_run,
)
from app.application.normal_chat_dispatch import try_normal_slot_read_payload
from app.application.planner_compat_service_part03 import compat_chat_stream_async

FACADE = "app.application.planner_compat_service"


def _drain(agen) -> list[bytes]:
    async def _run() -> list[bytes]:
        return [chunk async for chunk in agen]

    return asyncio.run(_run())


def test_normal_slot_match_is_logged(caplog) -> None:
    caplog.set_level(logging.INFO)
    with (
        patch(
            "app.application.normal_chat_dispatch.route_normal_mode_message",
            return_value={"intent": "customers_query", "slots": {}},
        ),
        patch(
            "app.application.normal_chat_dispatch.build_customers_query_response_dict",
            return_value={
                "success": True,
                "response": "当前共有 2 位客户",
                "data": {"intent": "customers_query"},
                "agent_tool_dispatch": True,
            },
        ),
    ):
        payload = try_normal_slot_read_payload("有哪些客户？")

    assert payload is not None
    assert "dispatch_path=normal_slot" in caplog.text
    assert "intent=customers_query matched=True" in caplog.text


def test_normal_slot_unmatched_intent_is_logged(caplog) -> None:
    caplog.set_level(logging.INFO)
    with patch(
        "app.application.normal_chat_dispatch.route_normal_mode_message",
        return_value={"intent": "no_such_intent", "slots": {}},
    ):
        assert try_normal_slot_read_payload("随便说点什么") is None

    assert "dispatch_path=normal_slot" in caplog.text
    assert "intent=no_such_intent matched=False" in caplog.text


def test_compat_slot_logs_run_id_and_intent(caplog) -> None:
    caplog.set_level(logging.INFO)
    body = SimpleNamespace(
        message="有哪些客户？",
        context={},
        system_prompt="keep",
        user_id="u1",
        source="desktop",
    )
    request = SimpleNamespace()
    with (
        patch(
            "app.application.normal_chat_dispatch.try_normal_slot_read_payload",
            return_value={
                "response": "当前共有 2 位客户",
                "data": {"intent": "customers_query"},
                "agent_tool_dispatch": True,
            },
        ),
        patch(
            f"{FACADE}._merge_runtime_context_with_message_paths",
            return_value=({}, None),
        ),
        patch(f"{FACADE}._runtime_context_with_authenticated_actor", return_value={}),
        patch(f"{FACADE}.attach_chat_trace_run", return_value={"run_id": "run-obs-1"}),
    ):
        chunks = _drain(compat_chat_stream_async(request, body))

    assert chunks
    assert "dispatch_path=compat_slot" in caplog.text
    assert "intent=customers_query" in caplog.text
    assert "run_id=run-obs-1" in caplog.text


def test_llm_planner_path_is_distinguishable(caplog) -> None:
    caplog.set_level(logging.INFO)
    body = SimpleNamespace(message="帮我看看这个月的情况", context={}, system_prompt="keep")
    request = SimpleNamespace()

    async def _fake_stream(*args, **kwargs):
        if False:  # pragma: no cover - 生成器占位
            yield b""

    with (
        patch(
            "app.application.normal_chat_dispatch.try_normal_slot_read_payload",
            return_value=None,
        ),
        patch(f"{FACADE}.resolve_ai_tier", return_value="standard"),
        patch(f"{FACADE}._xcagi_planner_stream_bytes_async", new=_fake_stream),
    ):
        chunks = _drain(compat_chat_stream_async(request, body))

    assert chunks == []
    assert "dispatch_path=llm_planner" in caplog.text
    assert "dispatch_path=compat_slot" not in caplog.text


def test_tool_call_and_artifact_are_logged(caplog) -> None:
    caplog.set_level(logging.INFO)
    run = AgentRun(user_id="u1", message="生成送货单")
    record = {
        "tool_id": "customers.query",
        "action": "query",
        "output": {"success": True},
    }
    artifact = AgentArtifact(
        artifact_type="delivery_note",
        name="送货单.xlsx",
        uri="/tmp/delivery-note.xlsx",
    )
    with patch(
        "app.application.agent_orchestrator.chat_trace.ingest_artifact_to_dataset",
        return_value=None,
    ):
        _append_legacy_tool_records_to_run(run, [record])
        _append_artifacts_to_run(run, [artifact])

    assert f"agent tool call: run_id={run.run_id}" in caplog.text
    assert "tool_id=customers.query" in caplog.text
    assert "action=query status=completed" in caplog.text
    assert f"agent artifact recorded: run_id={run.run_id}" in caplog.text
    assert f"artifact_id={artifact.artifact_id}" in caplog.text
