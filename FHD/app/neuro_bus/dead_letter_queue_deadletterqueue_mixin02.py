# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.neuro_bus.dead_letter_queue")


class _DeadLetterQueuePart02Mixin:
    def triage_entries(self) -> dict[str, list[str]]:
        """
        死信自动分类（对标 Kafka DLT triage）

        按 reason 分类：
        - retriable: RETRY_EXHAUSTED, TIMEOUT（可重试）
        - fixable: INVALID_PAYLOAD, HANDLER_NOT_FOUND（需修复后重播）
        - poison: UNRECOVERABLE, CIRCUIT_BREAKER（毒药消息，不宜重播）

        Returns:
            {"retriable": [...], "fixable": [...], "poison": [...]}
        """
        retriable_reasons = {
            _facade().DeadLetterReason.RETRY_EXHAUSTED,
            _facade().DeadLetterReason.TIMEOUT,
        }
        fixable_reasons = {
            _facade().DeadLetterReason.INVALID_PAYLOAD,
            _facade().DeadLetterReason.HANDLER_NOT_FOUND,
        }
        poison_reasons = {
            _facade().DeadLetterReason.UNRECOVERABLE,
            _facade().DeadLetterReason.CIRCUIT_BREAKER,
        }
        result: dict[str, list[str]] = {"retriable": [], "fixable": [], "poison": []}
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute("SELECT entry_id, reason FROM neuro_dead_letters")
                for row in cur.fetchall():
                    reason = _facade().DeadLetterReason(row["reason"])
                    if reason in retriable_reasons:
                        result["retriable"].append(row["entry_id"])
                    elif reason in fixable_reasons:
                        result["fixable"].append(row["entry_id"])
                    elif reason in poison_reasons:
                        result["poison"].append(row["entry_id"])
        else:
            with self._lock:
                for entry_id, entry in self._entries.items():
                    if entry.reason in retriable_reasons:
                        result["retriable"].append(entry_id)
                    elif entry.reason in fixable_reasons:
                        result["fixable"].append(entry_id)
                    elif entry.reason in poison_reasons:
                        result["poison"].append(entry_id)
        return result

    def on_alert(self, callback: _facade().Callable[[_facade().DeadLetterEntry], None]):
        """注册告警回调"""
        self._alert_callbacks.append(callback)

    def on_replay(self, callback: _facade().Callable[[_facade().NeuroEvent], None]):
        """注册重播回调"""
        self._replay_callbacks.append(callback)

    def _trigger_alert(self, entry: _facade().DeadLetterEntry):
        """
        触发告警（含抑制逻辑）

        按 (reason, event_type) 分组，同组 suppress_window 内只告警一次。
        告警内容含"X 条同类失败"。
        """
        (should_alert, count) = self._alert_suppressor.record_and_check(
            entry.reason, entry.original_event.event_type
        )
        if not should_alert:
            return
        entry.metadata["alert_count_in_window"] = count
        for callback in self._alert_callbacks:
            try:
                callback(entry)
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.error("[DeadLetterQueue] 告警回调失败: %s", e)

    def silence_alerts(self, duration_seconds: float) -> None:
        """
        手动静默告警指定时长

        Args:
            duration_seconds: 静默秒数
        """
        self._alert_suppressor.silence(duration_seconds)
        _facade().logger.info("[DeadLetterQueue] 告警已静默 %s 秒", duration_seconds)

    def get_alert_stats(self) -> dict[str, _facade().Any]:
        """
        获取告警统计（按组分类）

        Returns:
            统计字典，含各组的 fired/suppressed/total 计数、
            是否处于静默状态、抑制窗口和阈值
        """
        return self._alert_suppressor.get_stats()

    def schedule_retry(
        self,
        entry_id: str,
        base: float = _facade().RETRY_BASE_DELAY,
        cap: float = _facade().RETRY_MAX_DELAY,
    ) -> float | None:
        """
        计算并安排下一次重试的退避时间（Non-blocking retry，参考 Kafka DLT 设计）

        - 退避公式：delay = min(base * (2 ** retry_count), cap) * (0.5 + random() * 0.5)
        - jitter 范围 ±25%（实际为 0.5x ~ 1.0x 的乘数）
        - 更新 last_failure_time 和 retry_count
        - 调用方负责按返回的 delay 秒数调度实际重试

        Args:
            entry_id: 死信条目 ID
            base: 基础退避秒数（默认 0.5s）
            cap: 最大退避秒数（默认 30s）

        Returns:
            退避秒数；若条目不存在返回 None
        """
        entry = self.dequeue(entry_id)
        if entry is None:
            _facade().logger.warning(
                "[DeadLetterQueue] schedule_retry 失败：找不到条目 %s", entry_id
            )
            return None
        exponential = min(base * 2**entry.retry_count, cap)
        jitter_multiplier = 0.5 + _facade().random.random() * 0.5
        delay = exponential * jitter_multiplier
        new_retry_count = entry.retry_count + 1
        now = _facade().datetime.now()
        if self._conn is not None:
            with self._lock:
                self._conn.execute(
                    "\n                    UPDATE neuro_dead_letters\n                    SET retry_count = ?, last_failure_time = ?\n                    WHERE entry_id = ?\n                    ",
                    (new_retry_count, now.isoformat(), entry_id),
                )
        else:
            entry.retry_count = new_retry_count
            entry.last_failure_time = now
        _facade().logger.info(
            "[DeadLetterQueue] 安排重试: entry_id=%s, retry=%s, delay=%.3fs",
            entry_id,
            new_retry_count,
            delay,
        )
        return float(delay)

    def _evict_oldest(self):
        """驱逐最老的条目"""
        if self._conn is not None:
            with self._lock:
                cur = self._conn.execute(
                    "\n                    SELECT entry_id FROM neuro_dead_letters\n                    ORDER BY first_failure_time ASC\n                    LIMIT 1\n                    "
                )
                row = cur.fetchone()
                if row is None:
                    return
                oldest_id = row["entry_id"]
                self._conn.execute(
                    "DELETE FROM neuro_dead_letters WHERE entry_id = ?", (oldest_id,)
                )
                _facade().logger.warning("[DeadLetterQueue] 驱逐最老条目: %s", oldest_id)
            return
        if not self._entries:
            return
        oldest = min(self._entries.values(), key=lambda e: e.first_failure_time)
        del self._entries[oldest.entry_id]
        _facade().logger.warning("[DeadLetterQueue] 驱逐最老条目: %s", oldest.entry_id)
