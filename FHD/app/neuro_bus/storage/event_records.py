"""Event schemas, persisted records and deterministic upcaster chains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.neuro_bus.events.events_base import NeuroEvent


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
        self._upcasters: dict[tuple[str, int], EventUpcaster] = {}
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
            return (payload, from_version)
        chain = self.get_chain(event_type, from_version, target)
        result = payload
        for upcaster in chain:
            result = upcaster.upcast(result)
        return (result, target)

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
                current = self._upcasters[event_type, current].to_version


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

    MEMORY = "memory"
    JSON_FILE = "json"
    SQLITE = "sqlite"


@dataclass
class StoredEvent:
    """存储的事件记录"""

    store_id: str
    event: NeuroEvent
    stored_at: datetime
    sequence_number: int
    stream_id: str | None = None
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
    metadata: dict[str, Any] = field(default_factory=dict)
