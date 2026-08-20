# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.chat_trace")


def _iter_memory_payloads(
    payload: dict[str, _facade().Any],
) -> _facade().Iterator[dict[str, _facade().Any]]:
    nested_keys = ("user_memory_rag", "userMemoryRag", "memory_reference", "memoryReference")
    for item in _facade()._iter_payload_dicts(payload):
        if _facade()._has_user_memory_marker(item):
            yield item
        for key in nested_keys:
            candidate = item.get(key)
            if isinstance(candidate, dict):
                yield candidate


def _first_list_value(item: dict[str, _facade().Any], keys: tuple[str, ...]) -> list[_facade().Any]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            return value
    return []
