"""Glue: MLP policy -> ProcessorCoordinator ``RoutingDecision`` + JSONL logging."""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any

from app.domain.neuro.processors.coordinator import ProcessorType, RoutingDecision
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.routing.features import build_routing_features
from app.neuro_bus.routing.policy_nn import predict_with_confidence
from app.neuro_bus.routing.routing_log import append_routing_decision

logger = logging.getLogger(__name__)

_ACTION_ORDER = (ProcessorType.REFLEX, ProcessorType.SUBCONSCIOUS, ProcessorType.CONSCIOUS)


def _parse_canary_ratio(raw: str) -> float:
    """解析灰度比例，返回 [0.0, 1.0]。非法值视为 0.0（不灰度）。"""
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if val < 0.0:
        return 0.0
    if val > 1.0:
        return 1.0
    return val


def decide_processor_with_policy(
    text: str,
    event: NeuroEvent | None = None,
    *,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> RoutingDecision | None:
    raw = (os.environ.get("XCAGI_ROUTING_POLICY_ENABLED") or "").strip().lower()
    if raw not in {"1", "true", "yes", "on", "shadow"}:
        return None
    shadow_mode = raw == "shadow"

    canary_raw = (os.environ.get("XCAGI_ROUTING_POLICY_CANARY_RATIO") or "").strip()
    canary_ratio = _parse_canary_ratio(canary_raw)

    t0 = time.perf_counter()
    feats = build_routing_features(text, event, extra)
    idx, confidence = predict_with_confidence(feats)
    if idx < 0:
        return None
    if idx >= len(_ACTION_ORDER):
        return None
    proc = _ACTION_ORDER[idx]
    latency_ms = (time.perf_counter() - t0) * 1000
    tid = trace_id
    if tid is None and event is not None:
        tid = event.metadata.trace_id

    # 影子模式：记录 NN 决策但不实际路由，返回 None 回退规则路由
    if shadow_mode:
        append_routing_decision(
            trace_id=tid,
            features=feats,
            action=proc.value,
            latency_ms=latency_ms,
            outcome="policy_shadow",
            reward=None,
            sla_hit=None,
            success=None,
            extra={"source": "policy_mlp", "confidence": confidence, "shadow": True},
        )
        return None

    # 灰度模式：random.random() > canary_ratio 时回退规则路由
    if canary_ratio < 1.0 and random.random() > canary_ratio:
        append_routing_decision(
            trace_id=tid,
            features=feats,
            action=proc.value,
            latency_ms=latency_ms,
            outcome="policy_canary_fallback",
            reward=None,
            sla_hit=None,
            success=None,
            extra={
                "source": "policy_mlp",
                "confidence": confidence,
                "shadow": False,
                "canary_ratio": canary_ratio,
                "canary_fallback": True,
            },
        )
        return None

    append_routing_decision(
        trace_id=tid,
        features=feats,
        action=proc.value,
        latency_ms=latency_ms,
        outcome="policy_selected",
        reward=None,
        sla_hit=None,
        success=None,
        extra={"source": "policy_mlp", "confidence": confidence, "shadow": False},
    )
    return RoutingDecision(
        processor_type=proc,
        confidence=confidence,
        reason=f"routing_policy_mlp:{idx}",
    )
