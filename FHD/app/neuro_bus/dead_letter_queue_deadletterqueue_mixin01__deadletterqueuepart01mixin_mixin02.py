# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.neuro_bus.dead_letter_queue")


class __DeadLetterQueuePart01MixinPart02Mixin:
    def replay_with_progress(
        self,
        event_type: str | None = None,
        max_age_seconds: float | None = None,
        rate_limit_qps: float = 100.0,
        batch_size: int = 100,
    ) -> _facade().Iterator[tuple[int, int, str]]:
        """
        带进度的重播（生成器）

        支持中途取消（pause_replay 后迭代器会在下一个条目前停止）。

        Args:
            event_type: 筛选特定事件类型
            max_age_seconds: 最大年龄筛选
            rate_limit_qps: 重播速率上限（QPS）
            batch_size: 每批重播数量，批间 sleep

        Yields:
            (replayed_count, total_count, current_entry_id)
        """
        to_replay = self._get_replay_candidates(event_type, max_age_seconds)
        total = len(to_replay)
        replayed = 0
        batch_sleep = batch_size / rate_limit_qps if rate_limit_qps > 0 else 0.0
        for i, entry_id in enumerate(to_replay):
            if self._is_replay_paused():
                _facade().logger.info("[DeadLetterQueue] 重播已暂停，停止于 %s/%s", i, total)
                return
            success, _ = self.replay(entry_id)
            if success:
                replayed += 1
            yield (replayed, total, entry_id)
            if (i + 1) % batch_size == 0 and i + 1 < total:
                if batch_sleep > 0:
                    _facade().time.sleep(batch_sleep)

    def replay_gradual(
        self,
        event_type: str | None = None,
        stages: list[float] | None = None,
        stage_interval: float = 5.0,
        error_threshold: int = 5,
    ) -> dict[str, _facade().Any]:
        """
        灰度重播（分阶段：1% → 10% → 50% → 100%）

        每阶段后检查新增死信数，超阈值自动暂停。

        Args:
            event_type: 筛选特定事件类型
            stages: 灰度阶段列表（默认 [0.01, 0.1, 0.5, 1.0]）
            stage_interval: 阶段间隔秒数
            error_threshold: 新增死信数阈值，超过则自动暂停

        Returns:
            执行报告 dict，含 total / stages_executed / replayed / paused / pause_reason
        """
        if stages is None:
            stages = [0.01, 0.1, 0.5, 1.0]
        to_replay = self._get_replay_candidates(event_type, None)
        total = len(to_replay)
        report: dict[str, _facade().Any] = {
            "total": total,
            "stages_executed": [],
            "replayed": 0,
            "paused": False,
            "pause_reason": None,
        }
        if total == 0:
            return report
        replayed = 0
        for stage_idx, fraction in enumerate(stages):
            if self._is_replay_paused():
                report["paused"] = True
                report["pause_reason"] = "manual_pause"
                break
            target_count = int(total * fraction)
            batch = to_replay[replayed:target_count]
            stage_dlq_before = self._stats["total_entries"]
            for entry_id in batch:
                if self._is_replay_paused():
                    report["paused"] = True
                    report["pause_reason"] = "manual_pause"
                    break
                success, _ = self.replay(entry_id)
                if success:
                    replayed += 1
            stage_dlq_after = self._stats["total_entries"]
            new_dlq_count = stage_dlq_after - stage_dlq_before
            report["stages_executed"].append(
                {
                    "stage": stage_idx,
                    "fraction": fraction,
                    "target": len(batch),
                    "replayed": replayed,
                    "new_dlq": new_dlq_count,
                }
            )
            if new_dlq_count >= error_threshold:
                report["paused"] = True
                report["pause_reason"] = (
                    f"error_threshold_exceeded: {new_dlq_count} >= {error_threshold}"
                )
                self.pause_replay()
                break
            if stage_idx < len(stages) - 1:
                _facade().time.sleep(stage_interval)
        report["replayed"] = replayed
        return report

    def resolve_manually(self, entry_id: str, resolution: str, resolved_by: str) -> bool:
        """
        手动解决死信

        用于人工干预后标记为已处理
        """
        entry = self.dequeue(entry_id)
        if not entry:
            return False
        _facade().logger.info(
            "[DeadLetterQueue] 手动解决: %s (resolution=%s, by=%s)",
            entry_id,
            resolution,
            resolved_by,
        )
        entry.metadata["resolved"] = True
        entry.metadata["resolution"] = resolution
        entry.metadata["resolved_by"] = resolved_by
        entry.metadata["resolved_at"] = _facade().datetime.now().isoformat()
        self._stats["manually_resolved"] += 1
        if self._conn is not None:
            with self._lock:
                self._conn.execute(
                    "\n                    UPDATE neuro_dead_letters\n                    SET is_resolved = 1, metadata = ?\n                    WHERE entry_id = ?\n                    ",
                    (_facade().json.dumps(entry.metadata, ensure_ascii=False), entry_id),
                )
                self._conn.execute("DELETE FROM neuro_dead_letters WHERE entry_id = ?", (entry_id,))
        else:
            self.remove(entry_id)
        return True

    def cleanup_expired(self) -> int:
        """清理过期条目"""
        if self._conn is not None:
            with self._lock:
                cutoff_dt = _facade().datetime.fromtimestamp(
                    _facade().datetime.now().timestamp() - self._retention_seconds
                )
                cur = self._conn.execute(
                    "\n                    DELETE FROM neuro_dead_letters\n                    WHERE first_failure_time < ?\n                    ",
                    (cutoff_dt.isoformat(),),
                )
                expired_count = cur.rowcount
            self._stats["expired"] += expired_count
            if expired_count:
                _facade().logger.info("[DeadLetterQueue] 清理过期条目: %s 个", expired_count)
            return expired_count
        _facade().time.time()
        expired = [
            entry_id
            for entry_id, entry in self._entries.items()
            if entry.age_seconds > self._retention_seconds
        ]
        for entry_id in expired:
            del self._entries[entry_id]
        self._stats["expired"] += len(expired)
        if expired:
            _facade().logger.info("[DeadLetterQueue] 清理过期条目: %s 个", len(expired))
        return len(expired)

    def get_all_entries(self) -> list[_facade().DeadLetterEntry]:
        """获取所有条目"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute("SELECT * FROM neuro_dead_letters")
                return [self._row_to_entry(row) for row in cur.fetchall()]
        return list(self._entries.values())

    def get_entries_by_reason(
        self, reason: _facade().DeadLetterReason
    ) -> list[_facade().DeadLetterEntry]:
        """按原因筛选"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM neuro_dead_letters WHERE reason = ?", (reason.value,)
                )
                return [self._row_to_entry(row) for row in cur.fetchall()]
        return [e for e in self._entries.values() if e.reason == reason]

    def get_entries_by_event_type(self, event_type: str) -> list[_facade().DeadLetterEntry]:
        """按事件类型筛选"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM neuro_dead_letters WHERE event_type = ?", (event_type,)
                )
                return [self._row_to_entry(row) for row in cur.fetchall()]
        return [e for e in self._entries.values() if e.original_event.event_type == event_type]

    def get_stats(self) -> dict[str, _facade().Any]:
        """获取统计信息"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute("SELECT COUNT(*) FROM neuro_dead_letters")
                current_size = cur.fetchone()[0]
                cur = self._conn.execute(
                    "\n                    SELECT reason, COUNT(*) as cnt\n                    FROM neuro_dead_letters\n                    GROUP BY reason\n                    "
                )
                by_reason = {row["reason"]: row["cnt"] for row in cur.fetchall()}
                cur = self._conn.execute("SELECT MIN(first_failure_time) FROM neuro_dead_letters")
                oldest_iso = cur.fetchone()[0]
                if oldest_iso:
                    oldest_age_hours = (
                        _facade().datetime.now() - _facade().datetime.fromisoformat(oldest_iso)
                    ).total_seconds() / 3600
                else:
                    oldest_age_hours = 0
            return {
                "current_size": current_size,
                "max_size": self._max_size,
                **self._stats,
                "by_reason": by_reason,
                "oldest_entry_age_hours": oldest_age_hours,
            }
        by_reason = {}
        for entry in self._entries.values():
            reason = entry.reason.value
            by_reason[reason] = by_reason.get(reason, 0) + 1
        return {
            "current_size": len(self._entries),
            "max_size": self._max_size,
            **self._stats,
            "by_reason": by_reason,
            "oldest_entry_age_hours": min(e.age_seconds for e in self._entries.values()) / 3600
            if self._entries
            else 0,
        }
