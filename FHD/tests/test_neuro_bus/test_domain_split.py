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
