"""加强 app/di 变异杀死率：invalidate / lazy / set None / 属性值验证。

覆盖 survived 变异体模式：
- _lazy: is None → ""（假值替换），返回值验证，factory 调用次数
- get_service_registry: 单例身份验证（is 比较）
- set_service_registry(None): 显式 None 与未设置的差异
- reset_service_registry: 重建后新实例
- invalidate_*: 清除后再次访问重建
- get_service_container: 两个分支的精确验证
- ServiceContainer.__slots__: 每个 slot 初始 None 验证
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.di.fastapi_deps import get_service_container
from app.di.registry import (
    ServiceContainer,
    get_service_registry,
    reset_service_registry,
    set_service_registry,
)


@pytest.fixture(autouse=True)
def _isolate():
    reset_service_registry()
    yield
    reset_service_registry()


# ── _lazy 强断言 ─────────────────────────────────────────────


def test_lazy_stores_factory_return_value():
    """杀死 _lazy 中 factory() 返回值被丢弃的变异。"""
    c = ServiceContainer()
    sentinel = {"marker": "unique_value_42"}
    result = c._lazy("_session_service", lambda: sentinel)  # noqa: SLF001
    assert result is sentinel
    assert result["marker"] == "unique_value_42"


def test_lazy_second_call_does_not_invoke_factory():
    """杀死 _lazy 中双重检查条件被修改的变异。"""
    c = ServiceContainer()
    calls = []

    def factory():
        calls.append(1)
        return object()

    first = c._lazy("_auth_service", factory)  # noqa: SLF001
    second = c._lazy("_auth_service", factory)  # noqa: SLF001
    assert first is second
    assert len(calls) == 1


def test_lazy_returns_none_initially_then_factory_value():
    """杀死 _lazy 中 is None → is not None 的条件变异。"""
    c = ServiceContainer()
    assert c._session_service is None  # 初始为 None
    sentinel = object()
    result = c._lazy("_session_service", lambda: sentinel)  # noqa: SLF001
    assert result is sentinel
    assert c._session_service is sentinel  # 存储成功


# ── get_service_registry 强断言 ──────────────────────────────


def test_get_service_registry_returns_exact_same_object():
    """杀死 get_service_registry 每次创建新实例的变异。"""
    a = get_service_registry()
    b = get_service_registry()
    assert a is b  # 必须是同一对象


def test_get_service_registry_returns_service_container_type():
    """杀死返回非 ServiceContainer 的变异。"""
    reg = get_service_registry()
    assert type(reg) is ServiceContainer


# ── set_service_registry 强断言 ──────────────────────────────


def test_set_then_get_returns_exact_custom_container():
    """杀死 set_service_registry 忽略参数的变异。"""
    custom = ServiceContainer()
    set_service_registry(custom)
    assert get_service_registry() is custom


def test_set_none_drops_registry():
    """杀死 set_service_registry(None) 不生效的变异。"""
    first = get_service_registry()
    set_service_registry(None)
    # set None 后，get 会重建
    second = get_service_registry()
    assert first is not second


def test_set_replaces_previous_container():
    """杀死 set 追加而非替换的变异。"""
    c1 = ServiceContainer()
    c2 = ServiceContainer()
    set_service_registry(c1)
    assert get_service_registry() is c1
    set_service_registry(c2)
    assert get_service_registry() is c2
    assert get_service_registry() is not c1


# ── reset_service_registry 强断言 ────────────────────────────


def test_reset_then_get_creates_new_container():
    """杀死 reset 不生效的变异。"""
    first = get_service_registry()
    reset_service_registry()
    second = get_service_registry()
    assert first is not second
    assert type(second) is ServiceContainer


# ── invalidate_* 强断言 ──────────────────────────────────────


def test_invalidate_customer_clears_only_customer():
    """杀死 invalidate 清除错误属性的变异。"""
    c = ServiceContainer()
    c._customer_application_service = object()  # noqa: SLF001
    c._auth_service = object()  # noqa: SLF001  不应被清除
    c.invalidate_customer_application_service()
    assert c._customer_application_service is None  # noqa: SLF001
    assert c._auth_service is not None  # noqa: SLF001  其他属性不受影响


def test_invalidate_shipment_clears_both_core_and_facade():
    """杀死 invalidate_shipment_wiring 只清除一个的变异。"""
    c = ServiceContainer()
    c._shipment_application_service_core = object()  # noqa: SLF001
    c._shipment_event_primary_facade = object()  # noqa: SLF001
    c.invalidate_shipment_wiring()
    assert c._shipment_application_service_core is None  # noqa: SLF001
    assert c._shipment_event_primary_facade is None  # noqa: SLF001


# ── set_template_application_service 强断言 ──────────────────


def test_set_template_stores_exact_value():
    """杀死 set_template 存储错误值的变异。"""
    c = ServiceContainer()
    sentinel = object()
    c.set_template_application_service(sentinel)  # type: ignore[arg-type]
    assert c._template_application_service is sentinel  # noqa: SLF001


def test_set_template_none_clears():
    """杀死 set_template(None) 不生效的变异。"""
    c = ServiceContainer()
    c.set_template_application_service(object())  # type: ignore[arg-type]
    c.set_template_application_service(None)
    assert c._template_application_service is None  # noqa: SLF001


# ── get_service_container (FastAPI dep) 强断言 ───────────────


def test_get_service_container_returns_app_state_services():
    """杀死忽略 app.state.services 的变异。"""
    container = ServiceContainer()
    app = SimpleNamespace(state=SimpleNamespace(services=container))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "app": app,
    }
    req = Request(scope)
    result = get_service_container(req)
    assert result is container  # 必须返回 app.state.services


def test_get_service_container_falls_back_to_global_when_services_is_none():
    """杀死 fallback 分支不生效的变异。"""
    app = SimpleNamespace(state=SimpleNamespace(services=None))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "app": app,
    }
    req = Request(scope)
    global_reg = get_service_registry()
    result = get_service_container(req)
    assert result is global_reg


def test_get_service_container_falls_back_when_no_services_attr():
    """杀死 hasattr 检查被移除的变异。"""
    app = SimpleNamespace(state=SimpleNamespace())  # 无 services 属性
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "app": app,
    }
    req = Request(scope)
    global_reg = get_service_registry()
    result = get_service_container(req)
    assert result is global_reg


# ── ServiceContainer.__slots__ 初始值 ────────────────────────


def test_all_slots_initialized_to_none():
    """杀死 __init__ 中 self._foo = None → self._foo = "" 的变异。"""
    c = ServiceContainer()
    for name in ServiceContainer.__slots__:
        val = getattr(c, name)
        assert val is None, f"{name} should be None, got {val!r}"


def test_slots_count_matches_expected():
    """杀死 __slots__ 增减字段的变异。"""
    expected_slots = {
        "_session_service",
        "_auth_service",
        "_user_service",
        "_user_preference_service",
        "_customer_application_service",
        "_ai_chat_application_service",
        "_unit_products_import_application_service",
        "_file_analysis_application_service",
        "_template_application_service",
        "_materials_service",
        "_products_service",
        "_extract_log_service",
        "_product_import_service",
        "_shipment_application_service_core",
        "_shipment_event_primary_facade",
    }
    assert set(ServiceContainer.__slots__) == expected_slots
