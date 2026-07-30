"""持续学习反馈闭环——在线学策略，不在线改意图分类器权重。

三类反馈：
- user_correction：用户纠错
- task_outcome：任务成败
- sla_hit：软 SLA 命中

统一 reward 写入 routing_decisions.jsonl，供 OnlineLearner / Evolution 消费。
意图标签变更仍走离线蒸馏 + canary。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.neuro_bus.routing.routing_log import append_routing_decision
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass
class FeedbackEvent:
    kind: str  # user_correction | task_outcome | sla_hit
    success: bool
    processor: str = "conscious"
    confidence: float = 0.0
    latency_ms: float = 0.0
    sla_hit: bool | None = None
    trace_id: str | None = None
    text_hash: str = ""
    note: str = ""
    features: list[float] | None = None

    def reward(self) -> float:
        """合成 reward：禁止裸文本直接改权重。"""
        if self.kind == "user_correction":
            # 纠错：失败样本给低 reward，纠正成功给高 reward
            base = 0.9 if self.success else 0.1
        elif self.kind == "task_outcome":
            base = 0.85 if self.success else 0.2
        else:  # sla_hit
            hit = self.sla_hit if self.sla_hit is not None else self.success
            base = 0.7 if hit else 0.3
        # 置信度微调（不超过边界）
        adj = max(-0.1, min(0.1, (self.confidence - 0.5) * 0.2))
        return max(0.0, min(1.0, base + adj))


def record_learning_feedback(event: FeedbackEvent) -> dict[str, Any]:
    """把反馈落到 routing_decisions.jsonl（策略学习通道）。"""
    tid = event.trace_id or uuid.uuid4().hex[:16]
    reward = event.reward()
    sla = bool(event.sla_hit) if event.sla_hit is not None else bool(event.success)
    try:
        append_routing_decision(
            trace_id=tid,
            features=list(event.features or []),
            action=str(event.processor or "conscious"),
            latency_ms=float(event.latency_ms or 0.0),
            outcome=f"feedback:{event.kind}",
            reward=reward,
            sla_hit=sla,
            success=bool(event.success),
            extra={
                "source": "learning_feedback",
                "kind": event.kind,
                "confidence": float(event.confidence or 0.0),
                "text_hash": event.text_hash[:64],
                "note": (event.note or "")[:200],
                "ts_unix": time.time(),
                "online_label_update": False,  # 明确：不在线改分类器标签
            },
        )
        return {"ok": True, "trace_id": tid, "reward": reward}
    except RECOVERABLE_ERRORS:
        logger.debug("record_learning_feedback failed", exc_info=True)
        return {"ok": False, "trace_id": tid, "reward": reward}


def record_user_correction(
    *,
    corrected: bool,
    processor: str = "conscious",
    confidence: float = 0.0,
    trace_id: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    return record_learning_feedback(
        FeedbackEvent(
            kind="user_correction",
            success=corrected,
            processor=processor,
            confidence=confidence,
            trace_id=trace_id,
            note=note,
        )
    )


def record_task_outcome(
    *,
    success: bool,
    processor: str = "conscious",
    latency_ms: float = 0.0,
    sla_hit: bool | None = None,
    confidence: float = 0.0,
    trace_id: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    return record_learning_feedback(
        FeedbackEvent(
            kind="task_outcome",
            success=success,
            processor=processor,
            latency_ms=latency_ms,
            sla_hit=sla_hit,
            confidence=confidence,
            trace_id=trace_id,
            note=note,
        )
    )


def maybe_trigger_online_learner() -> dict[str, Any]:
    """窗口够大时触发策略增量更新（不碰意图分类器）。"""
    try:
        from app.neuro_bus.routing.online_learner import OnlineLearner

        learner = OnlineLearner()
        # OnlineLearner 窗口在实例内；生产侧由路由路径喂样本。
        # 这里提供显式钩子：若外部环境注入了共享 learner 再更新。
        if hasattr(learner, "should_update") and learner.should_update():
            version = learner.update_policy()
            return {"updated": bool(version), "version": version}
        return {"updated": False, "version": None, "reason": "below_threshold"}
    except RECOVERABLE_ERRORS:
        logger.debug("maybe_trigger_online_learner failed", exc_info=True)
        return {"updated": False, "version": None, "reason": "error"}
