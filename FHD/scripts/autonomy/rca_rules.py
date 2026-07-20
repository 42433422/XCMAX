"""RCA 规则映射：signal kind → root_cause（与桌面端 rca-rules.ts 同源）。

服务器端独有 kind：
  - health_down → service_unhealthy
  - manifest_drift → manifest_drift
  - compose_unhealthy → compose_unhealthy

新增 kind 必须同时更新此处与桌面端 rca-rules.ts（保持同源）。
"""

from __future__ import annotations

from .types import Diagnosis, Signal

# 服务器端 + 桌面端共用的 kind → root_cause 映射
RCA_MAP: dict[str, str] = {
    # 桌面端共用 kind
    "backend_exit": "backend_crash",
    "disk_full": "disk_pressure",
    "config_fingerprint_changed": "config_drift",
    "port_in_use": "port_conflict",
    "LLM_RUNTIME_UNAVAILABLE": "llm_runtime_down",
    "NEURO_BUS_CIRCUIT_OPEN": "neurobus_circuit_open",
    "NEURO_BUS_DLQ_FULL": "neurobus_dlq_saturated",
    "NEURO_BUS_RATE_LIMIT": "neurobus_rate_limited",
    "ota_install_failed": "ota_install_corrupted",
    # 服务器端独有 kind（Phase 2）
    "health_down": "service_unhealthy",
    "manifest_drift": "manifest_drift",
    "compose_unhealthy": "compose_unhealthy",
}

DEFAULT_ROOT_CAUSE = "unknown"


def diagnose_root_cause(signals: list[Signal]) -> Diagnosis:
    """诊断纯函数：根据信号列表生成诊断。

    - 取最近一条信号作为主因
    - 证据取最近 5 条信号的 detail
    - 禁止 time.time() / datetime.now()（纯函数，便于回放与测试）
    """
    if not signals:
        return Diagnosis(
            root_cause=DEFAULT_ROOT_CAUSE,
            confidence=0.0,
            detail="无信号输入",
            evidence=[],
        )
    # 按时间倒序，取最新信号作为主因
    sorted_signals = sorted(signals, key=lambda s: s.ts, reverse=True)
    latest = sorted_signals[0]
    root_cause = RCA_MAP.get(latest.kind, DEFAULT_ROOT_CAUSE)
    evidence = [f"[{s.kind}] {s.detail}" for s in sorted_signals[:5]]
    return Diagnosis(
        root_cause=root_cause,
        confidence=0.3 if root_cause == DEFAULT_ROOT_CAUSE else 0.8,
        detail=f"最近信号: {latest.kind} - {latest.detail}",
        evidence=evidence,
    )
