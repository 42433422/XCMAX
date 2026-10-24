"""Replay and conflict retry orchestration over explicit read/write callbacks."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any, Protocol

from app.neuro_bus.events.base import NeuroEvent

from .event_records import Snapshot, StoredEvent, WrongExpectedVersionError
from .sqlite import StorageRuntime


class StreamReader(Protocol):
    def __call__(self, stream_id: str, from_sequence: int = 0) -> list[StoredEvent]: ...


class EventReader(Protocol):
    def __call__(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        event_type: str | None = None,
    ) -> Iterator[StoredEvent]: ...


class BatchAppender(Protocol):
    def __call__(
        self,
        events: list[NeuroEvent],
        stream_id: str | None = None,
        expected_version: int | None = None,
    ) -> list[str]: ...


class EventRecovery:
    def __init__(
        self,
        read_stream: StreamReader,
        read_all: EventReader,
        snapshot: Callable[[str], Snapshot | None],
        append_batch: BatchAppender,
        compute_hash: Callable[[dict[str, Any]], str],
        runtime: StorageRuntime,
    ):
        self.read_stream = read_stream
        self.read_all = read_all
        self.snapshot = snapshot
        self.append_batch = append_batch
        self.compute_hash = compute_hash
        self.runtime = runtime

    def append_with_retry(
        self,
        stream_id: str,
        build_events: Callable[[list[StoredEvent]], list[NeuroEvent]],
        max_retries: int = 3,
        base_delay: float = 0.01,
    ) -> list[str]:
        """乐观并发重试追加。"""
        last_error: WrongExpectedVersionError | None = None
        for attempt in range(max_retries + 1):
            current_events = self.read_stream(stream_id)
            expected_version = len(current_events)
            new_events = build_events(current_events)
            if not new_events:
                return []
            try:
                return self.append_batch(
                    new_events, stream_id=stream_id, expected_version=expected_version
                )
            except WrongExpectedVersionError as e:
                last_error = e
                if attempt < max_retries:
                    delay = base_delay * 2**attempt
                    self.runtime.log().warning(
                        "[EventStore] 乐观并发冲突，%ss 后重试 (attempt=%s/%s, stream=%s)",
                        delay,
                        attempt + 1,
                        max_retries,
                        stream_id,
                    )
                    self.runtime.sleep(delay)
        if isinstance(last_error, BaseException):
            raise last_error
        raise RuntimeError("event append retries exhausted without a captured error")

    def get_events_after_snapshot(self, stream_id: str) -> list[StoredEvent]:
        """获取快照后的事件（用于恢复聚合根）"""
        snapshot = self.snapshot(stream_id)
        if not snapshot:
            return self.read_stream(stream_id)
        return self.read_stream(stream_id, from_sequence=snapshot.sequence_number + 1)

    def replay(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        event_types: list[str] | None = None,
        stream_id: str | None = None,
        callback: Callable[[NeuroEvent], None] | None = None,
    ) -> int:
        """重播事件。"""
        count = 0
        if stream_id:
            events = self.read_stream(stream_id)
        else:
            events = list(self.read_all(start_time, end_time))
        for stored in events:
            if event_types and stored.event.event_type not in event_types:
                continue
            if callback:
                try:
                    callback(stored.event)
                    count += 1
                except self.runtime.errors() as e:
                    self.runtime.log().error("[EventStore] 重播失败: %s", e)
            else:
                self.runtime.log().info(
                    "[EventStore] 重播: %s (store_id=%s)", stored.event.event_type, stored.store_id
                )
                count += 1
        self.runtime.log().info("[EventStore] 重播完成: %s 个事件", count)
        return count

    def replay_stream(
        self,
        stream_id: str,
        use_snapshot: bool = True,
        callback: Callable[[NeuroEvent], None] | None = None,
    ) -> dict[str, Any]:
        """重播事件流（用于恢复聚合根）。"""
        snapshot = None
        start_sequence = 0
        snapshot_hash_verified = True
        if use_snapshot:
            snapshot = self.snapshot(stream_id)
            if snapshot:
                stored_hash = snapshot.metadata.get("state_hash")
                if stored_hash is not None:
                    actual_hash = self.compute_hash(snapshot.state)
                    if stored_hash != actual_hash:
                        self.runtime.log().warning(
                            "[EventStore] 快照 state_hash 校验失败，丢弃快照全量重放: stream=%s snap_id=%s expected=%s actual=%s",
                            stream_id,
                            snapshot.snapshot_id,
                            stored_hash[:8],
                            actual_hash[:8],
                        )
                        snapshot = None
                        snapshot_hash_verified = False
                start_sequence = snapshot.sequence_number + 1 if snapshot else 0
        events = self.read_stream(stream_id, from_sequence=start_sequence)
        applied_count = 0
        for stored in events:
            if callback:
                callback(stored.event)
            applied_count += 1
        result: dict[str, Any] = {
            "stream_id": stream_id,
            "applied_events": applied_count,
            "snapshot_used": snapshot is not None,
            "snapshot_hash_verified": snapshot_hash_verified,
        }
        if snapshot:
            result["snapshot_sequence"] = snapshot.sequence_number
            result["snapshot_age_seconds"] = (
                self.runtime.clock().now() - snapshot.created_at
            ).total_seconds()
        self.runtime.log().info(
            "[EventStore] 流重播完成: %s (applied=%s)", stream_id, applied_count
        )
        return result

    def get_audit_log(
        self,
        stream_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """获取审计日志"""
        if stream_id:
            events = self.read_stream(stream_id)
        else:
            events = list(self.read_all(start_time, end_time))
        return [
            {
                "timestamp": e.stored_at.isoformat(),
                "event_type": e.event.event_type,
                "event_id": e.event.metadata.event_id,
                "source": e.event.metadata.source,
                "correlation_id": e.event.metadata.trace_id,
                "payload_keys": list(e.event.payload.keys()),
            }
            for e in events
        ]
