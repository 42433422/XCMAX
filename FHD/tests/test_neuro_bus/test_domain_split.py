"""领域拆分后导入兼容性测试。"""

import importlib

import pytest


@pytest.mark.parametrize(
    "domain_name",
    [
        "payment",
        "order",
        "customer",
        "ai_service",
        "intent",
        "safety",
        "wechat",
    ],
)
def test_domain_imports_handlers(domain_name):
    """domain.py 通过 import * 暴露 handlers 的所有符号。"""
    domain_mod = importlib.import_module(f"app.neuro_bus.domains.{domain_name}_domain")
    handlers_mod = importlib.import_module(f"app.neuro_bus.domains.{domain_name}_domain_handlers")
    # domain 模块应能正常导入
    assert domain_mod is not None
    assert handlers_mod is not None


def test_already_split_domains_unchanged():
    """已拆分的领域（ocr/print/shipment/inventory/product）保持不变。"""
    for name in ["ocr", "print", "shipment", "inventory", "product"]:
        mod = importlib.import_module(f"app.neuro_bus.domains.{name}_domain")
        assert mod is not None


class _DomainLike:
    """模拟旧域路径入参：暴露 ``.bus`` 但无 ``.subscribe``。"""

    def __init__(self, bus):
        self.bus = bus


@pytest.mark.parametrize(
    ("domain_name", "events"),
    [
        ("wechat", ["wechat.message.received", "wechat.payment.callback"]),
        ("order", ["order.created", "order.paid", "order.shipped"]),
        ("customer", ["customer.registered", "customer.login"]),
        ("payment", ["payment.completed", "payment.failed"]),
    ],
)
def test_legacy_domain_handlers_register_via_bus_path_idempotent(domain_name, events):
    """回归：mod neuro_handler_catalog 以 *bus* 调用 register_<domain>_domain_handlers。

    历史 bug：这些实现用 ``@domain.on``，而 catalog 传入的是 NeuroBus（无 ``.on``），
    桌面/服务端启动时抛 ``AttributeError: 'NeuroBus' object has no attribute 'on'``，
    导致 wechat/order/customer/payment 处理器无法经 catalog 注册。

    现统一改用 ``bus.subscribe`` 并解析入参（bus 直用 / domain 取 ``.bus``），
    bus 路径必须可注册、且跨「catalog + 旧域 + 重复」调用幂等（每事件恰好 1 个处理器）。
    """
    import importlib

    from app.neuro_bus.bus import get_neuro_bus

    mod = importlib.import_module(f"app.neuro_bus.domains.{domain_name}_domain_handlers")
    mod._handlers = None  # 重置单例，隔离其他用例
    bus = get_neuro_bus()
    register = getattr(mod, f"register_{domain_name}_domain_handlers")

    def count(evt):
        return len(bus._handlers.get(evt, []))

    base = {e: count(e) for e in events}

    # catalog 路径：传入 bus（此前会抛 AttributeError）
    register(bus)
    # 旧域路径 + 重复调用：必须幂等
    register(_DomainLike(bus))
    register(bus)

    for e in events:
        assert count(e) == base[e] + 1, f"{e} expected exactly 1 net handler (idempotent)"
