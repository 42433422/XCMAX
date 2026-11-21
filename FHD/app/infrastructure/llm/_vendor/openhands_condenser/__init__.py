"""OpenHands Condenser boundary/token components adapted for XCMAX messages.

MIT, Copyright (c) 2026 OpenHands contributors. See LICENSE and PROVENANCE.json.
Only event decoding and token counting are adapted; no OpenHands runtime state.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


class ManipulationIndices(set[int]):
    """Indices where insertion/deletion does not split an atomic event group."""

    def find_next(self, threshold: int) -> int:
        valid_indices = {idx for idx in self if idx >= threshold}
        if not valid_indices:
            raise ValueError(f"No manipulation index found >= {threshold}.")
        return min(valid_indices)

    @staticmethod
    def complete(events: Sequence[Any]) -> ManipulationIndices:
        manipulation_indices = ManipulationIndices()
        manipulation_indices.update(range(0, len(events)))
        manipulation_indices.add(len(events))
        return manipulation_indices


def tool_call_manipulation_indices(events: Sequence[dict]) -> ManipulationIndices:
    """OpenHands ToolCallMatchingProperty with OpenAI message decoding.

    A Chat Completions assistant message may contain several ActionEvents.
    Unanswered calls protect every following boundary, including the end.
    """
    manipulation_indices = ManipulationIndices.complete(events)
    pending_tool_call_ids: set[str] = set()
    for index, event in enumerate(events):
        if event.get("role") == "assistant":
            pending_tool_call_ids.update(
                str(call.get("id") or f"missing-tool-id-{index}")
                for call in event.get("tool_calls") or []
            )
            legacy = event.get("function_call")
            if legacy:
                pending_tool_call_ids.add("function:" + str(legacy.get("name", "")))
        elif event.get("role") == "tool":
            pending_tool_call_ids.discard(str(event.get("tool_call_id") or ""))
        elif event.get("role") == "function":
            pending_tool_call_ids.discard("function:" + str(event.get("name", "")))
        if pending_tool_call_ids:
            manipulation_indices.remove(index + 1)
    return manipulation_indices


def get_shortest_prefix_above_token_count(
    events: Sequence[Any],
    token_counter: Callable[[list[Any]], int],
    token_count: int,
    base_events: Sequence[Any] | None = None,
) -> int:
    """OpenHands Condenser binary search, with the existing provider counter."""
    if not events:
        return 0
    base_events = base_events or []
    base_tokens = token_counter(list(base_events)) if base_events else 0
    total_tokens = token_counter([*base_events, *events]) - base_tokens
    if total_tokens <= token_count:
        return len(events)
    left, right = 1, len(events)
    while left < right:
        mid = (left + right) // 2
        prefix_tokens = token_counter([*base_events, *events[:mid]]) - base_tokens
        if prefix_tokens > token_count:
            right = mid
        else:
            left = mid + 1
    return left
