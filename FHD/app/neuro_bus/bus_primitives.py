"""Configuration helpers and queue primitives for NeuroBus."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable

from app.neuro_bus.events.events_base import AsyncEventHandler, EventHandler, NeuroEvent

logger = logging.getLogger(__name__)


def _neuro_env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _deployment_is_staging() -> bool:
    """k8s/CI：设置 FHD_ENV=staging；与本仓库 staging 部署约定一致。"""
    return os.environ.get("FHD_ENV", "").strip().lower() == "staging"


def _deployment_is_production() -> bool:
    """k8s/CI：设置 FHD_ENV=production；生产环境安全优先，可靠性机制默认全开。"""
    return os.environ.get("FHD_ENV", "").strip().lower() == "production"


def _neuro_trace_sample_rate() -> float:
    """生产 trace 采样率，避免洪泛。XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE 默认 0.1。"""
    raw = os.environ.get("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "0.1").strip()
    try:
        rate = float(raw)
    except ValueError:
        rate = 0.1
    return max(0.0, min(1.0, rate))


def _should_trace_event() -> bool:
    """未启用 tracer 时忽略；启用后按采样率决定是否记录 span。"""
    rate = _neuro_trace_sample_rate()
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    import random

    return random.random() < rate


def _neuro_reliability_wanted(
    env_name: str, *, staging_default: bool, production_default: bool = True
) -> bool:
    """
    可靠性层开关：显式设置环境变量时以变量为准；未设置时在 staging/production
    采用默认值（生产安全优先，production_default 默认 True）。
    """
    raw = os.environ.get(env_name)
    if raw is not None and str(raw).strip() != "":
        return _neuro_env_flag(env_name)
    if _deployment_is_staging():
        return staging_default
    if _deployment_is_production():
        return production_default
    return False


class HandlerSubscription:
    """处理器订阅信息"""

    def __init__(
        self,
        event_type: str,
        handler: EventHandler | AsyncEventHandler,
        priority: int = 0,
        is_async: bool = True,
        filter_fn: Callable[[NeuroEvent], bool] | None = None,
    ):
        self.event_type = event_type
        self.handler = handler
        self.priority = priority
        self.is_async = is_async
        self.filter_fn = filter_fn
        self.created_at = time.time()
        self.call_count = 0
        self.error_count = 0

    def should_handle(self, event: NeuroEvent) -> bool:
        """检查是否应该处理该事件"""
        if self.filter_fn:
            return self.filter_fn(event)
        return True

    def record_call(self, success: bool = True):
        """记录调用统计"""
        self.call_count += 1
        if not success:
            self.error_count += 1

    @property
    def error_rate(self) -> float:
        """计算错误率"""
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count


_DOMAIN_ENTITY: dict[str, str | None] = {
    "shipment": "shipment_id",
    "material": "material_id",
    "print": "job_id",
    "order": "order_id",
    "payment": "payment_id",
    "product": "product_id",
    "customer": "customer_id",
    "ocr": "task_id",
    "auth": "user_id",
    "conversation": "conversation_id",
    "ai": "session_id",
    "ai_service": "user_id",
    "intent": "user_id",
    "workflow": "run_id",
    "agent": "run_id",
    "employee": "employee_id",
    # Transfers/batch adjustments can touch several products in one operation.
    "inventory": None,
}
_ENTITY_FIELDS = {name for name in _DOMAIN_ENTITY.values() if name is not None} | {"entity_id"}


def event_partition_key(event: NeuroEvent) -> tuple[str, str, str, str]:
    """Use domain aggregate keys, never a related customer's/order's first ID.

    Missing/ambiguous business identities form a domain barrier. Generic unkeyed
    notifications remain independent; a domain publisher can set _aggregate_id.
    """
    payload = event.payload
    tenant = str(payload.get("tenant_id") or payload.get("organization_id") or "")
    prefix = event.event_type.partition(".")[0]
    domain = prefix if prefix in _DOMAIN_ENTITY else event.metadata.domain
    primary = _DOMAIN_ENTITY.get(domain)
    if primary:
        value = payload.get(primary, payload.get("_aggregate_id"))
        if value is not None and str(value) != "":
            return domain, tenant, primary, str(value)
    elif domain not in _DOMAIN_ENTITY:
        keys = [name for name in _ENTITY_FIELDS if payload.get(name) is not None]
        if len(keys) == 1:
            return domain, tenant, keys[0], str(payload[keys[0]])
        if not keys and payload.get("_aggregate_id") is not None:
            return domain, tenant, "entity_id", str(payload["_aggregate_id"])
        if not keys and domain == "global":
            return domain, tenant, "event_id", event.metadata.event_id
    return domain, tenant, "*", ""


def _partition_scope(key: Hashable) -> tuple | None:
    return key[:2] if isinstance(key, tuple) and len(key) == 4 else None


def _domain_barrier(key: Hashable) -> bool:
    return isinstance(key, tuple) and len(key) == 4 and key[2] == "*"


class PriorityEventQueue:
    """Bounded five-priority queue; FIFO within each entity, even across priorities.

    Only each partition's head competes for dispatch. Eviction uses the lowest
    priority's newest event, preserving older work and avoiding a full heap scan.
    """

    def __init__(
        self,
        max_size: int = 10000,
        *,
        partition_key: Callable[[NeuroEvent], Hashable] | None = None,
        on_evict: Callable[[NeuroEvent], None] | None = None,
    ):
        self._levels: list[OrderedDict[str, tuple[Hashable, NeuroEvent]]] = [
            OrderedDict() for _ in range(5)
        ]
        self._partitions: dict[Hashable, OrderedDict[str, NeuroEvent]] = {}
        self._ready: list[OrderedDict[Hashable, tuple[str, NeuroEvent]]] = [
            OrderedDict() for _ in range(5)
        ]
        self._event_ids: set[str] = set()
        self._sequence = 0
        self._scopes: dict[tuple, OrderedDict[str, int]] = {}
        self._barriers: dict[tuple, OrderedDict[str, int]] = {}
        self._max_size = max(0, max_size)
        self._partition_key = partition_key or (lambda event: event.metadata.event_id)
        self._on_evict = on_evict
        self._lock = threading.RLock()
        self._dropped_count = 0

    def _remove(self, event_id: str, priority: int) -> NeuroEvent:
        key, event = self._levels[priority].pop(event_id)
        scope = _partition_scope(key)
        if scope is not None:
            for index in (self._scopes, self._barriers):
                if scope in index:
                    index[scope].pop(event_id, None)
                    if not index[scope]:
                        del index[scope]
        partition = self._partitions[key]
        was_head = next(iter(partition)) == event_id
        del partition[event_id]
        self._event_ids.discard(event_id)
        if was_head:
            self._ready[priority].pop(key, None)
            if partition:
                head_id, head = next(iter(partition.items()))
                self._ready[head.priority.value][key] = head_id, head
        if not partition:
            del self._partitions[key]
        return event

    def put(self, event: NeuroEvent) -> bool:
        with self._lock:
            for attempt in range(4):
                if event.metadata.event_id not in self._event_ids:
                    break
                if attempt == 3:
                    self._dropped_count += 1
                    return False
                event.remint_queue_identity()
            if len(self._event_ids) >= self._max_size:
                lowest = next((i for i in range(4, -1, -1) if self._levels[i]), -1)
                if lowest <= event.priority.value:
                    self._dropped_count += 1
                    return False
                old_id = next(reversed(self._levels[lowest]))
                old_event = self._remove(old_id, lowest)
                self._dropped_count += 1
                if self._on_evict is not None:
                    self._on_evict(old_event)
            key = self._partition_key(event)
            eid = event.metadata.event_id
            scope = _partition_scope(key)
            if scope is not None:
                self._sequence += 1
                self._scopes.setdefault(scope, OrderedDict())[eid] = self._sequence
                if _domain_barrier(key):
                    self._barriers.setdefault(scope, OrderedDict())[eid] = self._sequence
            partition = self._partitions.setdefault(key, OrderedDict())
            if not partition:
                self._ready[event.priority.value][key] = eid, event
            partition[eid] = event
            self._levels[event.priority.value][eid] = key, event
            self._event_ids.add(eid)
            return True

    def get(self, blocked: set[Hashable] | None = None) -> NeuroEvent | None:
        with self._lock:
            for priority, ready in enumerate(self._ready):
                for key, (eid, _) in ready.items():
                    if blocked and key in blocked:
                        continue
                    scope = _partition_scope(key)
                    if scope is not None:
                        if _domain_barrier(key):
                            if next(iter(self._scopes[scope])) != eid or any(
                                _partition_scope(active) == scope for active in blocked or ()
                            ):
                                continue
                        else:
                            barriers = self._barriers.get(scope)
                            if (blocked and (*scope, "*", "") in blocked) or (
                                barriers
                                and next(iter(barriers.values())) < self._scopes[scope][eid]
                            ):
                                continue
                    return self._remove(eid, priority)
        return None

    def peek(self) -> NeuroEvent | None:
        with self._lock:
            for ready in self._ready:
                if ready:
                    return next(iter(ready.values()))[1]
        return None

    def size(self) -> int:
        with self._lock:
            return len(self._event_ids)

    def clear(self):
        with self._lock:
            for level in (*self._levels, *self._ready):
                level.clear()
            self._partitions.clear()
            self._event_ids.clear()
            self._scopes.clear()
            self._barriers.clear()
