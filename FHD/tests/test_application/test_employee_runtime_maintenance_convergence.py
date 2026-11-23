"""Regression checks for converged employee bridge and truthful degradation."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

from app.application.employee_runtime.chat_results import (
    build_collaboration_context_result,
    build_interactive_chat_fallback_result,
)
from app.application.employee_runtime.executor import _run_maybe_async


def _pack():
    return {"pack_id": "fixture", "version": "1.0"}


def test_chat_model_outage_is_failure_not_success():
    result = build_interactive_chat_fallback_result(
        "fixture",
        _pack(),
        {},
        "question",
        ["llm_md"],
        {"error": "model unavailable", "error_code": "model_unavailable"},
        0.0,
    )
    assert result["success"] is False
    assert result["error_code"] == "model_unavailable"
    assert result["result"]["outputs"][0]["ok"] is False
    assert result["degraded"] is True


def test_collaboration_degradation_is_not_successful_execution():
    failed = build_collaboration_context_result(
        "fixture",
        _pack(),
        {},
        "question",
        ["llm_md"],
        {"error": "model unavailable"},
        0.0,
        SimpleNamespace(has_content=False),
        degraded=True,
    )
    assert failed["success"] is False
    assert failed["result"]["outputs"][0]["ok"] is False
    healthy = build_collaboration_context_result(
        "fixture",
        _pack(),
        {},
        "question",
        ["llm_md"],
        {"reasoning": "ready"},
        0.0,
        SimpleNamespace(has_content=False),
    )
    assert healthy["success"] is True
    assert healthy["result"]["outputs"][0]["ok"] is True


def test_maybe_async_uses_shared_context_preserving_bridge():
    marker = ContextVar("tenant_test_marker", default="missing")

    async def operation():
        await asyncio.sleep(0)
        return marker.get()

    async def within_loop():
        token = marker.set("tenant-42")
        try:
            return _run_maybe_async(lambda: operation())
        finally:
            marker.reset(token)

    assert asyncio.run(within_loop()) == "tenant-42"
    assert _run_maybe_async(lambda value: value + 1, 41) == 42
