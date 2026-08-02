"""Compatibility helpers for enriching existing chat stream events."""

from __future__ import annotations

from typing import Any, Callable


def attach_first_run_receipt(
    event: dict[str, Any],
    run_id: str | None,
    already_sent: bool,
    attach: Callable[[dict[str, Any], str | None], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Attach a durable run id to the first normal token without a new SSE event."""
    if run_id and not already_sent:
        return attach(event, run_id), True
    return event, already_sent
