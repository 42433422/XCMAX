"""Atomic retry and resolution transitions, retention, statistics and triage."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .dead_letter_repository import DeadLetterRepository
from .sqlite import fetch_rows


class DeadLetterManagement:
    def __init__(
        self,
        repository: DeadLetterRepository,
        retention_seconds: int,
        random_value: Callable[[], float],
    ):
        self.repository = repository
        self.retention_seconds = retention_seconds
        self.random_value = random_value

    def resolve(self, entry_id: str, resolution: str, resolved_by: str) -> bool:
        repository = self.repository
        with repository.storage.lock:
            with repository.storage.write() as connection:
                entry = repository.get(entry_id)
                if entry is None:
                    return False
                entry.metadata.update(
                    resolved=True,
                    resolution=resolution,
                    resolved_by=resolved_by,
                    resolved_at=repository.runtime.clock().now().isoformat(),
                )
                if connection is not None:
                    connection.execute(
                        "UPDATE neuro_dead_letters SET is_resolved = 1, metadata = ? WHERE entry_id = ?",
                        (json.dumps(entry.metadata, ensure_ascii=False), entry_id),
                    ).close()
                    connection.execute(
                        "DELETE FROM neuro_dead_letters WHERE entry_id = ?", (entry_id,)
                    ).close()
                else:
                    del repository.state.entries[entry_id]
            repository.state.stats["manually_resolved"] += 1
        repository.runtime.log().info(
            "[DeadLetterQueue] 手动解决: %s (resolution=%s, by=%s)",
            entry_id,
            resolution,
            resolved_by,
        )
        return True

    def cleanup_expired(self) -> int:
        repository = self.repository
        with repository.storage.lock:
            with repository.storage.write() as connection:
                if connection is not None:
                    clock = repository.runtime.clock()
                    cutoff = clock.fromtimestamp(clock.now().timestamp() - self.retention_seconds)
                    cursor = connection.execute(
                        "DELETE FROM neuro_dead_letters WHERE first_failure_time < ?",
                        (cutoff.isoformat(),),
                    )
                    count = cursor.rowcount
                    cursor.close()
                else:
                    expired = [
                        entry_id
                        for entry_id, entry in repository.state.entries.items()
                        if entry.age_seconds > self.retention_seconds
                    ]
                    for entry_id in expired:
                        del repository.state.entries[entry_id]
                    count = len(expired)
            repository.state.stats["expired"] += count
        if count:
            repository.runtime.log().info("[DeadLetterQueue] 清理过期条目: %s 个", count)
        return count

    def schedule_retry(self, entry_id: str, base: float, cap: float) -> float | None:
        repository = self.repository
        if repository.get(entry_id) is None:
            repository.runtime.log().warning(
                "[DeadLetterQueue] schedule_retry 失败：找不到条目 %s", entry_id
            )
            return None
        jitter = 0.5 + self.random_value() * 0.5
        with repository.storage.write() as connection:
            # Another instance may have advanced or removed the entry since
            # the preflight read; this read belongs to the write transaction.
            entry = repository.get(entry_id)
            if entry is None:
                return None
            delay = float(min(base * 2**entry.retry_count, cap) * jitter)
            retry_count = entry.retry_count + 1
            now = repository.runtime.clock().now()
            if connection is not None:
                connection.execute(
                    "UPDATE neuro_dead_letters SET retry_count = ?, last_failure_time = ? WHERE entry_id = ?",
                    (retry_count, now.isoformat(), entry_id),
                ).close()
            else:
                entry.retry_count = retry_count
                entry.last_failure_time = now
        repository.runtime.log().info(
            "[DeadLetterQueue] 安排重试: entry_id=%s, retry=%s, delay=%.3fs",
            entry_id,
            retry_count,
            delay,
        )
        return delay

    def stats(self) -> dict[str, Any]:
        repository = self.repository
        with repository.storage.lock:
            if repository.storage.connection is not None:
                aggregate = repository.storage.rows(
                    "SELECT COUNT(*), MIN(first_failure_time) FROM neuro_dead_letters"
                )[0]
                current_size = int(aggregate[0])
                oldest = aggregate[1]
                clock = repository.runtime.clock()
                age = (
                    (clock.now() - clock.fromisoformat(oldest)).total_seconds() / 3600
                    if oldest
                    else 0.0
                )
                by_reason = {
                    row["reason"]: row["cnt"]
                    for row in repository.storage.rows(
                        "SELECT reason, COUNT(*) AS cnt FROM neuro_dead_letters GROUP BY reason"
                    )
                }
            else:
                entries = repository.state.entries
                current_size = len(entries)
                by_reason = {}
                for entry in entries.values():
                    reason = entry.reason.value
                    by_reason[reason] = by_reason.get(reason, 0) + 1
                age = (
                    min(entry.age_seconds for entry in entries.values()) / 3600 if entries else 0.0
                )
            return {
                "current_size": current_size,
                "max_size": repository.max_size,
                **repository.state.stats,
                "by_reason": by_reason,
                "oldest_entry_age_hours": age,
            }

    def triage(self) -> dict[str, list[str]]:
        repository = self.repository
        categories = {
            "retry_exhausted": "retriable",
            "timeout": "retriable",
            "invalid_payload": "fixable",
            "handler_not_found": "fixable",
            "unrecoverable": "poison",
            "circuit_breaker": "poison",
        }
        result: dict[str, list[str]] = {"retriable": [], "fixable": [], "poison": []}
        with repository.storage.lock:
            if repository.storage.connection is not None:
                pairs = [
                    (row["entry_id"], repository.reason_type(row["reason"]).value)
                    for row in fetch_rows(
                        repository.storage.connection,
                        "SELECT entry_id, reason FROM neuro_dead_letters",
                    )
                ]
            else:
                pairs = [
                    (entry_id, entry.reason.value)
                    for entry_id, entry in repository.state.entries.items()
                ]
        for entry_id, reason in pairs:
            result[categories[reason]].append(entry_id)
        return result
