"""Stable status events emitted before a model stream produces text."""

MODEL_STREAM_ACCEPTED_EVENT = {
    "type": "tool_progress",
    "label": "模型服务",
    "text": "模型服务已接收任务，正在思考…",
    "phase": "accepted",
}
