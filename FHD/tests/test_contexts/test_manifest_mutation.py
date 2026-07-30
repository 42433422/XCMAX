"""app/contexts/manifest 变异测试强断言。

覆盖 survived 变异体：
- BoundedContextMeta 字段值验证
- BOUNDED_CONTEXTS 内容验证（6 个 context，精确字段）
- contexts_by_id() 返回值验证
"""

from __future__ import annotations

import pytest

from app.contexts.manifest import BOUNDED_CONTEXTS, BoundedContextMeta, contexts_by_id


# ── BoundedContextMeta 结构验证 ──────────────────────────────


def test_bounded_context_meta_fields():
    """杀死字段名或类型错误的变异。"""
    meta = BoundedContextMeta(
        context_id="test",
        event_prefixes=("test.",),
        aggregate_paths=("app.domain.test",),
        handler_module="app.handlers.test",
    )
    assert meta.context_id == "test"
    assert meta.event_prefixes == ("test.",)
    assert meta.aggregate_paths == ("app.domain.test",)
    assert meta.handler_module == "app.handlers.test"


def test_bounded_context_meta_is_frozen_dataclass():
    """杀死 dataclass 非 frozen 的变异。"""
    meta = BoundedContextMeta(
        context_id="x",
        event_prefixes=("x.",),
        aggregate_paths=("app.domain.x",),
        handler_module="app.handlers.x",
    )
    with pytest.raises(AttributeError):
        meta.context_id = "y"  # type: ignore[misc]


# ── BOUNDED_CONTEXTS 内容验证 ────────────────────────────────


def test_bounded_contexts_count():
    """杀死 context 数量错误的变异。"""
    assert len(BOUNDED_CONTEXTS) == 6


def test_bounded_contexts_exact_ids():
    """杀死 context_id 错误的变异。"""
    expected_ids = {"shipment", "order", "inventory", "product", "customer", "intent"}
    actual_ids = {m.context_id for m in BOUNDED_CONTEXTS}
    assert actual_ids == expected_ids


def test_shipment_context_exact_fields():
    """杀死 shipment context 字段错误的变异。"""
    by_id = contexts_by_id()
    shipment = by_id["shipment"]
    assert shipment.context_id == "shipment"
    assert shipment.event_prefixes == ("shipment.",)
    assert shipment.aggregate_paths == ("app.domain.shipment.aggregates",)
    assert shipment.handler_module == "app.neuro_bus.domains.shipment_domain_handlers"


def test_order_context_exact_fields():
    """杀死 order context 字段错误的变异。"""
    by_id = contexts_by_id()
    order = by_id["order"]
    assert order.context_id == "order"
    assert order.event_prefixes == ("order.",)
    assert order.aggregate_paths == ("app.domain.order",)
    assert order.handler_module == "app.neuro_bus.domains.order_domain_handlers"


def test_inventory_context_exact_fields():
    """杀死 inventory context 字段错误的变异。"""
    by_id = contexts_by_id()
    inventory = by_id["inventory"]
    assert inventory.context_id == "inventory"
    assert inventory.event_prefixes == ("inventory.",)
    assert inventory.aggregate_paths == ("app.domain.inventory", "app.services.inventory_service")
    assert inventory.handler_module == "app.neuro_bus.domains.inventory_domain_handlers"


def test_product_context_exact_fields():
    """杀死 product context 字段错误的变异。"""
    by_id = contexts_by_id()
    product = by_id["product"]
    assert product.context_id == "product"
    assert product.event_prefixes == ("product.",)
    assert product.aggregate_paths == ("app.domain.product",)
    assert product.handler_module == "app.neuro_bus.domains.product_domain_handlers"


def test_customer_context_exact_fields():
    """杀死 customer context 字段错误的变异。"""
    by_id = contexts_by_id()
    customer = by_id["customer"]
    assert customer.context_id == "customer"
    assert customer.event_prefixes == ("customer.",)
    assert customer.aggregate_paths == ("app.domain.customer",)
    assert customer.handler_module == "app.neuro_bus.domains.customer_domain_handlers"


def test_intent_context_exact_fields():
    """杀死 intent context 字段错误的变异。"""
    by_id = contexts_by_id()
    intent = by_id["intent"]
    assert intent.context_id == "intent"
    assert intent.event_prefixes == ("intent.",)
    assert intent.aggregate_paths == ("app.domain.services.intent",)
    assert intent.handler_module == "app.neuro_bus.domains.intent_domain"


# ── contexts_by_id() 验证 ────────────────────────────────────


def test_contexts_by_id_returns_dict():
    """杀死返回类型错误的变异。"""
    result = contexts_by_id()
    assert type(result) is dict


def test_contexts_by_id_keys_match_context_ids():
    """杀死 key 与 context_id 不匹配的变异。"""
    by_id = contexts_by_id()
    expected_keys = {m.context_id for m in BOUNDED_CONTEXTS}
    assert set(by_id.keys()) == expected_keys


def test_contexts_by_id_values_are_exact_objects():
    """杀死值不是原对象的变异。"""
    by_id = contexts_by_id()
    for meta in BOUNDED_CONTEXTS:
        assert by_id[meta.context_id] is meta


def test_contexts_by_id_returns_new_dict_each_call():
    """杀死缓存返回同一对象的变异。"""
    dict1 = contexts_by_id()
    dict2 = contexts_by_id()
    assert dict1 is not dict2  # 每次返回新 dict
    assert dict1 == dict2  # 但内容相同
