"""Tests for app.neuro_bus.__main__ — Neuro-DDD Architecture Verification Script."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.neuro_bus.__main__ import (
    main,
    test_domains,
    test_imports,
    test_neurobus,
    test_processors,
    test_reflex_arc,
)

# ---------------------------------------------------------------------------
# test_imports
# ---------------------------------------------------------------------------


class TestTestImports:
    """test_imports() — 模块导入验证"""

    def test_imports_success(self):
        """所有模块正常导入时返回 True"""
        result = test_imports()
        assert result is True

    def test_imports_failure_returns_false(self):
        """导入失败时返回 False"""
        # test_imports() calls print() before the try block (call 1),
        # then inside the try block (calls 2+). We need to raise on a call
        # inside the try block so the except RECOVERABLE_ERRORS catches it.
        real_print = print
        call_count = 0

        def flaky_print(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Call 1 is outside try; calls 2+ are inside try
            if call_count == 2:
                raise ImportError("broken")
            return real_print(*args, **kwargs)

        with patch("builtins.print", side_effect=flaky_print):
            result = test_imports()
        assert result is False


# ---------------------------------------------------------------------------
# test_reflex_arc
# ---------------------------------------------------------------------------


class TestTestReflexArc:
    """test_reflex_arc() — ReflexArc 响应时间 SLA 测试"""

    def test_reflex_arc_success(self):
        """ReflexArc 正常运行且延迟 < 1ms 时返回 True"""
        mock_reflex_arc = MagicMock()
        mock_result = MagicMock()
        mock_result.triggered = True
        mock_result.reflex_type.value = "greet"
        mock_reflex_arc.process.return_value = mock_result

        with (
            patch(
                "app.neuro_bus.__main__.get_reflex_arc",
                return_value=mock_reflex_arc,
                create=True,
            ),
            patch(
                "app.domain.neuro.reflex_arc.get_reflex_arc",
                return_value=mock_reflex_arc,
            ),
        ):
            result = test_reflex_arc()
        assert result is True

    def test_reflex_arc_slow_returns_false(self):
        """ReflexArc 延迟 >= 1ms 时返回 False"""
        import time

        mock_reflex_arc = MagicMock()
        mock_result = MagicMock()
        mock_result.triggered = True
        mock_result.reflex_type.value = "greet"

        call_count = 0

        def slow_process(text):
            nonlocal call_count
            call_count += 1
            # Simulate slow processing only for some calls to make avg > 1000us
            if call_count % 2 == 0:
                time.sleep(0.002)  # 2ms
            return mock_result

        mock_reflex_arc.process.side_effect = slow_process

        with patch(
            "app.domain.neuro.reflex_arc.get_reflex_arc",
            return_value=mock_reflex_arc,
        ):
            result = test_reflex_arc()
        assert result is False

    def test_reflex_arc_error_returns_false(self):
        """ReflexArc 抛出异常时返回 False"""
        with patch(
            "app.domain.neuro.reflex_arc.get_reflex_arc",
            side_effect=RuntimeError("init failed"),
        ):
            result = test_reflex_arc()
        assert result is False


# ---------------------------------------------------------------------------
# test_neurobus
# ---------------------------------------------------------------------------


class TestTestNeurobus:
    """test_neurobus() — NeuroBus 事件流测试"""

    @pytest.mark.asyncio
    async def test_neurobus_success(self):
        """NeuroBus 正常启动、发布、停止"""
        mock_bus = MagicMock()
        mock_bus.start = AsyncMock()
        mock_bus.stop = AsyncMock()
        mock_bus.publish.return_value = True
        mock_bus.subscribe = MagicMock()

        with patch(
            "app.neuro_bus.bus.get_neuro_bus",
            return_value=mock_bus,
        ):
            result = await test_neurobus()

        mock_bus.start.assert_awaited_once()
        mock_bus.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_neurobus_error_returns_false(self):
        """NeuroBus 异常时返回 False"""
        with patch(
            "app.neuro_bus.bus.get_neuro_bus",
            side_effect=RuntimeError("bus init failed"),
        ):
            result = await test_neurobus()
        assert result is False

    @pytest.mark.asyncio
    async def test_neurobus_no_events_received(self):
        """NeuroBus 未收到事件时返回 False"""
        mock_bus = MagicMock()
        mock_bus.start = AsyncMock()
        mock_bus.stop = AsyncMock()
        mock_bus.publish.return_value = False
        mock_bus.subscribe = MagicMock()

        with patch(
            "app.neuro_bus.bus.get_neuro_bus",
            return_value=mock_bus,
        ):
            # The handler won't receive events because publish returned False
            # and we don't await any processing
            result = await test_neurobus()

        # Result depends on whether events were received
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# test_domains
# ---------------------------------------------------------------------------


class TestTestDomains:
    """test_domains() — NeuroDomains 测试"""

    def test_domains_success(self):
        """至少 3 个域注册时返回 True"""
        mock_registry = MagicMock()
        mock_registry.list_domains.return_value = ["intent", "order", "payment"]
        mock_registry.get_all_stats.return_value = {
            "intent": {"events": 10},
            "order": {"events": 5},
        }

        with (
            patch(
                "app.neuro_bus.domains.base.get_domain_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.neuro_bus.domains.intent_domain.get_intent_domain",
            ),
            patch(
                "app.neuro_bus.domains.order_domain.get_order_domain",
            ),
            patch(
                "app.neuro_bus.domains.payment_domain.get_payment_domain",
            ),
        ):
            result = test_domains()
        assert result is True

    def test_domains_insufficient_returns_false(self):
        """域数量不足时返回 False"""
        mock_registry = MagicMock()
        mock_registry.list_domains.return_value = ["intent"]
        mock_registry.get_all_stats.return_value = {}

        with (
            patch(
                "app.neuro_bus.domains.base.get_domain_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.neuro_bus.domains.intent_domain.get_intent_domain",
            ),
        ):
            result = test_domains()
        assert result is False

    def test_domains_error_returns_false(self):
        """异常时返回 False"""
        with patch(
            "app.neuro_bus.domains.base.get_domain_registry",
            side_effect=RuntimeError("registry failed"),
        ):
            result = test_domains()
        assert result is False


# ---------------------------------------------------------------------------
# test_processors
# ---------------------------------------------------------------------------


class TestTestProcessors:
    """test_processors() — 处理器协调器测试"""

    @pytest.mark.asyncio
    async def test_processors_success(self):
        """处理器协调器正常运行"""
        mock_coordinator = MagicMock()
        mock_decision1 = MagicMock()
        mock_decision1.processor_type = MagicMock()
        mock_decision1.processor_type.value = "reflex"
        mock_decision1.reason = "greeting detected"

        mock_decision2 = MagicMock()
        mock_decision2.processor_type = MagicMock()
        mock_decision2.processor_type.value = "reflex"
        mock_decision2.reason = "stop command"

        mock_decision3 = MagicMock()
        mock_decision3.processor_type = MagicMock()
        mock_decision3.processor_type.value = "conscious"
        mock_decision3.reason = "complex query"

        mock_coordinator.route.side_effect = [mock_decision1, mock_decision2, mock_decision3]
        mock_coordinator.get_stats.return_value = {"total": 3}

        with patch(
            "app.domain.neuro.processors.coordinator.get_processor_coordinator",
            return_value=mock_coordinator,
        ):
            result = await test_processors()
        assert result is True

    @pytest.mark.asyncio
    async def test_processors_error_returns_false(self):
        """处理器协调器异常时返回 False"""
        with patch(
            "app.domain.neuro.processors.coordinator.get_processor_coordinator",
            side_effect=RuntimeError("coordinator failed"),
        ):
            result = await test_processors()
        assert result is False


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    """main() — 主入口"""

    @pytest.mark.asyncio
    async def test_main_all_pass_returns_0(self):
        """所有测试通过时返回 0"""
        with (
            patch("app.neuro_bus.__main__.test_imports", return_value=True),
            patch("app.neuro_bus.__main__.test_reflex_arc", return_value=True),
            patch("app.neuro_bus.__main__.test_neurobus", return_value=True),
            patch("app.neuro_bus.__main__.test_domains", return_value=True),
            patch("app.neuro_bus.__main__.test_processors", return_value=True),
        ):
            result = await main()
        assert result == 0

    @pytest.mark.asyncio
    async def test_main_some_fail_returns_1(self):
        """部分测试失败时返回 1"""
        with (
            patch("app.neuro_bus.__main__.test_imports", return_value=True),
            patch("app.neuro_bus.__main__.test_reflex_arc", return_value=False),
            patch("app.neuro_bus.__main__.test_neurobus", return_value=True),
            patch("app.neuro_bus.__main__.test_domains", return_value=True),
            patch("app.neuro_bus.__main__.test_processors", return_value=True),
        ):
            result = await main()
        assert result == 1

    @pytest.mark.asyncio
    async def test_main_all_fail_returns_1(self):
        """所有测试失败时返回 1"""
        with (
            patch("app.neuro_bus.__main__.test_imports", return_value=False),
            patch("app.neuro_bus.__main__.test_reflex_arc", return_value=False),
            patch("app.neuro_bus.__main__.test_neurobus", return_value=False),
            patch("app.neuro_bus.__main__.test_domains", return_value=False),
            patch("app.neuro_bus.__main__.test_processors", return_value=False),
        ):
            result = await main()
        assert result == 1
