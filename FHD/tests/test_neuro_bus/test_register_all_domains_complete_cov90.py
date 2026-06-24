"""真实行为测试：register_all_domains_complete 模块的注册流程与错误分支。

覆盖目标（此前未测的未覆盖行）：
- 每个领域的成功注册路径（register_* 被调用 + logger.info）。
- 各领域 ``except RECOVERABLE_ERRORS`` 错误分支（注册函数抛可恢复错误 → 不冒泡）。
- order/customer/.../conversation 的 ``except ImportError`` "不存在，跳过" 分支。
- application_event_consumers 消费者注册成功 + 失败分支。
- register_all_domains_complete 基础领域注册失败的 ``except RECOVERABLE_ERRORS`` warning 分支。
- init_neuro_bus_complete 的「有运行循环 → create_task」分支。

策略：领域 handler 是函数内 ``from app.neuro_bus.domains.X import register_X``。
- 注入伪模块到 sys.modules（带受控的 register_* MagicMock）→ 走成功/错误分支。
- 向 sys.modules 注入 ``None`` → 强制该模块 import 抛 ImportError → 走 except ImportError。
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.neuro_bus.register_all_domains_complete import (
    init_bus,
    init_neuro_bus_complete,
    register_all,
    register_all_domains_complete,
    register_domain_handlers_only,
)

# (sys.modules 路径, register 函数属性名) —— 与源文件 from-import 一一对应
DOMAIN_SPECS: list[tuple[str, str]] = [
    ("app.neuro_bus.domains.product_domain_handlers", "register_product_domain_handlers"),
    ("app.neuro_bus.domains.shipment_domain_handlers", "register_shipment_domain_handlers"),
    ("app.neuro_bus.domains.order_domain_handlers", "register_order_domain_handlers"),
    ("app.neuro_bus.domains.customer_domain_handlers", "register_customer_domain_handlers"),
    ("app.neuro_bus.domains.inventory_domain_handlers", "register_inventory_domain_handlers"),
    ("app.neuro_bus.domains.payment_domain_handlers", "register_payment_domain_handlers"),
    ("app.neuro_bus.domains.ocr_domain_handlers", "register_ocr_domain_handlers"),
    ("app.neuro_bus.domains.wechat_domain_handlers", "register_wechat_domain_handlers"),
    ("app.neuro_bus.domains.print_domain_handlers", "register_print_domain_handlers"),
    ("app.neuro_bus.domains.ai_domain_handlers", "register_ai_domain_handlers"),
    ("app.neuro_bus.domains.auth_domain_handlers", "register_auth_domain_handlers"),
    ("app.neuro_bus.domains.material_domain_handlers", "register_material_domain_handlers"),
    (
        "app.neuro_bus.domains.conversation_domain_handlers",
        "register_conversation_domain_handlers",
    ),
]

APP_CONSUMERS_MOD = "app.neuro_bus.domains.application_event_consumers"
APP_CONSUMERS_FN = "register_application_event_consumers"


def _all_success_fakes() -> tuple[dict[str, MagicMock], dict[str, MagicMock]]:
    """构造所有领域 + 消费者的成功伪模块。

    返回 (sys.modules 注入字典, {register函数名: mock} 的查表)。
    """
    fakes: dict[str, MagicMock] = {}
    registers: dict[str, MagicMock] = {}
    for mod_path, fn_name in DOMAIN_SPECS:
        reg = MagicMock(name=fn_name)
        fakes[mod_path] = MagicMock(**{fn_name: reg})
        registers[fn_name] = reg
    consumer_reg = MagicMock(name=APP_CONSUMERS_FN)
    fakes[APP_CONSUMERS_MOD] = MagicMock(**{APP_CONSUMERS_FN: consumer_reg})
    registers[APP_CONSUMERS_FN] = consumer_reg
    return fakes, registers


class TestAllDomainsSuccessPath:
    """全部领域成功注册——覆盖每个领域的成功 register + logger.info 行。"""

    async def test_every_domain_register_called_with_bus(self):
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()

        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        # 13 个领域 + 1 个消费者，全部恰好被调用一次，且参数是同一个 bus
        assert len(registers) == 14
        for fn_name, reg in registers.items():
            reg.assert_called_once_with(mock_bus)

    async def test_uses_get_neuro_bus_when_bus_is_none(self):
        fakes, registers = _all_success_fakes()
        sentinel_bus = MagicMock(name="sentinel_bus")

        with patch(
            "app.neuro_bus.register_all_domains_complete.get_neuro_bus",
            return_value=sentinel_bus,
        ) as get_bus:
            with patch.dict(sys.modules, fakes):
                await register_domain_handlers_only(None)

        get_bus.assert_called_once()
        # 默认 bus 应被透传到每个 register
        for reg in registers.values():
            reg.assert_called_once_with(sentinel_bus)

    async def test_application_consumers_registered(self):
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()

        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        registers[APP_CONSUMERS_FN].assert_called_once_with(mock_bus)


class TestDomainRecoverableErrorBranches:
    """各领域 register 抛 RECOVERABLE_ERRORS —— 覆盖 except RECOVERABLE_ERRORS 分支。

    关键点：错误被吞掉（不冒泡），后续领域仍继续注册。
    """

    @pytest.mark.parametrize(
        "failing_fn",
        [
            "register_product_domain_handlers",  # Product: 无 ImportError 分支
            "register_shipment_domain_handlers",  # Shipment: 无 ImportError 分支
            "register_order_domain_handlers",
            "register_customer_domain_handlers",
            "register_inventory_domain_handlers",
            "register_payment_domain_handlers",
            "register_ocr_domain_handlers",
            "register_wechat_domain_handlers",
            "register_print_domain_handlers",
            "register_ai_domain_handlers",
            "register_auth_domain_handlers",
            "register_material_domain_handlers",
            "register_conversation_domain_handlers",
        ],
    )
    async def test_recoverable_error_is_swallowed_and_others_continue(self, failing_fn):
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()
        # 让目标领域抛 RuntimeError（属于 RECOVERABLE_ERRORS / INFRA_TRANSIENT）
        registers[failing_fn].side_effect = RuntimeError(f"boom-{failing_fn}")

        # 不应抛出
        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        # 失败领域确实被尝试调用
        registers[failing_fn].assert_called_once_with(mock_bus)
        # 至少有另一个领域（消费者）在失败领域之后仍被注册
        registers[APP_CONSUMERS_FN].assert_called_once_with(mock_bus)

    async def test_value_error_is_recoverable(self):
        """ValueError 属于 DATA_SHAPE → 也应被 RECOVERABLE_ERRORS 吞掉。"""
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()
        registers["register_payment_domain_handlers"].side_effect = ValueError("bad shape")

        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        registers["register_payment_domain_handlers"].assert_called_once()
        # 后续 OCR 等仍继续
        registers["register_ocr_domain_handlers"].assert_called_once_with(mock_bus)


class TestDomainImportErrorBranches:
    """import 抛 ImportError —— 覆盖带 except ImportError 的领域「不存在，跳过」分支。

    通过向 sys.modules 注入 None 强制 from-import 抛 ImportError。
    仅针对源码中有专门 ``except ImportError`` 的领域（order 起及之后）。
    """

    @pytest.mark.parametrize(
        "mod_path,later_fn",
        [
            ("app.neuro_bus.domains.order_domain_handlers", "register_customer_domain_handlers"),
            (
                "app.neuro_bus.domains.customer_domain_handlers",
                "register_inventory_domain_handlers",
            ),
            (
                "app.neuro_bus.domains.inventory_domain_handlers",
                "register_payment_domain_handlers",
            ),
            ("app.neuro_bus.domains.payment_domain_handlers", "register_ocr_domain_handlers"),
            ("app.neuro_bus.domains.ocr_domain_handlers", "register_wechat_domain_handlers"),
            ("app.neuro_bus.domains.wechat_domain_handlers", "register_print_domain_handlers"),
            ("app.neuro_bus.domains.print_domain_handlers", "register_ai_domain_handlers"),
            ("app.neuro_bus.domains.ai_domain_handlers", "register_auth_domain_handlers"),
            ("app.neuro_bus.domains.auth_domain_handlers", "register_material_domain_handlers"),
            (
                "app.neuro_bus.domains.material_domain_handlers",
                "register_conversation_domain_handlers",
            ),
            ("app.neuro_bus.domains.conversation_domain_handlers", APP_CONSUMERS_FN),
        ],
    )
    async def test_missing_module_skips_and_continues(self, mod_path, later_fn):
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()
        # 强制该领域模块 import 失败（ImportError 走专门的 except ImportError 分支）
        fakes[mod_path] = None
        # 对应领域的 register 不应被调用
        failing_fn = next(fn for mp, fn in DOMAIN_SPECS if mp == mod_path)

        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        registers[failing_fn].assert_not_called()
        # 紧随其后的领域/消费者仍被注册
        registers[later_fn].assert_called_once_with(mock_bus)

    async def test_product_import_error_hits_recoverable_branch(self):
        """Product 无 except ImportError —— ImportError 由 RECOVERABLE_ERRORS 兜底（ImportError ∈ INFRA_TRANSIENT）。"""
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()
        fakes["app.neuro_bus.domains.product_domain_handlers"] = None

        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        registers["register_product_domain_handlers"].assert_not_called()
        # 后续 Shipment 仍继续（证明 ImportError 被吞、未冒泡）
        registers["register_shipment_domain_handlers"].assert_called_once_with(mock_bus)


class TestApplicationConsumersFailure:
    """消费者注册失败 —— 覆盖 except RECOVERABLE_ERRORS（line 191-192）。

    注意：application_event_consumers 无 except ImportError，故注入 None 会被
    RECOVERABLE_ERRORS 兜底（ImportError ∈ INFRA_TRANSIENT），不冒泡。
    """

    async def test_consumer_register_raises_recoverable_swallowed(self):
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()
        registers[APP_CONSUMERS_FN].side_effect = ConnectionError("redis down")

        # 不应抛出
        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        registers[APP_CONSUMERS_FN].assert_called_once_with(mock_bus)
        # 之前的领域仍正常注册
        registers["register_product_domain_handlers"].assert_called_once_with(mock_bus)

    async def test_consumer_import_error_swallowed_by_recoverable(self):
        fakes, registers = _all_success_fakes()
        mock_bus = MagicMock()
        fakes[APP_CONSUMERS_MOD] = None  # 强制 ImportError

        with patch.dict(sys.modules, fakes):
            await register_domain_handlers_only(mock_bus)

        registers[APP_CONSUMERS_FN].assert_not_called()
        # 整体仍正常完成（product 已注册）
        registers["register_product_domain_handlers"].assert_called_once_with(mock_bus)


class TestRegisterAllDomainsComplete:
    """register_all_domains_complete：基础领域注册 + 委托 handler-only。"""

    async def test_calls_base_then_handlers_only(self):
        mock_bus = MagicMock()
        base_register = MagicMock(name="register_all_neuro_domains")

        with patch(
            "app.neuro_bus.register_all_domains_complete.register_domain_handlers_only",
            new_callable=AsyncMock,
        ) as handlers_only:
            with patch.dict(
                sys.modules,
                {
                    "app.neuro_bus.register_all_neuro_domains": MagicMock(
                        register_all_neuro_domains=base_register
                    )
                },
            ):
                await register_all_domains_complete(mock_bus)

        base_register.assert_called_once()
        handlers_only.assert_awaited_once_with(mock_bus)

    async def test_base_register_failure_is_warned_not_raised(self):
        """基础领域注册抛 RECOVERABLE_ERRORS → warning 分支（line 210-211），不冒泡，仍调用 handlers_only。"""
        mock_bus = MagicMock()
        base_register = MagicMock(side_effect=RuntimeError("base boom"))

        with patch(
            "app.neuro_bus.register_all_domains_complete.register_domain_handlers_only",
            new_callable=AsyncMock,
        ) as handlers_only:
            with patch.dict(
                sys.modules,
                {
                    "app.neuro_bus.register_all_neuro_domains": MagicMock(
                        register_all_neuro_domains=base_register
                    )
                },
            ):
                # 不应抛出
                await register_all_domains_complete(mock_bus)

        base_register.assert_called_once()
        # 即便基础注册失败，handler-only 仍被调用（容错继续）
        handlers_only.assert_awaited_once_with(mock_bus)

    async def test_uses_get_neuro_bus_when_none(self):
        sentinel_bus = MagicMock(name="sentinel")
        base_register = MagicMock()

        with patch(
            "app.neuro_bus.register_all_domains_complete.get_neuro_bus",
            return_value=sentinel_bus,
        ) as get_bus:
            with patch(
                "app.neuro_bus.register_all_domains_complete.register_domain_handlers_only",
                new_callable=AsyncMock,
            ) as handlers_only:
                with patch.dict(
                    sys.modules,
                    {
                        "app.neuro_bus.register_all_neuro_domains": MagicMock(
                            register_all_neuro_domains=base_register
                        )
                    },
                ):
                    await register_all_domains_complete(None)

        get_bus.assert_called_once()
        handlers_only.assert_awaited_once_with(sentinel_bus)


class TestInitNeuroBusComplete:
    """init_neuro_bus_complete：两个循环分支 + 返回值。"""

    def test_no_running_loop_uses_asyncio_run(self):
        """同步调用（无运行循环）→ RuntimeError 分支 → asyncio.run。"""
        sentinel_bus = MagicMock(name="bus")
        runtime = AsyncMock(name="register_neuro_runtime")

        with patch(
            "app.neuro_bus.register_runtime.register_neuro_runtime",
            new=runtime,
        ):
            with patch(
                "app.neuro_bus.register_all_domains_complete.get_neuro_bus",
                return_value=sentinel_bus,
            ):
                result = init_neuro_bus_complete()

        assert result is sentinel_bus
        runtime.assert_awaited_once()

    async def test_running_loop_uses_create_task(self):
        """在运行中的循环内调用 → else 分支 → create_task（line 228）。"""
        sentinel_bus = MagicMock(name="bus")
        ran = {"flag": False}

        async def fake_runtime():
            ran["flag"] = True

        with patch(
            "app.neuro_bus.register_runtime.register_neuro_runtime",
            new=fake_runtime,
        ):
            with patch(
                "app.neuro_bus.register_all_domains_complete.get_neuro_bus",
                return_value=sentinel_bus,
            ):
                result = init_neuro_bus_complete()
                # 让被调度的 task 有机会运行
                await asyncio.sleep(0)

        assert result is sentinel_bus
        assert ran["flag"] is True


class TestAliases:
    """快捷别名身份。"""

    def test_register_all_is_register_all_domains_complete(self):
        assert register_all is register_all_domains_complete

    def test_init_bus_is_init_neuro_bus_complete(self):
        assert init_bus is init_neuro_bus_complete
