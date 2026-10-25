"""Live replay delivery and a shared throttled batch/progress iterator."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from app.neuro_bus.events.events_base import NeuroEvent

from .dead_letter_policies import ReplayLedger
from .replay_claim import ReplayClaim
from .sqlite import StorageRuntime

if TYPE_CHECKING:
    from app.neuro_bus.dead_letter_queue import DeadLetterEntry


class CandidateReader(Protocol):
    def __call__(
        self, event_type: str | None = None, max_age_seconds: float | None = None
    ) -> list[str]: ...


@dataclass(frozen=True)
class ReplaySchedulePorts:
    candidates: CandidateReader
    replay: Callable[[str], tuple[bool, str]]
    is_paused: Callable[[], bool]
    pause: Callable[[], None]
    total_entries: Callable[[], int]


class ReplayDelivery:
    def __init__(
        self,
        claim: ReplayClaim,
        load: Callable[[str], DeadLetterEntry | None],
        ledger: ReplayLedger,
        callbacks: list[Callable[[NeuroEvent], None]],
        stats: dict[str, int],
        lock: threading.RLock,
        runtime: StorageRuntime,
    ):
        self.claim = claim
        self.load = load
        self.ledger = ledger
        self.callbacks = callbacks
        self.stats = stats
        self.lock = lock
        self.runtime = runtime

    def replay(self, entry_id: str) -> tuple[bool, str]:
        with self.claim.acquire(entry_id) as acquired:
            if not acquired:
                return False, "replay_in_progress"
            entry = self.load(entry_id)
            if entry is None:
                self.runtime.log().warning("[DeadLetterQueue] 重播失败：找不到条目 %s", entry_id)
                return False, "entry_not_found"
            replay_count = entry.retry_count
            if self.ledger.is_replayed(entry_id, replay_count):
                self.runtime.log().info(
                    "[DeadLetterQueue] 跳过重播（已重播过）: %s (retry_count=%s)",
                    entry_id,
                    replay_count,
                )
                return False, "already_replayed"
            self.runtime.log().info(
                "[DeadLetterQueue] 重播事件: %s (entry_id=%s)",
                entry.original_event.event_type,
                entry_id,
            )
            # The claim covers live delivery, not a database transaction or
            # the storage mutex. Handlers may read, enqueue or schedule retry.
            for callback in self.callbacks:
                try:
                    callback(entry.original_event)
                except self.runtime.errors() as error:
                    self.runtime.log().error("[DeadLetterQueue] 重播回调失败: %s", error)
            self.ledger.mark_replayed(entry_id, replay_count)
            with self.lock:
                self.stats["replayed"] += 1
            return True, ""


class ReplaySchedule:
    def __init__(self, ports: ReplaySchedulePorts, runtime: StorageRuntime):
        self.ports = ports
        self.runtime = runtime

    def _iterate(
        self, entries: list[str], rate_limit_qps: float, batch_size: int
    ) -> Iterator[tuple[int, int, str]]:
        replayed = 0
        total = len(entries)
        delay = batch_size / rate_limit_qps if rate_limit_qps > 0 else 0.0
        for index, entry_id in enumerate(entries):
            if self.ports.is_paused():
                self.runtime.log().info("[DeadLetterQueue] 重播已暂停，停止于 %s/%s", index, total)
                return
            success, _ = self.ports.replay(entry_id)
            replayed += int(success)
            yield replayed, total, entry_id
            if (index + 1) % batch_size == 0 and index + 1 < total and delay > 0:
                self.runtime.sleep(delay)

    def all(
        self,
        event_type: str | None,
        max_age_seconds: float | None,
        rate_limit_qps: float,
        batch_size: int,
    ) -> int:
        entries = self.ports.candidates(event_type, max_age_seconds)
        replayed = 0
        for replayed, _, _entry_id in self._iterate(entries, rate_limit_qps, batch_size):
            pass
        self.runtime.log().info(
            "[DeadLetterQueue] 批量重播完成: %s/%s 个事件", replayed, len(entries)
        )
        return replayed

    def with_progress(
        self,
        event_type: str | None,
        max_age_seconds: float | None,
        rate_limit_qps: float,
        batch_size: int,
    ) -> Iterator[tuple[int, int, str]]:
        yield from self._iterate(
            self.ports.candidates(event_type, max_age_seconds), rate_limit_qps, batch_size
        )

    def gradual(
        self,
        event_type: str | None,
        stages: list[float] | None,
        stage_interval: float,
        error_threshold: int,
    ) -> dict[str, Any]:
        stages = [0.01, 0.1, 0.5, 1.0] if stages is None else stages
        entries = self.ports.candidates(event_type, None)
        total = len(entries)
        report: dict[str, Any] = {
            "total": total,
            "stages_executed": [],
            "replayed": 0,
            "paused": False,
            "pause_reason": None,
        }
        if total == 0:
            return report
        replayed = 0
        for index, fraction in enumerate(stages):
            if self.ports.is_paused():
                report.update(paused=True, pause_reason="manual_pause")
                break
            batch = entries[replayed : int(total * fraction)]
            before = self.ports.total_entries()
            for entry_id in batch:
                if self.ports.is_paused():
                    report.update(paused=True, pause_reason="manual_pause")
                    break
                success, _ = self.ports.replay(entry_id)
                replayed += int(success)
            added = self.ports.total_entries() - before
            report["stages_executed"].append(
                {
                    "stage": index,
                    "fraction": fraction,
                    "target": len(batch),
                    "replayed": replayed,
                    "new_dlq": added,
                }
            )
            if added >= error_threshold:
                report.update(
                    paused=True,
                    pause_reason=f"error_threshold_exceeded: {added} >= {error_threshold}",
                )
                self.ports.pause()
                break
            if index < len(stages) - 1:
                self.runtime.sleep(stage_interval)
        report["replayed"] = replayed
        return report
