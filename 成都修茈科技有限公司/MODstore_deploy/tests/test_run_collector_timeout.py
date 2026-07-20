"""Tests for ``workflow_scheduler._run_collector_with_timeout`` (2026-07-20 重写).

验证：
- 快返回值透传
- 异常传播（不是吞掉）
- 卡死 fn 在 timeout 内返回 None（且不阻塞调用方）
- 超时后下一次调用仍能正常工作（APScheduler 实例槽位没被占用）
- timeout 值被尊重（短 timeout 比长 timeout 更早返回）
- None 返回值（fn 返回 None）与 timeout 返回 None 不可区分（妥协）
"""

from __future__ import annotations

import threading
import time

import pytest

from modstore_server import workflow_scheduler as ws


def test_fast_return_value_passes_through():
    """快返回 fn 的返回值原样透传。"""
    result = ws._run_collector_with_timeout(
        lambda: 42, label="fast_ok", timeout=5.0
    )
    assert result == 42


def test_exception_propagates():
    """fn 抛异常时调用方也抛（不吞）。"""

    def _boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        ws._run_collector_with_timeout(_boom, label="boom", timeout=5.0)


def test_hanging_fn_returns_none_within_timeout_plus_one_second():
    """卡死 fn 在 timeout 附近返回 None（不阻塞 +1s）。"""
    started = time.monotonic()

    def _hang() -> None:
        time.sleep(10.0)

    result = ws._run_collector_with_timeout(_hang, label="hang", timeout=0.5)
    elapsed = time.monotonic() - started
    assert result is None
    # 关键断言：调用方没被卡 10s，应该在 1.5s 内拿回控制权
    assert elapsed < 1.5, f"elapsed={elapsed:.2f}s, expected < 1.5s"


def test_subsequent_call_works_after_timeout():
    """超时后下一次调用仍能正常工作（实例槽位没被永久占用）。"""

    def _hang() -> None:
        time.sleep(5.0)

    # 第一次：超时返回 None
    r1 = ws._run_collector_with_timeout(_hang, label="hang_then_ok", timeout=0.3)
    assert r1 is None
    # 第二次：完全不同的 fn，应该立即返回正常值
    r2 = ws._run_collector_with_timeout(
        lambda: "still_alive", label="hang_then_ok", timeout=2.0
    )
    assert r2 == "still_alive"


def test_timeout_value_is_respected():
    """timeout=2.0 比 timeout=0.3 更晚返回 None。"""
    started_short = time.monotonic()

    def _hang_short() -> None:
        time.sleep(3.0)

    ws._run_collector_with_timeout(_hang_short, label="timeout_short", timeout=0.3)
    elapsed_short = time.monotonic() - started_short

    started_long = time.monotonic()

    def _hang_long() -> None:
        time.sleep(3.0)

    ws._run_collector_with_timeout(_hang_long, label="timeout_long", timeout=1.2)
    elapsed_long = time.monotonic() - started_long

    # 长超时确实等了更久（差值至少 0.5s，避免抖动 false negative）
    assert elapsed_long - elapsed_short > 0.5, (
        f"short={elapsed_short:.2f}s, long={elapsed_long:.2f}s, "
        f"delta={elapsed_long - elapsed_short:.2f}s"
    )


def test_none_return_indistinguishable_from_timeout():
    """fn 返回 None 与 timeout 返回 None 不可区分（这是同步超时的妥协）。"""

    def _returns_none() -> None:
        return None

    r = ws._run_collector_with_timeout(
        _returns_none, label="none_vs_timeout", timeout=1.0
    )
    # 调用方无法区分：都是 None
    assert r is None


def test_concurrent_futures_thread_pool_naming():
    """ThreadPoolExecutor thread_name_prefix 被 label 化，便于 ops 排查。"""
    captured_threads: list[str] = []
    barrier = threading.Barrier(2, timeout=2.0)

    def _capture_thread_name() -> str:
        captured_threads.append(threading.current_thread().name)
        return "ok"

    # 直接调用 fn，让它报告线程名
    ws._run_collector_with_timeout(
        _capture_thread_name, label="naming_test", timeout=2.0
    )
    assert captured_threads, "thread name not captured"
    assert any("naming_test" in name for name in captured_threads), (
        f"expected 'naming_test' in thread name, got: {captured_threads}"
    )
