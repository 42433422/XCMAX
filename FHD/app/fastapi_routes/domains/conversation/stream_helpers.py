"""SSE encoding and compatibility exports for the single conversation stream."""

from __future__ import annotations

import json

from app.application.planner_display_markers import (
    _thinking_steps_from_planner_stream_text as _thinking_steps_from_planner_stream_text,
)
from app.application.planner_display_markers import (
    strip_planner_stream_markers as strip_planner_stream_markers,
)
from app.fastapi_routes.xcagi_compat_chat_helpers import (
    _xcagi_planner_stream_bytes_async as _xcagi_planner_stream_bytes_async,
)
from app.fastapi_routes.xcagi_compat_chat_stream import (
    _xcagi_planner_stream_bytes as _xcagi_planner_stream_bytes,
)


def _sse_event_line(payload: dict) -> bytes:
    from app.neuro_bus.tracer import get_trace_context

    # The producer's original IDs survive persistence/replay. Never turn a
    # transport "done" into an execution success or assign a replay a new span.
    result = payload.get("result")
    original = payload if payload.get("trace_id") else result if isinstance(result, dict) else {}
    context = (
        {key: original[key] for key in ("trace_id", "span_id", "request_id") if original.get(key)}
        if original.get("trace_id")
        else get_trace_context()
    )
    data = {**context, **payload}
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")
