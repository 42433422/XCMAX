"""HealthMonitor 安全闭环自愈 —— 事件存储缺失 / append 失败 fail-safe 契约测试。

覆盖：
- 闭环前置门：incident 接收单必须成功 append 之后 handler 才能执行
- append 抛 RuntimeError（含秘密）-> 不调用 handler、不报告恢复、返回原始健康结果
- outcome 返回 evidence_unavailable / recovered=False / handler_invoked=False /
  reason_code=event_store_unavailable，且日志与 outcome 不泄漏原始异常秘密
- 事件存储缺失（store=None）同样 fail-safe
"""

from __future__ import annotations

import pytest

from app.neuro_bus.health_monitor import (
    REASON_EVENT_STORE_UNAVAILABLE,
    STATUS_EVIDENCE_UNAVAILABLE,
    HealthCheckResult,
    HealthMonitor,
    HealthStatus,
)


def _result(component: str, status: HealthStatus, message: str = "msg") -> HealthCheckResult:
    return HealthCheckResult(component=component, status=status, message=message, latency_ms=0.1)


class _RaisingEventStore:
    """append 总是抛 RuntimeError 且携带一个秘密字符串的假事件存储。"""

    def __init__(self, secret: str):
        self.secret = secret
        self.append_calls = 0

    def append(self, event, stream_id=None):
        self.append_calls += 1
        raise RuntimeError(self.secret)


def _fresh_monitor(event_store=None) -> HealthMonitor:
    # 不保留默认检查，避免 postcondition 复检串到其它组件
    m = HealthMonitor(check_interval_seconds=60, event_store=event_store)
    for name in ("neuro_bus", "event_queue", "memory"):
        m.unregister_check(name)
    return m


@pytest.mark.asyncio
async def test_run_check_store_append_failure_no_handler_no_recovery_no_leak(caplog):
    """run_check 自动路径：append 抛 RuntimeError 时绝不调用 handler、绝不报告恢复、
    返回原始健康结果，且日志/接收单不泄漏秘密。"""
    secret = "TOP-SECRET-STORE-BOOM"
    store = _RaisingEventStore(secret)
    calls = []
    m = _fresh_monitor(event_store=store)

    def check():
        return _result("db", HealthStatus.UNHEALTHY, "down")

    def handler(result):
        calls.append(result)

    m.register_check("db", check)
    m.register_remediation("db", "restart_db", handler)

    with caplog.at_level("ERROR", logger="app.neuro_bus.health_monitor"):
        result = await m.run_check("db")

    # 返回原始健康结果（不崩溃、不吞并）
    assert result is not None
    assert result.status == HealthStatus.UNHEALTHY
    # handler 绝不执行
    assert calls == []
    # 绝不报告恢复：未决 incident 被清除，且无 recovery 接收单
    assert m._open_incidents.get("db") is None
    assert not m._recovery_emitted
    # 前置门确实尝试过写 incident 接收单（即 append 被调用过）
    assert store.append_calls >= 1
    # 日志绝不泄漏原始异常细节
    assert secret not in caplog.text
    assert "BOOM" not in caplog.text


@pytest.mark.asyncio
async def test_run_remediation_evidence_unavailable_outcome_no_leak(caplog):
    """事件存储 append 失败 -> evidence_unavailable / recovered=False / handler 未执行，
    且 outcome 与日志均不携带原始异常秘密。"""
    secret = "TOP-SECRET-STORE-BOOM"
    store = _RaisingEventStore(secret)
    calls = []
    m = _fresh_monitor(event_store=store)
    m.register_remediation("db", "restart_db", lambda r: calls.append(r))

    with caplog.at_level("ERROR", logger="app.neuro_bus.health_monitor"):
        outcome = await m.run_remediation_closed_loop(_result("db", HealthStatus.UNHEALTHY, "down"))

    assert outcome.status == STATUS_EVIDENCE_UNAVAILABLE
    assert outcome.recovered is False
    assert outcome.handler_invoked is False
    assert outcome.reason_code == REASON_EVENT_STORE_UNAVAILABLE
    assert calls == []  # 绝不调用 handler
    # outcome / 日志绝不泄漏秘密
    assert secret not in str(outcome)
    assert "BOOM" not in str(outcome)
    assert secret not in caplog.text
    assert "BOOM" not in caplog.text


@pytest.mark.asyncio
async def test_run_check_absent_store_fails_safe_no_handler():
    """事件存储缺失（store=None）时 run_check 自动路径同样 fail-safe：不调用 handler、
    不报告恢复、返回原始健康结果。"""
    calls = []
    m = _fresh_monitor(event_store=None)  # 不注入事件存储

    def check():
        return _result("db", HealthStatus.UNHEALTHY, "down")

    m.register_check("db", check)
    m.register_remediation("db", "restart_db", lambda r: calls.append(r))

    result = await m.run_check("db")

    assert result is not None
    assert result.status == HealthStatus.UNHEALTHY
    assert calls == []
    assert m._open_incidents.get("db") is None
    assert not m._recovery_emitted


@pytest.mark.asyncio
async def test_run_check_append_failure_blocks_fix_capable_handler(caplog):
    """即使 handler 本可将后置条件修复为 HEALTHY，当事件存储 append 抛含秘密的
    RuntimeError 时，前置门 fail-safe：handler 绝不执行、绝不报告恢复、直接闭环结果
    recovered=False + 固定 event_store_unavailable 原因码，且秘密不泄漏。"""
    secret = "TOP-SECRET-STORE-BOOM"
    store = _RaisingEventStore(secret)
    calls = []
    fixed = {"flag": False}
    m = _fresh_monitor(event_store=store)

    def check():
        return _result("db", HealthStatus.HEALTHY if fixed["flag"] else HealthStatus.UNHEALTHY)

    def handler(result):
        calls.append(result)
        fixed["flag"] = True  # 若被调用，本可将后置条件修复为 HEALTHY

    m.register_check("db", check)
    m.register_remediation("db", "restart_db", handler)

    with caplog.at_level("ERROR", logger="app.neuro_bus.health_monitor"):
        result = await m.run_check("db")

    # run_check 返回原始健康结果（仍不健康，绝不伪造恢复）
    assert result is not None
    assert result.status == HealthStatus.UNHEALTHY
    # 前置门失败 -> handler 绝不执行，即使它本可修复
    assert calls == []
    assert fixed["flag"] is False
    assert m._open_incidents.get("db") is None
    # 无恢复接收单声称
    assert not m._recovery_emitted
    assert store.append_calls >= 1

    # 直接闭环结果：recovered=False + 固定 event_store_unavailable 原因码
    outcome = await m.run_remediation_closed_loop(_result("db", HealthStatus.UNHEALTHY, "down"))
    assert outcome.status == STATUS_EVIDENCE_UNAVAILABLE
    assert outcome.recovered is False
    assert outcome.handler_invoked is False
    assert outcome.reason_code == REASON_EVENT_STORE_UNAVAILABLE
    assert calls == []
    assert fixed["flag"] is False
    assert not m._recovery_emitted

    # 秘密绝不泄漏：outcome / 日志（无接收单可写，故无需遍历 payload）
    assert secret not in str(outcome)
    assert "BOOM" not in str(outcome)
    assert secret not in caplog.text
    assert "BOOM" not in caplog.text


@pytest.mark.asyncio
async def test_run_check_absent_store_evidence_unavailable_outcome():
    """事件存储缺失时 run_check 与直接闭环同样 fail-safe：不调用 handler、
    不报告恢复，直接闭环结果 recovered=False + event_store_unavailable。"""
    calls = []
    m = _fresh_monitor(event_store=None)

    def check():
        return _result("db", HealthStatus.UNHEALTHY, "down")

    m.register_check("db", check)
    m.register_remediation("db", "restart_db", lambda r: calls.append(r))

    result = await m.run_check("db")
    assert result is not None
    assert result.status == HealthStatus.UNHEALTHY
    assert calls == []
    assert m._open_incidents.get("db") is None
    assert not m._recovery_emitted

    outcome = await m.run_remediation_closed_loop(_result("db", HealthStatus.UNHEALTHY, "down"))
    assert outcome.status == STATUS_EVIDENCE_UNAVAILABLE
    assert outcome.recovered is False
    assert outcome.handler_invoked is False
    assert outcome.reason_code == REASON_EVENT_STORE_UNAVAILABLE
    assert calls == []
    assert not m._recovery_emitted
