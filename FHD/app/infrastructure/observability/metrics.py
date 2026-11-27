"""统一指标出口，复刻 prometheus_client 的命名与采集口径。

各层只调用 ``observe_*``，不直接持有 Registry：这样本地/桌面端无采集器时
零开销，线上挂 Prometheus 时同一份代码即可抓取。命名前缀 ``xcagi_``，
标签保持低基数（层 + 结果），避免把用户或工具实例名写进标签。

开关 ``XCAGI_METRICS=0`` 可整体停用；停用后只做一次环境读取，不产生样本。
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from math import isfinite

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

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
_TOOL_DURATION_MS = Histogram(
    "xcagi_tool_duration_ms",
    "工具耗时（受控工具名称与结果，毫秒）",
    ("tool", "status"),
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
    registry=_REGISTRY,
)
_MODEL_CALL = Counter(
    "xcagi_model_call_total",
    "模型请求结果（一次宿主请求可含有界重试）",
    ("source", "status"),
    registry=_REGISTRY,
)
_MODEL_PHASE_MS = Histogram(
    "xcagi_model_phase_duration_ms",
    "模型请求可测阶段耗时；等待响应不等于服务端排队或推理耗时",
    ("source", "phase"),
    buckets=(1, 5, 10, 50, 100, 500, 1000, 5000, 30000, 120000, 300000),
    registry=_REGISTRY,
)
_MODEL_PHASES = frozenset(
    {"total", "admission", "connect", "request_send", "response_wait", "response_read"}
)
_DIAGNOSTIC_LAYERS = frozenset(
    {
        "runtime",
        "model",
        "planning",
        "tool",
        "persistence",
        "verification",
        "collaboration",
        "delivery",
        "unknown",
    }
)
_DIAGNOSTIC_KINDS = frozenset(
    {
        "progress_stalled",
        "queue_overdue",
        "lease_expired",
        "deadline_exceeded",
        "child_receipt_missing",
        "model_usage_unknown",
        "business_outcome_unknown",
        "outcome_unknown",
        "model_failed",
        "planning_failed",
        "tool_failed",
        "persistence_failed",
        "verification_failed",
        "collaboration_failed",
        "delivery_failed",
        "runtime_failed",
        "unclassified_failure",
    }
)
_DIAGNOSTIC_SCANS = Counter(
    "xcagi_agent_diagnostic_scans_total", "自动诊断扫描批次结果", ("outcome",), registry=_REGISTRY
)
_DIAGNOSTIC_FAULTS = Counter(
    "xcagi_agent_diagnostic_faults_total",
    "持久工单新建的故障数",
    ("layer", "kind"),
    registry=_REGISTRY,
)
_DIAGNOSTIC_FINDINGS = Gauge(
    "xcagi_agent_diagnostic_findings", "最近完整扫描的故障数", ("layer", "kind"), registry=_REGISTRY
)
_DIAGNOSTIC_SCAN_TIME = Gauge(
    "xcagi_agent_diagnostic_last_complete_scan_timestamp_seconds",
    "最近一次完整扫描完成的Unix时间；未完成扫描不更新",
    registry=_REGISTRY,
)
_diagnostic_finding_labels: set[tuple[str, str]] = set()
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


@lru_cache(maxsize=1)
def _host_tool_labels() -> frozenset[str]:
    # Reuse the host capability SSOT. Account-installed MCP names never become
    # metric labels; exact tool identities remain in their access-controlled trace.
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    return frozenset(sorted(get_workflow_tools_from_registry())[:128])


def _tool_label(tool: str) -> str:
    from app.utils.operational_errors import BOUNDARY_ERRORS

    name = str(tool or "")
    if name.startswith("mcp__"):
        return "mcp"
    try:
        return name if name in _host_tool_labels() else "other"
    except BOUNDARY_ERRORS:
        return "other"


def observe_tool_call(*, tool: str, status: str, duration_ms: float) -> None:
    if not _guard():
        return
    tool_label = _tool_label(tool)
    status_label = "success" if str(status) == "success" else "failure"
    _TOOL_CALL.labels(tool=tool_label, status=status_label).inc()
    duration = float(duration_ms)
    if isfinite(duration) and duration >= 0:
        _TOOL_CALL_MS.observe(duration)
        _TOOL_DURATION_MS.labels(tool=tool_label, status=status_label).observe(duration)


def observe_model_call(*, source: str, status: str, phases_ms: dict[str, float]) -> None:
    if not _guard():
        return
    source = source if source in {"xiaox", "provider"} else "other"
    status = status if status in {"success", "error", "cancelled", "unknown"} else "unknown"
    _MODEL_CALL.labels(source=source, status=status).inc()
    for phase, duration in phases_ms.items():
        if phase in _MODEL_PHASES and isfinite(duration) and duration >= 0:
            _MODEL_PHASE_MS.labels(source=source, phase=phase).observe(duration)


def _diagnostic_labels(layer: str, kind: str) -> tuple[str, str]:
    return (
        layer if layer in _DIAGNOSTIC_LAYERS else "unknown",
        kind if kind in _DIAGNOSTIC_KINDS else "unclassified_failure",
    )


def observe_diagnostic_scan(*, outcome: str) -> None:
    if _guard():
        _DIAGNOSTIC_SCANS.labels(outcome="ok" if outcome == "ok" else "error").inc()


def observe_diagnostic_fault(*, layer: str, kind: str) -> None:
    if _guard():
        _DIAGNOSTIC_FAULTS.labels(*_diagnostic_labels(layer, kind)).inc()


def set_diagnostic_findings(counts: dict[tuple[str, str], int], *, observed_at: float) -> None:
    if not _guard() or not isfinite(observed_at) or observed_at <= 0:
        return
    normalized: dict[tuple[str, str], int] = {}
    for (layer, kind), count in counts.items():
        labels = _diagnostic_labels(layer, kind)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            normalized[labels] = normalized.get(labels, 0) + count
    with _LOCK:
        for labels in _diagnostic_finding_labels | normalized.keys():
            _DIAGNOSTIC_FINDINGS.labels(*labels).set(normalized.get(labels, 0))
        _diagnostic_finding_labels.update(normalized)
        _DIAGNOSTIC_SCAN_TIME.set(observed_at)


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
    "observe_diagnostic_fault",
    "observe_diagnostic_scan",
    "observe_memory_consolidation",
    "observe_memory_recall",
    "observe_model_call",
    "observe_plan_stage",
    "observe_run_terminal",
    "observe_tool_call",
    "render",
    "snapshot",
    "set_diagnostic_findings",
]
