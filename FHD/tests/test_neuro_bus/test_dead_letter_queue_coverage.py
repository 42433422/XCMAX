# -*- coding: utf-8 -*-
"""死信队列 (DeadLetterQueue) 真实行为测试。

覆盖入队/出队/移除、重播去重、批量/灰度/进度重播、暂停恢复、
告警抑制与静默、手动解决、过期清理、容量驱逐、退避重试调度、
SQLITE 持久化与内存两种模式，以及 NeuroBus 集成与快捷函数。

所有时间/随机/IO 用 monkeypatch 控制，断言状态与数据正确性。
"""

from __future__ import annotations

import sqlite3

import pytest

import app.neuro_bus.dead_letter_queue as dlq_mod
from app.neuro_bus.dead_letter_queue import (
    AlertSuppressor,
    DeadLetterEntry,
    DeadLetterQueue,
    DeadLetterReason,
    NeuroBusDLQIntegration,
    ReplayDeduplicator,
    enqueue_dead_letter,
    get_dead_letter_queue,
    get_dlq_stats,
)
from app.neuro_bus.events.base import NeuroEvent


def make_event(event_type: str = "test.event", **payload) -> NeuroEvent:
    return NeuroEvent(event_type=event_type, payload=dict(payload) or {"k": "v"})


# ========================================================================
# DeadLetterEntry
# ========================================================================


def test_entry_age_and_to_dict_roundtrip():
    ev = make_event("order.created", order_id=42)
    enq_id = "dlq-abc"
    from datetime import datetime, timedelta

    first = datetime.now() - timedelta(seconds=5)
    entry = DeadLetterEntry(
        entry_id=enq_id,
        original_event=ev,
        reason=DeadLetterReason.TIMEOUT,
        error_message="boom",
        error_stack="trace",
        retry_count=2,
        first_failure_time=first,
        last_failure_time=datetime.now(),
        handler_name="h1",
        metadata={"x": 1},
    )
    # age_seconds 反映 first_failure_time 的流逝
    assert entry.age_seconds >= 5.0
    d = entry.to_dict()
    assert d["entry_id"] == enq_id
    assert d["reason"] == "timeout"
    assert d["original_event"]["event_type"] == "order.created"
    assert d["original_event"]["payload"]["order_id"] == 42
    assert d["retry_count"] == 2
    assert d["handler_name"] == "h1"
    assert d["metadata"] == {"x": 1}
    assert d["age_seconds"] >= 5.0


# ========================================================================
# ReplayDeduplicator
# ========================================================================


def test_deduplicator_fingerprint_deterministic_and_distinct():
    a = ReplayDeduplicator.fingerprint("e1", 0)
    b = ReplayDeduplicator.fingerprint("e1", 0)
    c = ReplayDeduplicator.fingerprint("e1", 1)
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hexdigest


def test_deduplicator_memory_mark_and_check():
    dedup = ReplayDeduplicator(ttl_seconds=100.0)
    assert dedup.is_replayed("e1", 0) is False
    dedup.mark_replayed("e1", 0)
    assert dedup.is_replayed("e1", 0) is True
    # 不同 replay_count 不互相影响
    assert dedup.is_replayed("e1", 1) is False


def test_deduplicator_memory_ttl_expiry(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    dedup = ReplayDeduplicator(ttl_seconds=10.0)
    dedup.mark_replayed("e1", 0)
    assert dedup.is_replayed("e1", 0) is True
    # 时间推进超过 TTL -> 过期且自动删除
    clock["t"] = 1011.0
    assert dedup.is_replayed("e1", 0) is False
    # 已删除，再查仍为 False
    assert dedup.is_replayed("e1", 0) is False


def test_deduplicator_memory_cleanup_expired(monkeypatch):
    clock = {"t": 2000.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    dedup = ReplayDeduplicator(ttl_seconds=10.0)
    dedup.mark_replayed("a", 0)
    dedup.mark_replayed("b", 0)
    clock["t"] = 2011.0
    dedup.mark_replayed("c", 0)  # 这个还没过期
    removed = dedup.cleanup_expired()
    assert removed == 2
    assert dedup.is_replayed("c", 0) is True


def test_deduplicator_sqlite_mark_check_cleanup(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "dedup.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    dedup = ReplayDeduplicator(conn=conn, ttl_seconds=100.0)
    assert dedup.is_replayed("e1", 0) is False
    dedup.mark_replayed("e1", 0)
    assert dedup.is_replayed("e1", 0) is True
    # INSERT OR REPLACE：重复 mark 不报错
    dedup.mark_replayed("e1", 0)
    assert dedup.is_replayed("e1", 0) is True
    # cleanup 不删未过期记录
    assert dedup.cleanup_expired() == 0
    conn.close()


def test_deduplicator_sqlite_cleanup_removes_expired(tmp_path, monkeypatch):
    conn = sqlite3.connect(str(tmp_path / "dedup2.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    clock = {"t": 5000.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    dedup = ReplayDeduplicator(conn=conn, ttl_seconds=10.0)
    dedup.mark_replayed("e1", 0)
    # 推进时间使记录过期；cleanup_expired 用 datetime.now()，所以也要推进 datetime
    import datetime as _dt

    class _FrozenDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime.fromtimestamp(clock["t"])

    monkeypatch.setattr(dlq_mod, "datetime", _FrozenDT)
    clock["t"] = 5020.0
    assert dedup.cleanup_expired() == 1
    conn.close()


# ========================================================================
# AlertSuppressor
# ========================================================================


def test_alert_suppressor_first_fires_then_suppressed(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    sup = AlertSuppressor(suppress_window=60.0, threshold=1)
    fired, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev")
    assert fired is True
    assert count == 1
    # 窗口内第二次：抑制
    fired, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev")
    assert fired is False
    assert count == 2
    stats = sup.get_stats()
    key = "timeout:ev"
    assert stats["groups"][key]["fired"] == 1
    assert stats["groups"][key]["suppressed"] == 1
    assert stats["groups"][key]["total"] == 2


def test_alert_suppressor_window_reset_re_fires(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    sup = AlertSuppressor(suppress_window=60.0, threshold=1)
    assert sup.record_and_check(DeadLetterReason.TIMEOUT, "ev")[0] is True
    # 推进超过窗口：计数重置且可再次告警
    clock["t"] = 200.0
    fired, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev")
    assert fired is True
    assert count == 1  # 窗口外计数被重置


def test_alert_suppressor_threshold_gating(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    sup = AlertSuppressor(suppress_window=60.0, threshold=3)
    # 前两次未达阈值，不告警
    assert sup.record_and_check(DeadLetterReason.TIMEOUT, "ev") == (False, 1)
    assert sup.record_and_check(DeadLetterReason.TIMEOUT, "ev") == (False, 2)
    # 第三次达阈值，告警
    fired, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev")
    assert fired is True
    assert count == 3


def test_alert_suppressor_global_silence(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    sup = AlertSuppressor(suppress_window=60.0, threshold=1)
    sup.silence(50.0)
    fired, count = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev")
    assert fired is False  # 全局静默期
    assert count == 1
    stats = sup.get_stats()
    assert stats["silenced"] is True
    assert stats["silenced_remaining_seconds"] == pytest.approx(50.0)
    # 静默到期后恢复告警
    clock["t"] = 151.0
    fired, _ = sup.record_and_check(DeadLetterReason.TIMEOUT, "ev")
    assert fired is True
    assert sup.get_stats()["silenced"] is False


# ========================================================================
# DeadLetterQueue —— 内存模式核心操作
# ========================================================================


def test_enqueue_dequeue_remove_memory():
    dlq = DeadLetterQueue()
    ev = make_event("a.b", foo=1)
    eid = dlq.enqueue(ev, DeadLetterReason.UNRECOVERABLE, "err", retry_count=2, handler_name="h")
    assert eid.startswith("dlq-")
    entry = dlq.dequeue(eid)
    assert entry is not None
    assert entry.reason == DeadLetterReason.UNRECOVERABLE
    assert entry.error_message == "err"
    assert entry.retry_count == 2
    assert entry.handler_name == "h"
    # envelope 元数据
    assert "enqueue_time" in entry.metadata
    assert entry.metadata["original_event_id"] == ev.metadata.event_id
    assert dlq.get_stats()["total_entries"] == 1
    # 移除
    assert dlq.remove(eid) is True
    assert dlq.dequeue(eid) is None
    assert dlq.remove(eid) is False  # 二次移除返回 False


def test_enqueue_triggers_alert_callback():
    dlq = DeadLetterQueue(alert_threshold=1)
    received = []
    dlq.on_alert(lambda e: received.append(e))
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    assert len(received) == 1
    assert received[0].entry_id == eid
    # metadata 中应注入窗口内同类计数
    assert received[0].metadata["alert_count_in_window"] == 1


def test_alert_suppression_only_first_callback(monkeypatch):
    # 起始时钟须大于 suppress_window，否则首条因 last_alert_ts=0 也被抑制
    clock = {"t": 10000.0}
    monkeypatch.setattr(dlq_mod.time, "time", lambda: clock["t"])
    dlq = DeadLetterQueue(alert_suppress_window=300.0, alert_threshold=1)
    fired = []
    dlq.on_alert(lambda e: fired.append(e.entry_id))
    dlq.enqueue(make_event("dup"), DeadLetterReason.TIMEOUT, "e1", 0)
    dlq.enqueue(make_event("dup"), DeadLetterReason.TIMEOUT, "e2", 0)
    # 同 (reason, event_type) 窗口内只告警一次
    assert len(fired) == 1


def test_alert_callback_exception_swallowed():
    dlq = DeadLetterQueue()

    def boom(_e):
        raise ValueError("callback failed")

    dlq.on_alert(boom)
    # 回调抛 RECOVERABLE_ERROR 不应中断入队
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    assert dlq.dequeue(eid) is not None


def test_silence_alerts_and_stats():
    dlq = DeadLetterQueue()
    dlq.silence_alerts(120.0)
    stats = dlq.get_alert_stats()
    assert stats["silenced"] is True
    assert stats["silenced_remaining_seconds"] > 0


# ========================================================================
# 重播 / 去重
# ========================================================================


def test_replay_success_and_dedup_skip():
    dlq = DeadLetterQueue()
    replayed_events = []
    dlq.on_replay(lambda ev: replayed_events.append(ev))
    eid = dlq.enqueue(make_event("r.ev"), DeadLetterReason.RETRY_EXHAUSTED, "e", retry_count=1)
    ok, reason = dlq.replay(eid)
    assert ok is True
    assert reason == ""
    assert len(replayed_events) == 1
    assert dlq.get_stats()["replayed"] == 1
    # 同一 (entry_id, retry_count) 重复重播被去重跳过
    ok2, reason2 = dlq.replay(eid)
    assert ok2 is False
    assert reason2 == "already_replayed"
    assert len(replayed_events) == 1  # 回调未再次触发


def test_replay_entry_not_found():
    dlq = DeadLetterQueue()
    ok, reason = dlq.replay("dlq-nonexistent")
    assert ok is False
    assert reason == "entry_not_found"


def test_replay_callback_exception_swallowed():
    dlq = DeadLetterQueue()

    def boom(_ev):
        raise RuntimeError("replay handler down")

    dlq.on_replay(boom)
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    ok, reason = dlq.replay(eid)
    # 回调失败仍视为重播成功（异常被吞，标记去重）
    assert ok is True
    assert reason == ""


def test_replay_all_memory_with_filter():
    dlq = DeadLetterQueue()
    seen = []
    dlq.on_replay(lambda ev: seen.append(ev.event_type))
    dlq.enqueue(make_event("type.a"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("type.a"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("type.b"), DeadLetterReason.TIMEOUT, "e", 0)
    # 仅重播 type.a
    count = dlq.replay_all(event_type="type.a", rate_limit_qps=0)
    assert count == 2
    assert seen == ["type.a", "type.a"]


def test_replay_all_batches_sleep(monkeypatch):
    dlq = DeadLetterQueue()
    dlq.on_replay(lambda ev: None)
    for _ in range(5):
        dlq.enqueue(make_event("t"), DeadLetterReason.TIMEOUT, "e", 0)
    sleeps = []
    monkeypatch.setattr(dlq_mod.time, "sleep", lambda s: sleeps.append(s))
    count = dlq.replay_all(batch_size=2, rate_limit_qps=100.0)
    assert count == 5
    # 5 条、batch=2 -> 第2、4条后 sleep（第6条不存在），每次 sleep = 2/100
    assert sleeps == [pytest.approx(0.02), pytest.approx(0.02)]


def test_replay_all_pause_stops_early():
    dlq = DeadLetterQueue()
    dlq.on_replay(lambda ev: None)
    for _ in range(3):
        dlq.enqueue(make_event("t"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.pause_replay()
    assert dlq._is_replay_paused() is True
    count = dlq.replay_all(rate_limit_qps=0)
    assert count == 0  # 暂停后立即停止
    dlq.resume_replay()
    assert dlq._is_replay_paused() is False
    assert dlq.replay_all(rate_limit_qps=0) == 3


def test_replay_with_progress_yields_and_pauses(monkeypatch):
    dlq = DeadLetterQueue()
    dlq.on_replay(lambda ev: None)
    for _ in range(4):
        dlq.enqueue(make_event("t"), DeadLetterReason.TIMEOUT, "e", 0)
    monkeypatch.setattr(dlq_mod.time, "sleep", lambda s: None)
    gen = dlq.replay_with_progress(batch_size=2, rate_limit_qps=100.0)
    first = next(gen)
    assert first[0] == 1  # replayed
    assert first[1] == 4  # total
    second = next(gen)
    assert second[0] == 2
    # 中途暂停：下一个条目前停止
    dlq.pause_replay()
    remaining = list(gen)
    assert remaining == []  # 生成器提前 return


def test_replay_gradual_empty():
    dlq = DeadLetterQueue()
    report = dlq.replay_gradual()
    assert report["total"] == 0
    assert report["replayed"] == 0
    assert report["paused"] is False


def test_replay_gradual_full_run(monkeypatch):
    dlq = DeadLetterQueue()
    dlq.on_replay(lambda ev: None)
    for _ in range(10):
        dlq.enqueue(make_event("g"), DeadLetterReason.TIMEOUT, "e", 0)
    monkeypatch.setattr(dlq_mod.time, "sleep", lambda s: None)
    report = dlq.replay_gradual(stages=[0.1, 0.5, 1.0], stage_interval=0.0)
    assert report["total"] == 10
    assert report["replayed"] == 10
    assert report["paused"] is False
    assert len(report["stages_executed"]) == 3
    # 阶段目标递增
    assert report["stages_executed"][0]["fraction"] == 0.1


def test_replay_gradual_manual_pause_before_start():
    dlq = DeadLetterQueue()
    for _ in range(5):
        dlq.enqueue(make_event("g"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.pause_replay()
    report = dlq.replay_gradual(stages=[0.5, 1.0], stage_interval=0.0)
    assert report["paused"] is True
    assert report["pause_reason"] == "manual_pause"
    assert report["replayed"] == 0


def test_replay_all_memory_max_age_filter():
    dlq = DeadLetterQueue()
    dlq.on_replay(lambda ev: None)
    from datetime import datetime, timedelta

    young = dlq.enqueue(make_event("t"), DeadLetterReason.TIMEOUT, "e", 0)
    old = dlq.enqueue(make_event("t"), DeadLetterReason.TIMEOUT, "e", 0)
    # 让 old 超过 max_age
    dlq._entries[old].first_failure_time = datetime.now() - timedelta(seconds=100)
    cands = dlq._get_replay_candidates(max_age_seconds=10.0)
    assert young in cands
    assert old not in cands


def test_replay_gradual_inner_pause(monkeypatch):
    """灰度重播在阶段内逐条时遇到 pause 立即停止。"""
    dlq = DeadLetterQueue()
    monkeypatch.setattr(dlq_mod.time, "sleep", lambda s: None)
    for _ in range(10):
        dlq.enqueue(make_event("g"), DeadLetterReason.TIMEOUT, "e", 0)

    calls = {"n": 0}

    def pause_after_two(_ev):
        calls["n"] += 1
        if calls["n"] == 2:
            dlq.pause_replay()

    dlq.on_replay(pause_after_two)
    report = dlq.replay_gradual(stages=[1.0], stage_interval=0.0)
    assert report["paused"] is True
    assert report["pause_reason"] == "manual_pause"


def test_replay_gradual_error_threshold_pauses(monkeypatch):
    dlq = DeadLetterQueue()
    monkeypatch.setattr(dlq_mod.time, "sleep", lambda s: None)
    for _ in range(10):
        dlq.enqueue(make_event("g"), DeadLetterReason.TIMEOUT, "e", 0)

    # 重播回调每次再次入队（制造新增死信），触发 error_threshold
    def reenqueue(_ev):
        dlq.enqueue(make_event("new"), DeadLetterReason.UNRECOVERABLE, "again", 0)

    dlq.on_replay(reenqueue)
    report = dlq.replay_gradual(stages=[0.5, 1.0], stage_interval=0.0, error_threshold=3)
    assert report["paused"] is True
    assert "error_threshold_exceeded" in report["pause_reason"]
    # 触发后熔断暂停标志被置位
    assert dlq._is_replay_paused() is True


# ========================================================================
# 手动解决 / 过期清理 / 驱逐
# ========================================================================


def test_resolve_manually_memory():
    dlq = DeadLetterQueue()
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.UNRECOVERABLE, "e", 0)
    assert dlq.resolve_manually(eid, "fixed root cause", "alice") is True
    # 解决后从队列移除
    assert dlq.dequeue(eid) is None
    assert dlq.get_stats()["manually_resolved"] == 1
    # 不存在条目返回 False
    assert dlq.resolve_manually("dlq-nope", "x", "bob") is False


def test_cleanup_expired_memory(monkeypatch):
    # retention 很短，制造过期
    dlq = DeadLetterQueue(retention_hours=0)
    eid_old = dlq.enqueue(make_event("old"), DeadLetterReason.TIMEOUT, "e", 0)
    # 强制 age_seconds 大于 retention (=0)
    entry = dlq._entries[eid_old]
    from datetime import datetime, timedelta

    entry.first_failure_time = datetime.now() - timedelta(seconds=10)
    removed = dlq.cleanup_expired()
    assert removed == 1
    assert dlq.get_stats()["expired"] == 1
    assert dlq.dequeue(eid_old) is None


def test_evict_oldest_on_capacity_memory():
    dlq = DeadLetterQueue(max_size=2)
    from datetime import datetime, timedelta

    e1 = dlq.enqueue(make_event("a"), DeadLetterReason.TIMEOUT, "e", 0)
    # 让 e1 最老
    dlq._entries[e1].first_failure_time = datetime.now() - timedelta(seconds=100)
    e2 = dlq.enqueue(make_event("b"), DeadLetterReason.TIMEOUT, "e", 0)
    # 第三次入队触发驱逐最老 (e1)
    e3 = dlq.enqueue(make_event("c"), DeadLetterReason.TIMEOUT, "e", 0)
    assert dlq.dequeue(e1) is None
    assert dlq.dequeue(e2) is not None
    assert dlq.dequeue(e3) is not None
    assert len(dlq.get_all_entries()) == 2


# ========================================================================
# 查询 / 分类
# ========================================================================


def test_get_entries_filters_memory():
    dlq = DeadLetterQueue()
    dlq.enqueue(make_event("type.x"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("type.y"), DeadLetterReason.UNRECOVERABLE, "e", 0)
    assert len(dlq.get_all_entries()) == 2
    assert len(dlq.get_entries_by_reason(DeadLetterReason.TIMEOUT)) == 1
    assert len(dlq.get_entries_by_event_type("type.y")) == 1


def test_triage_entries_memory():
    dlq = DeadLetterQueue()
    dlq.enqueue(make_event("a"), DeadLetterReason.RETRY_EXHAUSTED, "e", 0)  # retriable
    dlq.enqueue(make_event("b"), DeadLetterReason.TIMEOUT, "e", 0)  # retriable
    dlq.enqueue(make_event("c"), DeadLetterReason.INVALID_PAYLOAD, "e", 0)  # fixable
    dlq.enqueue(make_event("d"), DeadLetterReason.HANDLER_NOT_FOUND, "e", 0)  # fixable
    dlq.enqueue(make_event("e"), DeadLetterReason.UNRECOVERABLE, "e", 0)  # poison
    dlq.enqueue(make_event("f"), DeadLetterReason.CIRCUIT_BREAKER, "e", 0)  # poison
    triage = dlq.triage_entries()
    assert len(triage["retriable"]) == 2
    assert len(triage["fixable"]) == 2
    assert len(triage["poison"]) == 2


def test_get_stats_by_reason_memory():
    dlq = DeadLetterQueue(max_size=99)
    dlq.enqueue(make_event("a"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("b"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("c"), DeadLetterReason.UNRECOVERABLE, "e", 0)
    stats = dlq.get_stats()
    assert stats["current_size"] == 3
    assert stats["max_size"] == 99
    assert stats["by_reason"]["timeout"] == 2
    assert stats["by_reason"]["unrecoverable"] == 1
    assert stats["oldest_entry_age_hours"] >= 0


def test_get_stats_empty_memory():
    dlq = DeadLetterQueue()
    stats = dlq.get_stats()
    assert stats["current_size"] == 0
    assert stats["oldest_entry_age_hours"] == 0


# ========================================================================
# 退避重试调度
# ========================================================================


def test_schedule_retry_backoff_and_jitter(monkeypatch):
    dlq = DeadLetterQueue()
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", retry_count=2)
    # 固定 random -> jitter_multiplier = 0.5 + 1.0*0.5 = 1.0
    monkeypatch.setattr(dlq_mod.random, "random", lambda: 1.0)
    delay = dlq.schedule_retry(eid, base=0.5, cap=30.0)
    # exponential = min(0.5 * 2**2, 30) = 2.0; * 1.0 = 2.0
    assert delay == pytest.approx(2.0)
    # retry_count 自增，last_failure_time 更新
    entry = dlq.dequeue(eid)
    assert entry.retry_count == 3


def test_schedule_retry_cap(monkeypatch):
    dlq = DeadLetterQueue()
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", retry_count=20)
    monkeypatch.setattr(dlq_mod.random, "random", lambda: 0.0)  # multiplier = 0.5
    delay = dlq.schedule_retry(eid, base=0.5, cap=30.0)
    # exponential capped at 30; * 0.5 = 15
    assert delay == pytest.approx(15.0)


def test_schedule_retry_missing_entry():
    dlq = DeadLetterQueue()
    assert dlq.schedule_retry("dlq-missing") is None


# ========================================================================
# SQLITE 持久化模式
# ========================================================================


def test_sqlite_enqueue_dequeue_persist(tmp_path):
    db = str(tmp_path / "dlq.db")
    dlq = DeadLetterQueue(storage_path=db)
    ev = make_event("sql.ev", n=7)
    eid = dlq.enqueue(ev, DeadLetterReason.RETRY_EXHAUSTED, "boom", retry_count=3, handler_name="h")
    # 反序列化往返
    entry = dlq.dequeue(eid)
    assert entry is not None
    assert entry.reason == DeadLetterReason.RETRY_EXHAUSTED
    assert entry.retry_count == 3
    assert entry.handler_name == "h"
    assert entry.original_event.event_type == "sql.ev"
    assert entry.original_event.payload["n"] == 7
    # 新实例从同一文件读取 -> 真持久化
    dlq2 = DeadLetterQueue(storage_path=db)
    assert dlq2.dequeue(eid) is not None
    assert dlq2.get_stats()["current_size"] == 1


def test_sqlite_remove_and_missing(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    assert dlq.dequeue("dlq-missing") is None
    assert dlq.remove("dlq-missing") is False
    assert dlq.remove(eid) is True
    assert dlq.dequeue(eid) is None


def test_sqlite_replay_dedup(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    replayed = []
    dlq.on_replay(lambda ev: replayed.append(ev))
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", retry_count=0)
    ok, _ = dlq.replay(eid)
    assert ok is True
    ok2, reason2 = dlq.replay(eid)
    assert ok2 is False
    assert reason2 == "already_replayed"
    assert len(replayed) == 1


def test_sqlite_resolve_manually(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.UNRECOVERABLE, "e", 0)
    assert dlq.resolve_manually(eid, "patched", "ops") is True
    # 解决后从活动队列移除
    assert dlq.dequeue(eid) is None
    assert dlq.get_stats()["manually_resolved"] == 1


def test_sqlite_get_replay_candidates_no_filter_and_event_type(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    a1 = dlq.enqueue(make_event("type.a"), DeadLetterReason.TIMEOUT, "e", 0)
    a2 = dlq.enqueue(make_event("type.a"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("type.b"), DeadLetterReason.TIMEOUT, "e", 0)
    # 无筛选 -> 全部
    assert len(dlq._get_replay_candidates()) == 3
    # 仅 event_type
    by_type = dlq._get_replay_candidates(event_type="type.a")
    assert set(by_type) == {a1, a2}


def test_sqlite_get_replay_candidates_max_age_is_buggy(tmp_path):
    """已知源码缺陷：SQLITE 模式下传 max_age_seconds 时 SELECT 仅取
    entry_id/first_failure_time 两列，却调用 _row_to_entry（需 event_data 等列），
    导致 IndexError。此用例锁定当前真实行为，便于源码修复后回归捕捉。"""
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    dlq.enqueue(make_event("type.a"), DeadLetterReason.TIMEOUT, "e", 0)
    # 仅 max_age
    with pytest.raises(IndexError):
        dlq._get_replay_candidates(max_age_seconds=1e9)
    # event_type + max_age
    with pytest.raises(IndexError):
        dlq._get_replay_candidates(event_type="type.a", max_age_seconds=1e9)


def test_sqlite_replay_all_filter(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    dlq.on_replay(lambda ev: None)
    dlq.enqueue(make_event("type.a"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("type.a"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("type.b"), DeadLetterReason.TIMEOUT, "e", 0)
    assert dlq.replay_all(event_type="type.a", rate_limit_qps=0) == 2


def test_sqlite_cleanup_expired(tmp_path, monkeypatch):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"), retention_hours=1)
    # 直接写一条很老的记录
    eid = dlq.enqueue(make_event("old"), DeadLetterReason.TIMEOUT, "e", 0)
    import datetime as _dt

    old_iso = (_dt.datetime.now() - _dt.timedelta(hours=5)).isoformat()
    dlq._conn.execute(
        "UPDATE neuro_dead_letters SET first_failure_time = ? WHERE entry_id = ?",
        (old_iso, eid),
    )
    removed = dlq.cleanup_expired()
    assert removed == 1
    assert dlq.get_stats()["expired"] == 1


def test_sqlite_evict_oldest_on_capacity(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"), max_size=2)
    import datetime as _dt

    e1 = dlq.enqueue(make_event("a"), DeadLetterReason.TIMEOUT, "e", 0)
    old_iso = (_dt.datetime.now() - _dt.timedelta(hours=5)).isoformat()
    dlq._conn.execute(
        "UPDATE neuro_dead_letters SET first_failure_time = ? WHERE entry_id = ?",
        (old_iso, e1),
    )
    dlq.enqueue(make_event("b"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("c"), DeadLetterReason.TIMEOUT, "e", 0)  # 触发驱逐
    assert dlq.dequeue(e1) is None
    assert dlq.get_stats()["current_size"] == 2


def test_sqlite_get_stats_and_triage(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    dlq.enqueue(make_event("a"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("b"), DeadLetterReason.UNRECOVERABLE, "e", 0)
    stats = dlq.get_stats()
    assert stats["current_size"] == 2
    assert stats["by_reason"]["timeout"] == 1
    assert stats["oldest_entry_age_hours"] >= 0
    triage = dlq.triage_entries()
    assert len(triage["retriable"]) == 1
    assert len(triage["poison"]) == 1


def test_sqlite_triage_all_categories(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    dlq.enqueue(make_event("a"), DeadLetterReason.RETRY_EXHAUSTED, "e", 0)  # retriable
    dlq.enqueue(make_event("b"), DeadLetterReason.INVALID_PAYLOAD, "e", 0)  # fixable
    dlq.enqueue(make_event("c"), DeadLetterReason.HANDLER_NOT_FOUND, "e", 0)  # fixable
    dlq.enqueue(make_event("d"), DeadLetterReason.CIRCUIT_BREAKER, "e", 0)  # poison
    triage = dlq.triage_entries()
    assert len(triage["retriable"]) == 1
    assert len(triage["fixable"]) == 2
    assert len(triage["poison"]) == 1


def test_sqlite_get_entries_by_filters(tmp_path):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    dlq.enqueue(make_event("type.x"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq.enqueue(make_event("type.y"), DeadLetterReason.UNRECOVERABLE, "e", 0)
    assert len(dlq.get_all_entries()) == 2
    assert len(dlq.get_entries_by_reason(DeadLetterReason.TIMEOUT)) == 1
    assert len(dlq.get_entries_by_event_type("type.y")) == 1


def test_sqlite_schedule_retry_updates_db(tmp_path, monkeypatch):
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", retry_count=1)
    monkeypatch.setattr(dlq_mod.random, "random", lambda: 1.0)
    delay = dlq.schedule_retry(eid, base=1.0, cap=100.0)
    # exponential = min(1.0 * 2**1, 100) = 2.0; *1.0
    assert delay == pytest.approx(2.0)
    # DB 中 retry_count 自增到 2
    entry = dlq.dequeue(eid)
    assert entry.retry_count == 2


def test_sqlite_row_to_entry_corrupt_event(tmp_path):
    """event_data 损坏时回退为 __corrupt__ 事件，不抛异常。"""
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    # 损坏 event_data 列
    dlq._conn.execute(
        "UPDATE neuro_dead_letters SET event_data = ? WHERE entry_id = ?",
        ("{not valid json", eid),
    )
    entry = dlq.dequeue(eid)
    assert entry is not None
    assert entry.original_event.event_type == "__corrupt__"


def test_sqlite_row_to_entry_corrupt_metadata(tmp_path):
    """metadata 损坏时回退为空 dict。"""
    dlq = DeadLetterQueue(storage_path=str(tmp_path / "d.db"))
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    dlq._conn.execute(
        "UPDATE neuro_dead_letters SET metadata = ? WHERE entry_id = ?",
        ("{bad json", eid),
    )
    entry = dlq.dequeue(eid)
    assert entry is not None
    assert entry.metadata == {}


def test_sqlite_creates_parent_dir(tmp_path):
    nested = tmp_path / "sub" / "deep" / "dlq.db"
    assert not nested.parent.exists()
    dlq = DeadLetterQueue(storage_path=str(nested))
    assert nested.parent.exists()
    eid = dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    assert dlq.dequeue(eid) is not None


# ========================================================================
# NeuroBus 集成
# ========================================================================


def test_integration_handle_failure_reason_mapping():
    integ = NeuroBusDLQIntegration()
    ev = make_event("x")
    # retry_count >= max_retries -> RETRY_EXHAUSTED
    eid = integ.handle_failure(ev, RuntimeError("x"), retry_count=3)
    assert integ.dlq.dequeue(eid).reason == DeadLetterReason.RETRY_EXHAUSTED


def test_integration_handle_failure_timeout():
    integ = NeuroBusDLQIntegration()
    eid = integ.handle_failure(make_event("x"), TimeoutError("t"), retry_count=0)
    assert integ.dlq.dequeue(eid).reason == DeadLetterReason.TIMEOUT


def test_integration_handle_failure_value_error():
    integ = NeuroBusDLQIntegration()
    eid = integ.handle_failure(make_event("x"), ValueError("bad"), retry_count=0)
    assert integ.dlq.dequeue(eid).reason == DeadLetterReason.INVALID_PAYLOAD


def test_integration_handle_failure_unrecoverable():
    integ = NeuroBusDLQIntegration()
    eid = integ.handle_failure(make_event("x"), KeyError("k"), retry_count=0)
    assert integ.dlq.dequeue(eid).reason == DeadLetterReason.UNRECOVERABLE


def test_integration_setup_replay_to_bus():
    class FakeBus:
        def __init__(self):
            self.published = []

        def publish(self, ev):
            self.published.append(ev)

    bus = FakeBus()
    integ = NeuroBusDLQIntegration()
    integ.setup_replay_to_bus(bus)
    eid = integ.dlq.enqueue(make_event("x"), DeadLetterReason.TIMEOUT, "e", 0)
    integ.dlq.replay(eid)
    assert len(bus.published) == 1


def test_integration_uses_provided_dlq():
    custom = DeadLetterQueue(max_size=5)
    integ = NeuroBusDLQIntegration(dlq=custom)
    assert integ.dlq is custom


# ========================================================================
# 全局单例与快捷函数
# ========================================================================


def test_get_dead_letter_queue_singleton(monkeypatch):
    monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
    a = get_dead_letter_queue()
    b = get_dead_letter_queue()
    assert a is b


def test_enqueue_dead_letter_shortcut_valid_reason(monkeypatch):
    monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
    eid = enqueue_dead_letter(make_event("x"), "timeout", "boom", retry_count=1)
    dlq = get_dead_letter_queue()
    entry = dlq.dequeue(eid)
    assert entry.reason == DeadLetterReason.TIMEOUT
    assert entry.retry_count == 1


def test_enqueue_dead_letter_shortcut_invalid_reason_defaults(monkeypatch):
    monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
    eid = enqueue_dead_letter(make_event("x"), "not_a_real_reason", "boom")
    dlq = get_dead_letter_queue()
    # 非法 reason 字符串回退 UNRECOVERABLE
    assert dlq.dequeue(eid).reason == DeadLetterReason.UNRECOVERABLE


def test_get_dlq_stats_shortcut(monkeypatch):
    monkeypatch.setattr(dlq_mod, "_dlq_instance", None)
    enqueue_dead_letter(make_event("x"), "timeout", "boom")
    stats = get_dlq_stats()
    assert stats["current_size"] >= 1
