"""Glue: MLP policy -> ProcessorCoordinator ``RoutingDecision`` + JSONL logging."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

from app.domain.neuro.processors.coordinator import ProcessorType, RoutingDecision
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.routing.features import build_routing_features
from app.neuro_bus.routing.policy_nn import predict_with_confidence
from app.neuro_bus.routing.routing_log import append_routing_decision

logger = logging.getLogger(__name__)

_ACTION_ORDER = (ProcessorType.REFLEX, ProcessorType.SUBCONSCIOUS, ProcessorType.CONSCIOUS)

# 动态 canary 状态文件（daemon 写入，router 读取）
_CANARY_STATE_PATH = Path(
    os.environ.get(
        "XCAGI_ROUTING_CANARY_STATE",
        str(
            Path(__file__).resolve().parents[3]
            / "resources"
            / "routing_policies"
            / "canary_state.json"
        ),
    )
)
_CANARY_CACHE_TTL = 30.0  # 秒，每 30 秒刷新一次 canary 状态
_canary_cache: dict[str, Any] | None = None
_canary_cache_ts = 0.0


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


def _load_canary_state() -> tuple[float, str]:
    """从 canary_state.json 动态读取 canary_ratio 和 mode。

    返回 (canary_ratio, mode)。mode 可能是 "shadow"/"canary"/"full"。
    文件不存在或读取失败时回退到环境变量。
    """
    global _canary_cache, _canary_cache_ts
    now = time.monotonic()
    if _canary_cache is not None and (now - _canary_cache_ts) < _CANARY_CACHE_TTL:
        return _canary_cache.get("canary_ratio", 0.0), _canary_cache.get("mode", "shadow")

    try:
        text = _CANARY_STATE_PATH.read_text(encoding="utf-8")
        data = json.loads(text)
        _canary_cache = {
            "canary_ratio": _parse_canary_ratio(str(data.get("canary_ratio", 0.0))),
            "mode": str(data.get("mode", "shadow")),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # 回退到环境变量
        _canary_cache = {
            "canary_ratio": _parse_canary_ratio(
                os.environ.get("XCAGI_ROUTING_POLICY_CANARY_RATIO", "0.0")
            ),
            "mode": (os.environ.get("XCAGI_ROUTING_POLICY_ENABLED") or "").strip().lower(),
        }
    _canary_cache_ts = now
    return _canary_cache["canary_ratio"], _canary_cache["mode"]


def decide_processor_with_policy(
    text: str,
    event: NeuroEvent | None = None,
    *,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> RoutingDecision | None:
    # 优先从 canary_state.json 动态读取，回退到环境变量
    canary_ratio, mode = _load_canary_state()
    if mode not in {"1", "true", "yes", "on", "shadow", "canary", "full"}:
        # 环境变量也没启用
        raw_env = (os.environ.get("XCAGI_ROUTING_POLICY_ENABLED") or "").strip().lower()
        if raw_env not in {"1", "true", "yes", "on", "shadow"}:
            return None
        mode = raw_env
    shadow_mode = mode == "shadow"

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
