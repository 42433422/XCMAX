# ruff: noqa: E402, F401
"""
事件存储与重播 - Level 4 可靠性机制

提供：
- 事件持久化存储
- 事件溯源支持
- 快照管理
- 时间旅行（重播）
- 审计日志
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


# ========== 异常定义 ==========


class WrongExpectedVersionError(Exception):
    """乐观并发冲突：expected_version 与实际 stream version 不匹配"""

    def __init__(self, stream_id: str, expected: int, actual: int):
        self.stream_id = stream_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"[EventStore] 乐观并发冲突: stream={stream_id} expected_version={expected} actual_version={actual}"
        )


class InvalidEventError(Exception):
    """事件 schema 校验失败"""


# ========== 事件 Upcaster ==========


class EventUpcaster(ABC):
    """事件 upcaster 抽象基类 - 将事件 payload 从 from_version 升级到 to_version"""

    event_type: str
    from_version: int
    to_version: int

    @abstractmethod
    def upcast(self, payload: dict[str, Any]) -> dict[str, Any]:
        """将 payload 从 from_version 升级到 to_version（必须是纯函数）"""
        ...


class UpcasterRegistry:
    """upcaster 注册表 - 管理 event_type 的版本升级链"""

    def __init__(self) -> None:
        # (event_type, from_version) -> upcaster
        self._upcasters: dict[tuple[str, int], EventUpcaster] = {}
        # event_type -> current_version（最新版本号）
        self._current_versions: dict[str, int] = {}

    def register(self, upcaster: EventUpcaster) -> None:
        """注册一个 upcaster，并更新该 event_type 的当前版本"""
        key = (upcaster.event_type, upcaster.from_version)
        if key in self._upcasters:
            raise ValueError(
                f"[UpcasterRegistry] 重复注册: event_type={upcaster.event_type} from_version={upcaster.from_version}"
            )
        if upcaster.to_version != upcaster.from_version + 1:
            raise ValueError(
                f"[UpcasterRegistry] upcaster 必须连续升级: from_ver={upcaster.from_version} to_ver={upcaster.to_version}"
            )
        self._upcasters[key] = upcaster
        # 更新当前版本（取最大 to_version）
        prev = self._current_versions.get(upcaster.event_type, 1)
        self._current_versions[upcaster.event_type] = max(prev, upcaster.to_version)

    def get_chain(self, event_type: str, from_version: int, to_version: int) -> list[EventUpcaster]:
        """获取从 from_version 到 to_version 的 upcaster 链"""
        chain: list[EventUpcaster] = []
        current = from_version
        while current < to_version:
            upcaster = self._upcasters.get((event_type, current))
            if upcaster is None:
                raise ValueError(
                    f"[UpcasterRegistry] 链断裂: event_type={event_type} 缺少 from_version={current} 的 upcaster"
                )
            chain.append(upcaster)
            current = upcaster.to_version
        return chain

    def upcast(
        self, event_type: str, payload: dict[str, Any], from_version: int
    ) -> tuple[dict[str, Any], int]:
        """
        将 payload 从 from_version 升级到当前版本

        Returns:
            (升级后的 payload, 最终版本号)
        """
        target = self._current_versions.get(event_type, 1)
        if from_version >= target:
            return payload, from_version
        chain = self.get_chain(event_type, from_version, target)
        result = payload
        for upcaster in chain:
            result = upcaster.upcast(result)
        return result, target

    def get_current_version(self, event_type: str) -> int:
        """获取 event_type 的当前 schema 版本"""
        return self._current_versions.get(event_type, 1)

    def validate_chains(self) -> None:
        """校验所有注册的 upcaster 链完整（v1→v2→...→current 无断链）"""
        for event_type, target in self._current_versions.items():
            current = 1
            while current < target:
                if (event_type, current) not in self._upcasters:
                    raise ValueError(
                        f"[UpcasterRegistry] 链断裂: event_type={event_type} 缺少 from_version={current} 的 upcaster"
                    )
                current = self._upcasters[(event_type, current)].to_version


def validate_event_schema(event: NeuroEvent) -> bool:
    """
    校验事件结构

    - event_type 非空
    - payload 是 dict
    - metadata.event_id 非空

    校验失败抛出 InvalidEventError
    """
    if not event.event_type or not isinstance(event.event_type, str):
        raise InvalidEventError(f"event_type 必须是非空字符串，实际: {event.event_type!r}")
    if not isinstance(event.payload, dict):
        raise InvalidEventError(f"payload 必须是 dict，实际类型: {type(event.payload).__name__}")
    if not event.metadata.event_id:
        raise InvalidEventError("metadata.event_id 不能为空")
    return True


class EventStoreMode(Enum):
    """存储模式"""

    MEMORY = "memory"  # 内存存储（仅用于测试）
    JSON_FILE = "json"  # JSON 文件
    SQLITE = "sqlite"  # SQLite 数据库


@dataclass
class StoredEvent:
    """存储的事件记录"""

    store_id: str
    event: NeuroEvent
    stored_at: datetime
    sequence_number: int
    stream_id: str | None = None  # 事件流 ID（用于聚合根）
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "event": {
                "event_id": self.event.metadata.event_id,
                "event_type": self.event.event_type,
                "payload": self.event.payload,
                "timestamp": self.event.metadata.timestamp,
                "source": self.event.metadata.source,
                "correlation_id": self.event.metadata.correlation_id,
                "priority": self.event.priority.value,
            },
            "stored_at": self.stored_at.isoformat(),
            "sequence_number": self.sequence_number,
            "stream_id": self.stream_id,
            "metadata": self.metadata,
        }


@dataclass
class Snapshot:
    """聚合根快照"""

    snapshot_id: str
    stream_id: str
    sequence_number: int
    state: dict[str, Any]
    created_at: datetime
    version: int = 1
    # metadata 用于存储 state_hash 等校验信息
    metadata: dict[str, Any] = field(default_factory=dict)


from app.neuro_bus.event_store_eventstore_mixin01 import _EventStorePart01Mixin
from app.neuro_bus.event_store_eventstore_mixin02 import _EventStorePart02Mixin


class EventStore(_EventStorePart01Mixin, _EventStorePart02Mixin):
    """
    事件存储

    Level 4 可靠性机制:
    - 持久化所有领域事件
    - 支持事件溯源
    - 快照优化加载性能
    - 时间旅行调试
    """

    # ========== 存储操作 ==========

    # ========== 查询操作 ==========

    # ========== 快照管理 ==========

    # ========== 重播机制 ==========

    # ========== 审计 ==========

    # ========== 统计 ==========

    # ========== 管理 ==========


# ========== 全局实例 ==========

_event_store_instance: EventStore | None = None


def get_event_store(mode: EventStoreMode | None = None) -> EventStore:
    """获取全局事件存储实例"""
    global _event_store_instance
    if _event_store_instance is None:
        _event_store_instance = EventStore(mode=mode or EventStoreMode.MEMORY)
    elif mode is not None and _event_store_instance._mode != mode:
        _event_store_instance = EventStore(mode=mode)
    return _event_store_instance


def store_event(event: NeuroEvent, stream_id: str | None = None) -> str:
    """快捷函数：存储事件"""
    return get_event_store().append(event, stream_id)


def replay_events(**kwargs) -> int:
    """快捷函数：重播事件"""
    return get_event_store().replay(**kwargs)


def get_event_stats() -> dict[str, Any]:
    """快捷函数：获取统计"""
    return get_event_store().get_stats()
