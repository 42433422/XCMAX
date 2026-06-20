"""测试 register_all_domains_complete 模块 - Neuro 领域事件处理器注册。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.neuro_bus.register_all_domains_complete import (
    init_bus,
    init_neuro_bus_complete,
    register_all,
    register_all_domains_complete,
    register_domain_handlers_only,
)


class TestRegisterDomainHandlersOnly:
    """测试 register_domain_handlers_only 函数。"""

    @pytest.mark.asyncio
    async def test_registers_product_handlers(self):
        mock_bus = MagicMock()
        mock_register = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "app.neuro_bus.domains.product_domain_handlers": MagicMock(
                    register_product_domain_handlers=mock_register
                ),
            },
        ):
            await register_domain_handlers_only(mock_bus)

        mock_register.assert_called_once_with(mock_bus)

    @pytest.mark.asyncio
    async def test_handles_import_error_gracefully(self):
        mock_bus = MagicMock()

        with patch.dict("sys.modules", {}):
            # Should not raise even if modules don't exist
            await register_domain_handlers_only(mock_bus)

    @pytest.mark.asyncio
    async def test_creates_bus_if_none(self):
        mock_bus = MagicMock()
        with patch(
            "app.neuro_bus.register_all_domains_complete.get_neuro_bus",
            return_value=mock_bus,
        ):
            with patch.dict("sys.modules", {}):
                await register_domain_handlers_only(None)

    @pytest.mark.asyncio
    async def test_continues_after_domain_failure(self):
        mock_bus = MagicMock()

        # Product succeeds, shipment fails
        product_register = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "app.neuro_bus.domains.product_domain_handlers": MagicMock(
                    register_product_domain_handlers=product_register
                ),
            },
        ):
            await register_domain_handlers_only(mock_bus)
            # Product should still be registered
            product_register.assert_called_once()


class TestRegisterAllDomainsComplete:
    """测试 register_all_domains_complete 函数。"""

    @pytest.mark.asyncio
    async def test_calls_register_all_neuro_domains(self):
        mock_bus = MagicMock()
        mock_register_all = MagicMock()

        with patch(
            "app.neuro_bus.register_all_domains_complete.register_domain_handlers_only",
            new_callable=AsyncMock,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "app.neuro_bus.register_all_neuro_domains": MagicMock(
                        register_all_neuro_domains=mock_register_all
                    ),
                },
            ):
                await register_all_domains_complete(mock_bus)

        mock_register_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_bus_if_none(self):
        mock_bus = MagicMock()
        with patch(
            "app.neuro_bus.register_all_domains_complete.get_neuro_bus",
            return_value=mock_bus,
        ):
            with patch(
                "app.neuro_bus.register_all_domains_complete.register_domain_handlers_only",
                new_callable=AsyncMock,
            ):
                with patch.dict(
                    "sys.modules",
                    {
                        "app.neuro_bus.register_all_neuro_domains": MagicMock(
                            register_all_neuro_domains=MagicMock()
                        ),
                    },
                ):
                    await register_all_domains_complete(None)


class TestInitNeuroBusComplete:
    """测试 init_neuro_bus_complete 函数。"""

    def test_returns_bus(self):
        mock_bus = MagicMock()
        with patch(
            "app.neuro_bus.register_all_domains_complete.get_neuro_bus",
            return_value=mock_bus,
        ):
            with patch(
                "app.neuro_bus.register_runtime.register_neuro_runtime", new_callable=AsyncMock
            ):
                result = init_neuro_bus_complete()
                assert result is mock_bus


class TestAliases:
    """测试快捷函数别名。"""

    def test_register_all_alias(self):
        assert register_all is register_all_domains_complete

    def test_init_bus_alias(self):
        assert init_bus is init_neuro_bus_complete
