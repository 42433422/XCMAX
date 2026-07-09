"""Lazy access to ``chat_trace`` shim for monkeypatch-compatible lookups."""

from __future__ import annotations

from typing import Any


def module() -> Any:
    from app.application.agent_orchestrator import chat_trace as chat_trace_module

    return chat_trace_module
