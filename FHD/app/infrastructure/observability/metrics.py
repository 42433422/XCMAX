"""统一指标出口，复刻 prometheus_client 的命名与采集口径。

各层只调用 ``observe_*``，不直接持有 Registry：这样本地/桌面端无采集器时
零开销，线上挂 Prometheus 时同一份代码即可抓取。命名前缀 ``xcagi_``，
标签保持低基数（层 + 结果），避免把用户或工具实例名写进标签。

开关 ``XCAGI_METRICS=0`` 可整体停用；停用后只做一次环境读取，不产生样本。
"""

from __future__ import annotations

import os
import threading

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

_ENV_METRICS = "XCAGI_METRICS"

_REGISTRY = CollectorRegistry(auto_describe=False)
_LOCK = threading.Lock()

_MEMORY_RECALL = Counter(
    "xcagi_memory_recall_total",
    "长期记忆召回次数（按命中结果）",
    ("outcome",),
    registry=_REGISTRY,
)
_MEMORY_RECALL_MS = Histogram(
    "xcagi_memory_recall_duration_ms",
    "长期记忆召回耗时（毫秒）",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
    registry=_REGISTRY,
)
_MEMORY_CONSOLIDATION = Counter(
    "xcagi_memory_consolidation_total",
    "事实合并决策次数（ADD/NOOP/SUPERSEDE/SKIPPED）",
    ("action",),
    registry=_REGISTRY,
)
_PLAN_STAGES = frozenset({"model_returned", "plan_valid"})
_PLAN_OUTCOMES = frozenset(
    {
        "returned",
        "empty",
        "error",
        "valid_first_pass",
        "valid_after_repair",
        "rejected",
    }
)
_PLAN_STAGE = Counter(
    "xcagi_plan_stage_total",
    "规划分阶段结果（模型返回 / 计划有效）",
    ("stage", "outcome"),
    registry=_REGISTRY,
)
_PLAN_STAGE_MS = Histogram(
    "xcagi_plan_stage_duration_ms",
    "规划分阶段耗时（毫秒）",
    ("stage",),
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
    registry=_REGISTRY,
)
_RUN_TERMINAL = Counter(
    "xcagi_run_terminal_total",
    "Agent run 终态（业务目标完成与否）",
    ("status",),
    registry=_REGISTRY,
)
_TOOL_CALL = Counter(
    "xcagi_tool_call_total",
    "工具调用次数（按工具与结果）",
    ("tool", "status"),
    registry=_REGISTRY,
)
_TOOL_CALL_MS = Histogram(
    "xcagi_tool_call_duration_ms",
    "工具调用耗时（毫秒）",
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
    registry=_REGISTRY,
)
_CHAT_TTFT_MS = Histogram(
    "xcagi_chat_ttft_ms",
    "对话流式首 token 延迟（毫秒）",
    buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000),
    registry=_REGISTRY,
)


def metrics_enabled() -> bool:
    raw = str(os.environ.get(_ENV_METRICS) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _guard() -> bool:
    return metrics_enabled()


def observe_memory_recall(*, outcome: str, duration_ms: float) -> None:
    if not _guard():
        return
    label = "hit" if str(outcome) == "hit" else "empty"
    _MEMORY_RECALL.labels(outcome=label).inc()
    _MEMORY_RECALL_MS.observe(max(0.0, float(duration_ms)))


def observe_memory_consolidation(action: str) -> None:
    if not _guard():
        return
    label = str(action or "SKIPPED").upper()
    if label not in {"ADD", "NOOP", "SUPERSEDE", "SKIPPED"}:
        label = "SKIPPED"
    _MEMORY_CONSOLIDATION.labels(action=label).inc()


def observe_plan_stage(*, stage: str, outcome: str, duration_ms: float) -> None:
    if not _guard():
        return
    stage_label = str(stage) if str(stage) in _PLAN_STAGES else "unknown"
    outcome_label = str(outcome) if str(outcome) in _PLAN_OUTCOMES else "unknown"
    _PLAN_STAGE.labels(stage=stage_label, outcome=outcome_label).inc()
    _PLAN_STAGE_MS.labels(stage=stage_label).observe(max(0.0, float(duration_ms)))


def observe_run_terminal(*, status: str) -> None:
    if not _guard():
        return
    _RUN_TERMINAL.labels(status=str(status or "unknown")[:32]).inc()


def observe_tool_call(*, tool: str, status: str, duration_ms: float) -> None:
    if not _guard():
        return
    tool_label = str(tool or "unknown")[:64]
    status_label = "success" if str(status) == "success" else "failure"
    _TOOL_CALL.labels(tool=tool_label, status=status_label).inc()
    _TOOL_CALL_MS.observe(max(0.0, float(duration_ms)))


def observe_chat_ttft(duration_ms: float) -> None:
    if not _guard():
        return
    _CHAT_TTFT_MS.observe(max(0.0, float(duration_ms)))


def snapshot() -> dict[str, float]:
    """导出当前样本，便于测试与健康页只读展示；带标签的样本按标签区分。"""
    with _LOCK:
        values: dict[str, float] = {}
        for metric in _REGISTRY.collect():
            for sample in metric.samples:
                labels = ",".join(f"{key}={value}" for key, value in sorted(sample.labels.items()))
                key = f"{sample.name}{{{labels}}}" if labels else sample.name
                values[key] = float(sample.value)
        return values


def render() -> bytes:
    """Prometheus 文本格式；由 HTTP 层按需暴露。"""
    with _LOCK:
        return generate_latest(_REGISTRY)


__all__ = [
    "metrics_enabled",
    "observe_chat_ttft",
    "observe_memory_consolidation",
    "observe_memory_recall",
    "observe_plan_stage",
    "observe_run_terminal",
    "observe_tool_call",
    "render",
    "snapshot",
]
