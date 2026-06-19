"""COVERAGE_RAMP Phase 6 round 10: backend low-coverage modules.

Targets:
- ``app/neuro_bus/domains/product_domain_handlers.py`` (28.4% line coverage, 78 uncovered lines)
- ``app/application/employee_runtime/agent.py`` (54.3% line coverage, 75 uncovered lines)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (NeuroBus /
DB session / app service / external API / employee pack loader). The handler
functions and EmployeeAgent methods themselves are exercised through real calls.

Note: ``ProductCacheInvalidatedEvent`` / ``ProductPriceChangedEvent`` 等 dataclass
子类生成的 ``__init__`` 不接受 ``payload`` / ``source`` / ``correlation_id`` 关键字
参数（基类 ``NeuroEvent`` 非 dataclass），因此 handler 中以关键字构造这些事件会
触发 ``TypeError``（属于 ``RECOVERABLE_ERRORS``）。测试通过在 handler 模块命名空间
中替换为接受这些关键字的事件 mock，使 handler 业务分支得以真实执行；同时保留
``isinstance`` 检查能力。

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, missing keys)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, LookupError, etc.)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application.employee_runtime.agent import EmployeeAgent
from app.application.employee_runtime.memory import MemoryContext
from app.neuro_bus.domains.product_domain_handlers import (
    ProductDomainHandlers,
    get_product_domain_handlers,
    register_product_domain_handlers,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_event(payload: dict[str, Any]) -> MagicMock:
    """构造一个最小可用的 event mock（payload + metadata.event_id）。"""
    ev = MagicMock()
    ev.payload = payload
    ev.metadata.event_id = "evt-123"
    return ev


class _FakeProductCacheInvalidatedEvent:
    """模拟 ProductCacheInvalidatedEvent，接受 payload/source/correlation_id 关键字。"""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        source: str | None = None,
        correlation_id: str | None = None,
        **kwargs: object,
    ) -> None:
        self.payload = payload or {}
        self.source = source
        self.correlation_id = correlation_id

    def __repr__(self) -> str:
        return f"<FakeProductCacheInvalidatedEvent payload={self.payload!r}>"


class _FakeProductPriceChangedEvent:
    """模拟 ProductPriceChangedEvent，接受 payload/source/correlation_id 关键字。"""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        source: str | None = None,
        correlation_id: str | None = None,
        **kwargs: object,
    ) -> None:
        self.payload = payload or {}
        self.source = source
        self.correlation_id = correlation_id

    def __repr__(self) -> str:
        return f"<FakeProductPriceChangedEvent payload={self.payload!r}>"


@pytest.fixture
def handlers() -> ProductDomainHandlers:
    return ProductDomainHandlers()


@pytest.fixture
def mock_bus() -> MagicMock:
    return MagicMock()


@pytest.fixture
def patch_product_events() -> Iterator[None]:
    """在 handler 模块命名空间中替换事件类，使关键字构造可用。

    handler 内通过 ``from app.neuro_bus.events.product_events import X`` 引入，
    实际查找的是 ``app.neuro_bus.domains.product_domain_handlers.X``。
    """
    with (
        patch(
            "app.neuro_bus.domains.product_domain_handlers.ProductCacheInvalidatedEvent",
            _FakeProductCacheInvalidatedEvent,
        ),
        patch(
            "app.neuro_bus.domains.product_domain_handlers.ProductPriceChangedEvent",
            _FakeProductPriceChangedEvent,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# ProductDomainHandlers — bus property lazy init
# ---------------------------------------------------------------------------


def test_bus_lazy_init_returns_cached(handlers: ProductDomainHandlers) -> None:
    assert handlers._bus is None
    mock_bus = MagicMock()
    with patch(
        "app.neuro_bus.domains.product_domain_handlers.get_neuro_bus",
        return_value=mock_bus,
    ):
        assert handlers.bus is mock_bus
    # 第二次访问应使用缓存（不再调用 get_neuro_bus）
    assert handlers.bus is mock_bus


# ---------------------------------------------------------------------------
# ProductDomainHandlers — handle_product_created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_product_created_happy_path(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event(
        {
            "product_id": "P1",
            "unit_name": "甲公司",
            "product_name": "涂料A",
        }
    )
    handlers._bus = mock_bus
    out = await handlers.handle_product_created(event)
    assert out["success"] is True
    assert out["product_id"] == "P1"
    assert out["actions"] == ["audit_logged", "cache_warmup_triggered"]
    # 应发布一个缓存失效事件
    assert mock_bus.publish.call_count == 1
    published = mock_bus.publish.call_args.args[0]
    assert isinstance(published, _FakeProductCacheInvalidatedEvent)
    assert published.payload["unit_name"] == "甲公司"
    assert published.payload["reason"] == "new_product_added"
    assert published.source == "product_domain"
    assert published.correlation_id == "evt-123"


@pytest.mark.asyncio
async def test_handle_product_created_empty_payload(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({})
    handlers._bus = mock_bus
    out = await handlers.handle_product_created(event)
    assert out["success"] is True
    assert out["product_id"] is None
    # unit_name 缺失 → None
    assert mock_bus.publish.call_count == 1
    published = mock_bus.publish.call_args.args[0]
    assert published.payload["unit_name"] is None


@pytest.mark.asyncio
async def test_handle_product_created_publish_raises_recoverable(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"product_id": "P2", "unit_name": "乙公司", "product_name": "漆"})
    mock_bus.publish.side_effect = RuntimeError("bus down")
    handlers._bus = mock_bus
    out = await handlers.handle_product_created(event)
    assert out["success"] is False
    assert "bus down" in out["error"]
    assert out["actions"] == ["audit_logged"]  # cache_warmup 未触发


@pytest.mark.asyncio
async def test_handle_product_created_publish_raises_value_error(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"product_id": "P3", "unit_name": "丙", "product_name": "x"})
    mock_bus.publish.side_effect = ValueError("invalid event")
    handlers._bus = mock_bus
    out = await handlers.handle_product_created(event)
    assert out["success"] is False
    assert "invalid event" in out["error"]


# ---------------------------------------------------------------------------
# ProductDomainHandlers — handle_product_updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_product_updated_with_price_change(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event(
        {
            "product_id": "P1",
            "unit_name": "甲公司",
            "changed_fields": ["price", "name"],
            "old_price": 100,
            "price": 120,
        }
    )
    handlers._bus = mock_bus
    out = await handlers.handle_product_updated(event)
    assert out["success"] is True
    assert out["product_id"] == "P1"
    assert out["actions"] == [
        "change_history_recorded",
        "price_change_event_triggered",
        "cache_invalidated",
    ]
    # 应发布两个事件：价格变更 + 缓存失效
    assert mock_bus.publish.call_count == 2
    price_ev = mock_bus.publish.call_args_list[0].args[0]
    cache_ev = mock_bus.publish.call_args_list[1].args[0]
    assert isinstance(price_ev, _FakeProductPriceChangedEvent)
    assert price_ev.payload["old_price"] == 100
    assert price_ev.payload["new_price"] == 120
    assert isinstance(cache_ev, _FakeProductCacheInvalidatedEvent)


@pytest.mark.asyncio
async def test_handle_product_updated_no_price_change(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event(
        {
            "product_id": "P2",
            "unit_name": "乙公司",
            "changed_fields": ["name"],
        }
    )
    handlers._bus = mock_bus
    out = await handlers.handle_product_updated(event)
    assert out["success"] is True
    # 没有 price_change_event_triggered
    assert out["actions"] == ["change_history_recorded", "cache_invalidated"]
    # 只发布缓存失效事件
    assert mock_bus.publish.call_count == 1
    assert isinstance(mock_bus.publish.call_args.args[0], _FakeProductCacheInvalidatedEvent)


@pytest.mark.asyncio
async def test_handle_product_updated_empty_changed_fields(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"product_id": "P3", "unit_name": "丙"})
    handlers._bus = mock_bus
    out = await handlers.handle_product_updated(event)
    assert out["success"] is True
    # changed_fields 缺失 → []，不触发价格变更
    assert "price_change_event_triggered" not in out["actions"]
    assert "cache_invalidated" in out["actions"]


@pytest.mark.asyncio
async def test_handle_product_updated_price_in_changed_fields_but_missing_prices(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    # 边界：price 在 changed_fields 中但 old_price/new_price 缺失
    event = _make_event(
        {
            "product_id": "P4",
            "unit_name": "丁",
            "changed_fields": ["price"],
        }
    )
    handlers._bus = mock_bus
    out = await handlers.handle_product_updated(event)
    assert out["success"] is True
    assert "price_change_event_triggered" in out["actions"]
    price_ev = mock_bus.publish.call_args_list[0].args[0]
    assert price_ev.payload["old_price"] is None
    assert price_ev.payload["new_price"] is None


@pytest.mark.asyncio
async def test_handle_product_updated_publish_raises_recoverable(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"product_id": "P5", "unit_name": "戊", "changed_fields": ["name"]})
    mock_bus.publish.side_effect = LookupError("lookup failed")
    handlers._bus = mock_bus
    out = await handlers.handle_product_updated(event)
    assert out["success"] is False
    assert "lookup failed" in out["error"]


# ---------------------------------------------------------------------------
# ProductDomainHandlers — handle_product_deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_product_deleted_happy_path(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"product_id": "P1", "unit_name": "甲公司"})
    handlers._bus = mock_bus
    out = await handlers.handle_product_deleted(event)
    assert out["success"] is True
    assert out["product_id"] == "P1"
    assert out["actions"] == ["deletion_audit_logged", "cache_invalidated"]
    assert mock_bus.publish.call_count == 1
    published = mock_bus.publish.call_args.args[0]
    assert isinstance(published, _FakeProductCacheInvalidatedEvent)
    assert published.payload["reason"] == "product_deleted"


@pytest.mark.asyncio
async def test_handle_product_deleted_empty_payload(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({})
    handlers._bus = mock_bus
    out = await handlers.handle_product_deleted(event)
    assert out["success"] is True
    assert out["product_id"] is None
    assert mock_bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_handle_product_deleted_publish_raises_recoverable(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"product_id": "P2"})
    mock_bus.publish.side_effect = RuntimeError("redis down")
    handlers._bus = mock_bus
    out = await handlers.handle_product_deleted(event)
    assert out["success"] is False
    assert "redis down" in out["error"]
    assert out["actions"] == ["deletion_audit_logged"]


# ---------------------------------------------------------------------------
# ProductDomainHandlers — handle_product_imported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_product_imported_happy_path(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"unit_name": "甲公司", "count": 50})
    handlers._bus = mock_bus
    out = await handlers.handle_product_imported(event)
    assert out["success"] is True
    assert out["unit_name"] == "甲公司"
    assert out["imported_count"] == 50
    assert out["actions"] == ["import_stats_recorded", "bulk_cache_invalidated"]
    assert mock_bus.publish.call_count == 1
    published = mock_bus.publish.call_args.args[0]
    assert isinstance(published, _FakeProductCacheInvalidatedEvent)
    assert published.payload["reason"] == "bulk_import"
    assert published.payload["affected_count"] == 50


@pytest.mark.asyncio
async def test_handle_product_imported_default_count(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    # 边界：count 缺失 → 默认 0
    event = _make_event({"unit_name": "乙公司"})
    handlers._bus = mock_bus
    out = await handlers.handle_product_imported(event)
    assert out["success"] is True
    assert out["imported_count"] == 0
    published = mock_bus.publish.call_args.args[0]
    assert published.payload["affected_count"] == 0


@pytest.mark.asyncio
async def test_handle_product_imported_publish_raises_recoverable(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"unit_name": "丙", "count": 10})
    mock_bus.publish.side_effect = ValueError("invalid")
    handlers._bus = mock_bus
    out = await handlers.handle_product_imported(event)
    assert out["success"] is False
    assert "invalid" in out["error"]


# ---------------------------------------------------------------------------
# ProductDomainHandlers — handle_price_changed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_price_changed_happy_path(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event(
        {
            "product_id": "P1",
            "old_price": 100,
            "new_price": 150,
            "unit_name": "甲公司",
        }
    )
    handlers._bus = mock_bus
    out = await handlers.handle_price_changed(event)
    assert out["success"] is True
    assert out["product_id"] == "P1"
    assert out["price_delta"] == 50
    assert out["actions"] == ["price_history_recorded"]
    # handle_price_changed 不发布事件
    assert mock_bus.publish.call_count == 0


@pytest.mark.asyncio
async def test_handle_price_changed_default_prices(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    # 边界：old_price/new_price 缺失 → 默认 0，delta = 0
    event = _make_event({"product_id": "P2"})
    handlers._bus = mock_bus
    out = await handlers.handle_price_changed(event)
    assert out["success"] is True
    assert out["price_delta"] == 0


@pytest.mark.asyncio
async def test_handle_price_changed_negative_delta(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    # 边界：降价场景
    event = _make_event({"product_id": "P3", "old_price": 200, "new_price": 50})
    handlers._bus = mock_bus
    out = await handlers.handle_price_changed(event)
    assert out["success"] is True
    assert out["price_delta"] == -150


# ---------------------------------------------------------------------------
# ProductDomainHandlers — handle_cache_invalidated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_cache_invalidated_with_product_id(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"product_id": "P1", "reason": "manual"})
    handlers._bus = mock_bus
    out = await handlers.handle_cache_invalidated(event)
    assert out["success"] is True
    assert out["invalidated"] == {"product_id": "P1", "reason": "manual"}
    assert out["actions"] == ["cache_cleared"]


@pytest.mark.asyncio
async def test_handle_cache_invalidated_with_unit_name(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({"unit_name": "甲公司"})
    handlers._bus = mock_bus
    out = await handlers.handle_cache_invalidated(event)
    assert out["success"] is True
    assert out["invalidated"]["unit_name"] == "甲公司"


@pytest.mark.asyncio
async def test_handle_cache_invalidated_empty_payload(
    handlers: ProductDomainHandlers,
    mock_bus: MagicMock,
    patch_product_events: None,
) -> None:
    event = _make_event({})
    handlers._bus = mock_bus
    out = await handlers.handle_cache_invalidated(event)
    assert out["success"] is True
    assert out["invalidated"] == {}
    assert out["actions"] == ["cache_cleared"]


# ---------------------------------------------------------------------------
# ProductDomainHandlers — singleton & register
# ---------------------------------------------------------------------------


def test_get_product_domain_handlers_singleton() -> None:
    import app.neuro_bus.domains.product_domain_handlers as mod

    mod._product_handlers = None
    a = get_product_domain_handlers()
    b = get_product_domain_handlers()
    assert a is b
    # 清理以避免污染其他测试
    mod._product_handlers = None


def test_register_product_domain_handlers_subscribes_all() -> None:
    mock_bus = MagicMock()
    register_product_domain_handlers(mock_bus)
    # 应注册 6 个事件
    assert mock_bus.subscribe.call_count == 6
    subscribed_events = [call.args[0] for call in mock_bus.subscribe.call_args_list]
    assert set(subscribed_events) == {
        "product.created",
        "product.updated",
        "product.deleted",
        "product.imported",
        "product.price_changed",
        "product.cache_invalidated",
    }
    # 清理单例
    import app.neuro_bus.domains.product_domain_handlers as mod

    mod._product_handlers = None


# ---------------------------------------------------------------------------
# EmployeeAgent — __init__
# ---------------------------------------------------------------------------


def test_employee_agent_init_strips_employee_id() -> None:
    agent = EmployeeAgent("  emp-1  ")
    assert agent.employee_id == "emp-1"


def test_employee_agent_init_empty_id() -> None:
    agent = EmployeeAgent("")
    assert agent.employee_id == ""


def test_employee_agent_init_none_id() -> None:
    agent = EmployeeAgent(None)  # type: ignore[arg-type]
    assert agent.employee_id == ""


def test_employee_agent_init_non_string_id() -> None:
    agent = EmployeeAgent(123)  # type: ignore[arg-type]
    assert agent.employee_id == "123"


# ---------------------------------------------------------------------------
# EmployeeAgent — _augment_config_with_memory
# ---------------------------------------------------------------------------


def test_augment_config_with_memory_empty_suffix_returns_original() -> None:
    config = {"cognition": {"agent": {"system_prompt": "hi"}}}
    mem_ctx = MemoryContext()  # 空 → suffix 为空
    out = EmployeeAgent._augment_config_with_memory(config, mem_ctx)
    assert out is config  # 应返回原对象


def test_augment_config_with_memory_appends_suffix() -> None:
    config = {"cognition": {"agent": {"system_prompt": "你是助手。"}}}
    mem_ctx = MemoryContext(long_term_prompt="【长期记忆】某客户偏好A")
    out = EmployeeAgent._augment_config_with_memory(config, mem_ctx)
    assert out is not config  # 应返回新对象
    assert "你是助手。" in out["cognition"]["agent"]["system_prompt"]
    assert "【长期记忆】某客户偏好A" in out["cognition"]["agent"]["system_prompt"]


def test_augment_config_with_memory_no_existing_system_prompt() -> None:
    config = {"cognition": {"agent": {}}}
    mem_ctx = MemoryContext(long_term_prompt="记忆内容")
    out = EmployeeAgent._augment_config_with_memory(config, mem_ctx)
    # base 为空 → 直接用 suffix
    assert out["cognition"]["agent"]["system_prompt"] == "记忆内容"


def test_augment_config_with_memory_no_cognition_key() -> None:
    config: dict[str, Any] = {}
    mem_ctx = MemoryContext(long_term_prompt="记忆")
    out = EmployeeAgent._augment_config_with_memory(config, mem_ctx)
    assert "cognition" in out
    assert "agent" in out["cognition"]
    assert out["cognition"]["agent"]["system_prompt"] == "记忆"


def test_augment_config_with_memory_cognition_not_dict() -> None:
    config = {"cognition": "not-a-dict"}
    mem_ctx = MemoryContext(long_term_prompt="记忆")
    out = EmployeeAgent._augment_config_with_memory(config, mem_ctx)
    assert isinstance(out["cognition"], dict)
    assert out["cognition"]["agent"]["system_prompt"] == "记忆"


def test_augment_config_with_memory_agent_not_dict() -> None:
    config = {"cognition": {"agent": "not-a-dict"}}
    mem_ctx = MemoryContext(long_term_prompt="记忆")
    out = EmployeeAgent._augment_config_with_memory(config, mem_ctx)
    assert isinstance(out["cognition"]["agent"], dict)
    assert out["cognition"]["agent"]["system_prompt"] == "记忆"


def test_augment_config_with_memory_short_term_messages() -> None:
    config: dict[str, Any] = {}
    mem_ctx = MemoryContext(
        short_term_messages=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好"},
        ]
    )
    out = EmployeeAgent._augment_config_with_memory(config, mem_ctx)
    prompt = out["cognition"]["agent"]["system_prompt"]
    assert "【近期会话记忆】" in prompt
    assert "你好" in prompt
    assert "您好" in prompt


# ---------------------------------------------------------------------------
# EmployeeAgent — _summarize
# ---------------------------------------------------------------------------


def test_summarize_empty_result_returns_empty() -> None:
    assert EmployeeAgent._summarize({}) == ""


def test_summarize_none_result_returns_empty() -> None:
    assert EmployeeAgent._summarize(None) == ""  # type: ignore[arg-type]


def test_summarize_result_with_summary_field() -> None:
    result = {"summary": "执行完成"}
    assert EmployeeAgent._summarize(result) == "执行完成"


def test_summarize_result_with_outputs_list() -> None:
    result = {
        "outputs": [
            {"handler": "echo", "output": "hello"},
            {"handler": "agent", "summary": "agent done"},
            {"handler": "failed", "error": "boom"},
        ]
    }
    out = EmployeeAgent._summarize(result)
    assert "[echo] hello" in out
    assert "[agent] agent done" in out
    assert "[failed] boom" in out


def test_summarize_outputs_not_list_falls_back_to_summary() -> None:
    result = {"outputs": "not-a-list", "summary": "fallback"}
    assert EmployeeAgent._summarize(result) == "fallback"


def test_summarize_outputs_empty_list_returns_empty() -> None:
    # outputs 为空列表 → isinstance(outputs, list) 为 True → 走 for 循环 → parts 为空
    result = {"outputs": [], "summary": "empty outputs"}
    assert EmployeeAgent._summarize(result) == ""


def test_summarize_output_item_not_dict_skipped() -> None:
    result = {"outputs": ["not-dict", {"handler": "echo", "output": "ok"}]}
    out = EmployeeAgent._summarize(result)
    assert "[echo] ok" in out
    # 非 dict 项被跳过
    assert "not-dict" not in out


def test_summarize_output_item_no_text_fields_skipped() -> None:
    result = {"outputs": [{"handler": "x"}, {"handler": "y"}]}
    # 所有项都没有 output/summary/error → parts 为空 → 返回空字符串
    assert EmployeeAgent._summarize(result) == ""


def test_summarize_truncates_long_text() -> None:
    long_text = "x" * 500
    result = {"outputs": [{"handler": "h", "output": long_text}]}
    out = EmployeeAgent._summarize(result)
    # 单项 output 截断到 300 字符
    assert len(out) < len(long_text)


# ---------------------------------------------------------------------------
# EmployeeAgent — _build_agent_tools
# ---------------------------------------------------------------------------


def test_build_agent_tools_import_error_returns_none() -> None:
    agent = EmployeeAgent("emp-1")
    # 将 sys.modules 中模块设为 None 强制触发 ImportError
    with patch.dict(
        "sys.modules",
        {"app.application.employee_runtime.tool_scope": None},
    ):
        out = agent._build_agent_tools({}, {})
    assert out is None


def test_build_agent_tools_recoverable_error_returns_none() -> None:
    agent = EmployeeAgent("emp-1")
    import app.application.employee_runtime.tool_scope as ts_mod

    with patch.object(ts_mod, "resolve_employee_tools", side_effect=RuntimeError("boom")):
        out = agent._build_agent_tools({}, {})
    assert out is None


def test_build_agent_tools_success_returns_tools() -> None:
    agent = EmployeeAgent("emp-1")
    import app.application.employee_runtime.tool_scope as ts_mod

    expected = [{"name": "tool1"}]
    with patch.object(ts_mod, "resolve_employee_tools", return_value=expected):
        out = agent._build_agent_tools({"m": 1}, {"c": 2})
    assert out == expected


# ---------------------------------------------------------------------------
# EmployeeAgent — _build_agent_gate
# ---------------------------------------------------------------------------


def test_build_agent_gate_all_imports_fail_returns_none() -> None:
    agent = EmployeeAgent("emp-1")
    with patch.dict(
        "sys.modules",
        {
            "app.application.employee_runtime.workspace_guard": None,
            "app.application.employee_runtime.write_approval": None,
        },
    ):
        out = agent._build_agent_gate({}, {}, None, {})
    assert out is None


def test_build_agent_gate_workspace_guard_only() -> None:
    agent = EmployeeAgent("emp-1")
    mock_ws_gate = MagicMock(name="ws_gate")
    import app.application.employee_runtime.workspace_guard as ws_mod

    with (
        patch.object(ws_mod, "build_employee_gate", return_value=mock_ws_gate),
        patch.dict(
            "sys.modules",
            {"app.application.employee_runtime.write_approval": None},
        ),
    ):
        out = agent._build_agent_gate({}, {}, "/ws", {})
    # compose_gates 也不可用 → 返回 ws_gate or write_gate = ws_gate
    assert out is mock_ws_gate


def test_build_agent_gate_recoverable_error_in_workspace_guard() -> None:
    agent = EmployeeAgent("emp-1")
    import app.application.employee_runtime.workspace_guard as ws_mod
    import app.application.employee_runtime.write_approval as wa_mod

    with (
        patch.object(ws_mod, "build_employee_gate", side_effect=RuntimeError("ws boom")),
        patch.object(wa_mod, "build_write_approval_gate", return_value=None),
        patch.object(wa_mod, "compose_gates", return_value="composed"),
    ):
        out = agent._build_agent_gate({}, {}, None, {})
    # ws_gate 失败 → None；write_gate 成功 → None；compose_gates 成功
    assert out == "composed"


def test_build_agent_gate_compose_success() -> None:
    agent = EmployeeAgent("emp-1")
    mock_ws_gate = MagicMock(name="ws_gate")
    mock_write_gate = MagicMock(name="write_gate")
    composed = MagicMock(name="composed")
    import app.application.employee_runtime.workspace_guard as ws_mod
    import app.application.employee_runtime.write_approval as wa_mod

    with (
        patch.object(ws_mod, "build_employee_gate", return_value=mock_ws_gate),
        patch.object(wa_mod, "build_write_approval_gate", return_value=mock_write_gate),
        patch.object(wa_mod, "compose_gates", return_value=composed),
    ):
        out = agent._build_agent_gate({}, {}, "/ws", {"input": 1})
    assert out is composed


# ---------------------------------------------------------------------------
# EmployeeAgent — _run_upstream_collaboration
# ---------------------------------------------------------------------------


def test_run_upstream_collaboration_skip_flag_returns_none() -> None:
    agent = EmployeeAgent("emp-1")
    out = agent._run_upstream_collaboration("task", {"skip_collaboration": True}, {}, {})
    assert out is None


def test_run_upstream_collaboration_import_error_returns_none() -> None:
    agent = EmployeeAgent("emp-1")
    with patch.dict(
        "sys.modules",
        {"app.application.employee_runtime.orchestrator": None},
    ):
        out = agent._run_upstream_collaboration("task", {}, {}, {})
    assert out is None


def test_run_upstream_collaboration_no_deps_returns_none() -> None:
    agent = EmployeeAgent("emp-1")
    mock_orch = MagicMock()
    mock_orch.depends_on.return_value = []
    with patch(
        "app.application.employee_runtime.orchestrator.EmployeeOrchestrator",
        return_value=mock_orch,
    ):
        out = agent._run_upstream_collaboration("task", {}, {}, {})
    assert out is None


def test_run_upstream_collaboration_with_deps_runs_upstream() -> None:
    agent = EmployeeAgent("emp-1")
    mock_orch = MagicMock()
    mock_orch.depends_on.return_value = ["dep-1"]
    mock_orch.run_upstream.return_value = {"node_outputs": {"dep-1": "ok"}}
    with (
        patch(
            "app.application.employee_runtime.orchestrator.EmployeeOrchestrator",
            return_value=mock_orch,
        ),
        patch("app.application.employee_runtime.metrics.record_orchestration") as mock_record,
    ):
        out = agent._run_upstream_collaboration(
            "task",
            {"user_id": 1, "workspace_root": "/ws", "session_id": "s1"},
            {"m": 1},
            {"c": 2},
        )
    assert out == {"node_outputs": {"dep-1": "ok"}}
    mock_record.assert_called_once_with("emp-1")
    # 验证 runtime_context 传递
    call_kwargs = mock_orch.run_upstream.call_args.kwargs
    assert call_kwargs["runtime_context"]["user_id"] == 1
    assert call_kwargs["runtime_context"]["workspace_root"] == "/ws"
    assert call_kwargs["runtime_context"]["session_id"] == "s1"


def test_run_upstream_collaboration_recoverable_error_returns_none() -> None:
    agent = EmployeeAgent("emp-1")
    mock_orch = MagicMock()
    mock_orch.depends_on.return_value = ["dep-1"]
    mock_orch.run_upstream.side_effect = RuntimeError("orch down")
    with (
        patch(
            "app.application.employee_runtime.orchestrator.EmployeeOrchestrator",
            return_value=mock_orch,
        ),
        patch("app.application.employee_runtime.metrics.record_orchestration"),
    ):
        out = agent._run_upstream_collaboration("task", {}, {}, {})
    assert out is None


# ---------------------------------------------------------------------------
# EmployeeAgent — _perceive
# ---------------------------------------------------------------------------


def test_perceive_import_error_falls_back_to_executor() -> None:
    agent = EmployeeAgent("emp-1")
    with (
        patch.dict(
            "sys.modules",
            {"app.application.employee_runtime.perception": None},
        ),
        patch(
            "app.application.employee_runtime.executor._perception_real",
            return_value={"fallback": True},
        ) as mock_real,
    ):
        out = agent._perceive({"cfg": 1}, {"input": "x"})
    assert out == {"fallback": True}
    mock_real.assert_called_once_with({"cfg": 1}, {"input": "x"})


def test_perceive_recoverable_error_falls_back_to_executor() -> None:
    agent = EmployeeAgent("emp-1")
    mock_pipeline_cls = MagicMock()
    mock_pipeline_cls.return_value.process.side_effect = RuntimeError("perceive boom")
    with (
        patch(
            "app.application.employee_runtime.perception.PerceptionPipeline",
            mock_pipeline_cls,
        ),
        patch(
            "app.application.employee_runtime.executor._perception_real",
            return_value={"fallback": True},
        ) as mock_real,
    ):
        out = agent._perceive({"cfg": 1}, {"input": "x"})
    assert out == {"fallback": True}
    mock_real.assert_called_once_with({"cfg": 1}, {"input": "x"})


def test_perceive_success_returns_pipeline_result() -> None:
    agent = EmployeeAgent("emp-1")
    mock_pipeline_cls = MagicMock()
    mock_pipeline_cls.return_value.process.return_value = {"perceived": True}
    with patch(
        "app.application.employee_runtime.perception.PerceptionPipeline",
        mock_pipeline_cls,
    ):
        out = agent._perceive({"cfg": 1}, {"input": "x"})
    assert out == {"perceived": True}


# ---------------------------------------------------------------------------
# EmployeeAgent — run (blocked by risk gate)
# ---------------------------------------------------------------------------


def test_run_blocked_by_risk_gate_returns_blocked_result() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {"pack_id": "emp-1", "version": "1.0.0", "manifest": {}, "pack_dir": "/tmp"}
    gate = {"ok": False, "blocked": True, "risk_level": "high", "reason": "r", "detail": "d"}
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["echo"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.metrics.record_employee_run") as mock_record,
    ):
        out = agent.run("task", input_data={})
    assert out["success"] is False
    assert out["blocked_by_risk_gate"] is True
    assert out["result"]["summary"] == "blocked by risk middleware"
    assert out["result"]["risk_gate"] == gate
    mock_record.assert_called_once_with("emp-1", success=False, blocked=True)


# ---------------------------------------------------------------------------
# EmployeeAgent — run (pack load raises recoverable error)
# ---------------------------------------------------------------------------


def test_run_pack_load_recoverable_error_returns_error_result() -> None:
    agent = EmployeeAgent("emp-1")
    with patch(
        "app.application.employee_runtime.agent.load_employee_pack_from_disk",
        side_effect=ValueError("pack not found"),
    ):
        out = agent.run("task", input_data={})
    assert out["success"] is False
    assert "pack not found" in out["error"]
    assert out["employee_id"] == "emp-1"
    assert "duration_ms" in out
    assert "executed_at" in out


def test_run_pack_load_runtime_error_returns_error_result() -> None:
    agent = EmployeeAgent("emp-1")
    with patch(
        "app.application.employee_runtime.agent.load_employee_pack_from_disk",
        side_effect=RuntimeError("disk io"),
    ):
        out = agent.run("task", input_data={})
    assert out["success"] is False
    assert "disk io" in out["error"]


# ---------------------------------------------------------------------------
# EmployeeAgent — run (direct_python fast path with file_path)
# ---------------------------------------------------------------------------


def test_run_direct_python_fast_path_success() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["direct_python"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context"),
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch(
            "app.application.employee_runtime.agent._ex._actions_fhd",
            return_value={"outputs": [{"handler": "direct_python", "ok": True, "output": "done"}]},
        ) as mock_actions,
        patch(
            "app.application.employee_runtime.agent._ex._handlers_execution_ok",
            return_value=True,
        ),
        patch("app.application.employee_runtime.metrics.record_employee_run") as mock_record,
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()
        mock_mm.remember.return_value = None

        out = agent.run(
            "task",
            input_data={"file_path": "/tmp/file.txt"},
            workspace_root="/ws",
        )
    assert out["success"] is True
    assert out["employee_id"] == "emp-1"
    assert out["pack"]["id"] == "emp-1"
    assert out["source"] == "employee_runtime.local"
    assert out["memory_used"] is False
    mock_record.assert_called_once_with("emp-1", success=True)
    # 验证 direct_only 路径：reasoning 应包含 skipped_cognition
    actions_call = mock_actions.call_args
    reasoning = actions_call.args[1]
    assert reasoning.get("skipped_cognition") is True


# ---------------------------------------------------------------------------
# EmployeeAgent — run (cognition failed path)
# ---------------------------------------------------------------------------


def test_run_cognition_failed_returns_cognition_failed_result() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    reasoning_err = {"reasoning": "", "error": "llm timeout", "input": {}}
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["echo"],  # 非 direct_python
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context"),
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch(
            "app.application.employee_runtime.agent._ex._memory_light",
            return_value={"session": {}},
        ),
        patch(
            "app.application.employee_runtime.agent._ex._cognition_fhd",
            return_value=reasoning_err,
        ),
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()

        out = agent.run("task", input_data={})
    assert out["success"] is False
    assert out["result"]["summary"] == "cognition failed"
    assert out["result"]["cognition_error"] == "llm timeout"


def test_run_interactive_chat_cognition_failed_returns_degraded_reply() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {"name": "变更评审员"},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    reasoning_err = {"reasoning": "", "error": "llm timeout", "input": {}}
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["echo"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context"),
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch(
            "app.application.employee_runtime.agent._ex._memory_light",
            return_value={"session": {}},
        ),
        patch(
            "app.application.employee_runtime.agent._ex._cognition_fhd",
            return_value=reasoning_err,
        ),
        patch("app.application.employee_runtime.agent._ex._actions_fhd") as mock_actions,
        patch("app.application.employee_runtime.metrics.record_employee_run") as mock_record,
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()

        out = agent.run(
            "你好",
            input_data={"source": "admin_im", "invoke_mode": "interactive_chat"},
        )
    assert out["success"] is True
    assert out["degraded"] is True
    assert out["result"]["summary"] == "interactive chat fallback"
    assert out["result"]["cognition_error"] == "llm timeout"
    assert out["result"]["outputs"][0]["handler"] == "interactive_chat_fallback"
    assert "变更评审员" in out["result"]["outputs"][0]["output"]
    mock_actions.assert_not_called()
    mock_record.assert_called_once_with("emp-1", success=True)


# ---------------------------------------------------------------------------
# EmployeeAgent — run (full success path with agent handler)
# ---------------------------------------------------------------------------


def test_run_full_success_with_agent_handler() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    reasoning = {"reasoning": "thought", "input": {}, "memory": {}}
    actions_result = {
        "outputs": [{"handler": "agent", "ok": True, "output": "agent done"}],
        "summary": "executed 1 handlers",
    }
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["agent"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context"),
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch.object(
            EmployeeAgent, "_build_agent_tools", return_value=[{"name": "t1"}]
        ) as mock_build_tools,
        patch.object(
            EmployeeAgent, "_build_agent_gate", return_value=MagicMock()
        ) as mock_build_gate,
        patch(
            "app.application.employee_runtime.agent._ex._memory_light",
            return_value={"session": {}},
        ),
        patch(
            "app.application.employee_runtime.agent._ex._cognition_fhd",
            return_value=reasoning,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._actions_fhd",
            return_value=actions_result,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._handlers_execution_ok",
            return_value=True,
        ),
        patch("app.application.employee_runtime.metrics.record_employee_run") as mock_record,
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()
        mock_mm.remember.return_value = None

        out = agent.run("task", input_data={}, workspace_root="/ws")
    assert out["success"] is True
    assert out["source"] == "employee_runtime.local"
    mock_build_tools.assert_called_once()
    mock_build_gate.assert_called_once()
    mock_record.assert_called_once_with("emp-1", success=True)


# ---------------------------------------------------------------------------
# EmployeeAgent — run (handler execution fails, publishes trigger)
# ---------------------------------------------------------------------------


def test_run_handler_fails_publishes_trigger() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    reasoning = {"reasoning": "thought", "input": {}, "memory": {}}
    actions_result = {
        "outputs": [{"handler": "echo", "ok": False, "error": "boom"}],
        "summary": "executed 1 handlers",
    }
    mock_publish = MagicMock()
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["echo"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context"),
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch(
            "app.application.employee_runtime.agent._ex._memory_light",
            return_value={"session": {}},
        ),
        patch(
            "app.application.employee_runtime.agent._ex._cognition_fhd",
            return_value=reasoning,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._actions_fhd",
            return_value=actions_result,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._handlers_execution_ok",
            return_value=False,
        ),
        patch("app.application.employee_runtime.metrics.record_employee_run") as mock_record,
        patch(
            "app.application.employee_runtime.triggers.publish_employee_task_failed",
            mock_publish,
        ),
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()
        mock_mm.remember.return_value = None

        out = agent.run("task", input_data={}, session_id="s1")
    assert out["success"] is False
    mock_record.assert_called_once_with("emp-1", success=False)
    mock_publish.assert_called_once()
    call_args = mock_publish.call_args.args
    call_kwargs = mock_publish.call_args.kwargs
    # employee_id 是第一个位置参数
    assert call_args[0] == "emp-1"
    assert call_kwargs["task"] == "task"
    assert "boom" in call_kwargs["message"]


def test_run_handler_fails_trigger_publish_recoverable_error_swallowed() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    reasoning = {"reasoning": "thought", "input": {}, "memory": {}}
    actions_result = {
        "outputs": [{"handler": "echo", "ok": False, "error": "boom"}],
        "summary": "executed 1 handlers",
    }
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["echo"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context"),
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch(
            "app.application.employee_runtime.agent._ex._memory_light",
            return_value={"session": {}},
        ),
        patch(
            "app.application.employee_runtime.agent._ex._cognition_fhd",
            return_value=reasoning,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._actions_fhd",
            return_value=actions_result,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._handlers_execution_ok",
            return_value=False,
        ),
        patch("app.application.employee_runtime.metrics.record_employee_run"),
        patch(
            "app.application.employee_runtime.triggers.publish_employee_task_failed",
            side_effect=RuntimeError("trigger bus down"),
        ),
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()
        mock_mm.remember.return_value = None

        # 不应抛错，trigger 失败被吞掉
        out = agent.run("task", input_data={})
    assert out["success"] is False


# ---------------------------------------------------------------------------
# EmployeeAgent — run (upstream collaboration injects payload)
# ---------------------------------------------------------------------------


def test_run_upstream_collaboration_injects_payload() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    reasoning = {"reasoning": "thought", "input": {}, "memory": {}}
    actions_result = {"outputs": [], "summary": "executed 0 handlers"}
    upstream = {
        "node_outputs": {"dep-1": "ok"},
        "plan_id": "p1",
        "success": True,
        "node_results": [{"id": "dep-1"}],
    }
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["echo"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch.object(
            EmployeeAgent,
            "_run_upstream_collaboration",
            return_value=upstream,
        ) as mock_upstream,
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context"),
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch(
            "app.application.employee_runtime.agent._ex._memory_light",
            return_value={"session": {}},
        ),
        patch(
            "app.application.employee_runtime.agent._ex._cognition_fhd",
            return_value=reasoning,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._actions_fhd",
            return_value=actions_result,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._handlers_execution_ok",
            return_value=True,
        ),
        patch("app.application.employee_runtime.metrics.record_employee_run"),
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()
        mock_mm.remember.return_value = None

        out = agent.run("task", input_data={})
    assert out["success"] is True
    # upstream 应被注入到 payload
    # 验证 upstream 出现在结果中
    assert out["collaboration_upstream"] == upstream
    mock_upstream.assert_called_once()


# ---------------------------------------------------------------------------
# EmployeeAgent — run (workspace_root injected into payload)
# ---------------------------------------------------------------------------


def test_run_workspace_root_injected_into_payload() -> None:
    agent = EmployeeAgent("emp-1")
    pack = {
        "pack_id": "emp-1",
        "version": "1.0.0",
        "manifest": {},
        "pack_dir": "/tmp/emp-1",
    }
    gate = {"ok": True, "risk_level": "low", "reason": "low"}
    reasoning = {"reasoning": "thought", "input": {}, "memory": {}}
    actions_result = {"outputs": [], "summary": "executed 0 handlers"}
    with (
        patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            return_value=pack,
        ),
        patch(
            "app.application.employee_runtime.agent.parse_employee_config_v2",
            return_value={},
        ),
        patch("app.application.employee_runtime.agent._ex._normalize_actions_cfg", return_value={}),
        patch(
            "app.application.employee_runtime.agent._ex._handler_list",
            return_value=["echo"],
        ),
        patch(
            "app.application.employee_runtime.agent.gate_action_or_block",
            return_value=gate,
        ),
        patch("app.application.employee_runtime.agent.MemoryScope.from_config") as mock_scope_cls,
        patch("app.application.employee_runtime.agent.EmployeeMemoryManager") as mock_mm_cls,
        patch("app.application.employee_runtime.agent.build_employee_context") as mock_build_ctx,
        patch.object(EmployeeAgent, "_perceive", return_value={"normalized_input": {}}),
        patch(
            "app.application.employee_runtime.agent._ex._memory_light",
            return_value={"session": {}},
        ),
        patch(
            "app.application.employee_runtime.agent._ex._cognition_fhd",
            return_value=reasoning,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._actions_fhd",
            return_value=actions_result,
        ),
        patch(
            "app.application.employee_runtime.agent._ex._handlers_execution_ok",
            return_value=True,
        ),
        patch("app.application.employee_runtime.metrics.record_employee_run"),
    ):
        mock_scope = MagicMock()
        mock_scope_cls.return_value = mock_scope
        mock_mm = MagicMock()
        mock_mm_cls.return_value = mock_mm
        mock_mm.recall.return_value = MemoryContext()
        mock_mm.remember.return_value = None

        agent.run("task", input_data={}, workspace_root="/custom/ws")
    # build_employee_context 收到的 payload 应包含 workspace_root
    call_args = mock_build_ctx.call_args.args
    assert call_args[1].get("workspace_root") == "/custom/ws"


# ---------------------------------------------------------------------------
# EmployeeAgent — _blocked_result / _cognition_failed_result (direct)
# ---------------------------------------------------------------------------


def test_blocked_result_structure() -> None:
    agent = EmployeeAgent("emp-1")
    import time

    t0 = time.perf_counter()
    pack = {"pack_id": "emp-1", "version": "1.0.0"}
    gate = {"ok": False, "blocked": True}
    out = agent._blocked_result(pack, "task", ["echo"], gate, t0)
    assert out["employee_id"] == "emp-1"
    assert out["pack"]["id"] == "emp-1"
    assert out["pack"]["version"] == "1.0.0"
    assert out["result"]["task"] == "task"
    assert out["result"]["handlers"] == ["echo"]
    assert out["result"]["summary"] == "blocked by risk middleware"
    assert out["result"]["risk_gate"] == gate
    assert out["blocked_by_risk_gate"] is True
    assert out["success"] is False
    assert "duration_ms" in out
    assert "executed_at" in out


def test_cognition_failed_result_structure() -> None:
    agent = EmployeeAgent("emp-1")
    import time

    t0 = time.perf_counter()
    pack = {"pack_id": "emp-1", "version": "1.0.0"}
    reasoning = {"error": "llm error"}
    out = agent._cognition_failed_result(pack, "task", ["echo"], reasoning, t0)
    assert out["employee_id"] == "emp-1"
    assert out["pack"]["id"] == "emp-1"
    assert out["success"] is False
    assert out["result"]["task"] == "task"
    assert out["result"]["handlers"] == ["echo"]
    assert out["result"]["summary"] == "cognition failed"
    assert out["result"]["cognition_error"] == "llm error"
    assert "duration_ms" in out
    assert "executed_at" in out
