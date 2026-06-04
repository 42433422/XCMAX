"""
NeuroBus 背压策略（Task 4 闭环 2026-06-03）

设计目标：
- 把现有 PriorityEventQueue.put() 的「硬编码 drop_low」变成可配置策略。
- 被丢弃的事件不静默丢失，而是通过 on_drop 回调通知上层（通常挂到 DLQ）。
- 保持向后兼容：默认策略 = 原有行为（高优先级挤掉低优先级）。

四种策略：
- DROP_OLD  : 队列满时丢弃队中最低优先级事件（默认；保留「保命通道」语义）
- DROP_NEW  : 队列满时直接拒绝新入队事件（更激进，适合保护下游）
- REJECT    : 队列满时拒绝新入队事件，调用方拿 False
- BLOCK     : 阻塞等待（带超时）；当前实现为快速失败（False），完整 block 需 asyncio.Lock + cond

环境变量：
- XCAGI_NEURO_BUS_BACKPRESSUE  默认 drop_old；可选 drop_new / reject
- XCAGI_NEURO_BUS_DLQ_ON_DROP  默认 1；0 = 不入 DLQ（仅日志）
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.neuro_bus.events.base import NeuroEvent

logger = logging.getLogger(__name__)


class BackpressurePolicy(str, Enum):
    """背压策略枚举。字符串值用于环境变量解析。"""

    DROP_OLD = "drop_old"  # 队满 → 驱逐最低优先级事件
    DROP_NEW = "drop_new"  # 队满 → 拒绝新入队
    REJECT = "reject"  # 队满 → 拒绝新入队（语义同 drop_new；保留区分便于扩展）
    BLOCK = "block"  # 队满 → 阻塞等待（当前实现退化为 reject）


_VALID_POLICIES: frozenset[str] = frozenset(p.value for p in BackpressurePolicy)


def parse_backpressure_policy(raw: str | None) -> BackpressurePolicy:
    """解析环境变量 / 字符串到策略；非法值回退 DROP_OLD 并打 warning。"""
    if not raw:
        return BackpressurePolicy.DROP_OLD
    val = raw.strip().lower()
    if val in _VALID_POLICIES:
        return BackpressurePolicy(val)
    logger.warning(
        "[NeuroBus] 未知的 backpressure 策略 %r，回退到 drop_old；合法值=%s",
        raw,
        sorted(_VALID_POLICIES),
    )
    return BackpressurePolicy.DROP_OLD


def env_backpressure_policy() -> BackpressurePolicy:
    """读取 ``XCAGI_NEURO_BUS_BACKPRESSURE`` 环境变量并解析。"""
    return parse_backpressure_policy(os.environ.get("XCAGI_NEURO_BUS_BACKPRESSURE"))


def env_dlq_on_drop() -> bool:
    """``XCAGI_NEURO_BUS_DLQ_ON_DROP`` 默认 True（被丢弃事件入 DLQ）。"""
    raw = os.environ.get("XCAGI_NEURO_BUS_DLQ_ON_DROP", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass
class DropRecord:
    """一次丢弃事件的记录。供上层（DLQ 适配器）做持久化。"""

    event: "NeuroEvent"
    reason: str  # "queue_full" | "duplicate_id_unresolved" | "policy_reject"
    policy: BackpressurePolicy
    queue_size: int
    queue_max: int
    timestamp: float = field(default_factory=lambda: __import__("time").time())


# 类型别名：on_drop 回调签名 ``(DropRecord) -> None``
DropCallback = Callable[[DropRecord], None]


__all__ = [
    "BackpressurePolicy",
    "DropRecord",
    "DropCallback",
    "env_backpressure_policy",
    "env_dlq_on_drop",
    "parse_backpressure_policy",
]
