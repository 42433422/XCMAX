"""真实行为测试：app/infrastructure/mods/comms.py（第二波覆盖）。

ModCommsRegistry 是纯内存的同步调用表，无外部依赖（无 DB/网络/LLM/文件系统/时间）。
本套件直接构造 registry 实例并断言返回值、副作用、状态变化与异常分支，
覆盖 register/unregister/unregister_all/has_handler/call/list_endpoints/get_caller_mod_id。
"""

from __future__ import annotations

import pytest

from app.infrastructure.mods import comms as comms_mod
from app.infrastructure.mods.comms import (
    ModCommsConflictError,
    ModCommsNotFoundError,
    ModCommsRegistry,
    get_caller_mod_id,
    get_mod_comms,
)


@pytest.fixture
def registry() -> ModCommsRegistry:
    """每个用例独立的全新 registry，隔离全局单例。"""
    return ModCommsRegistry()


class TestRegister:
    def test_register_success_and_call_returns_handler_value(self, registry):
        def handler(query: str) -> dict:
            return {"echo": query}

        registry.register("mod-a", "search", handler)
        assert registry.has_handler("mod-a", "search") is True
        # handler 实际被存进 (mod_id, channel) 键
        result = registry.call("caller", "mod-a", "search", "hello")
        assert result == {"echo": "hello"}

    def test_register_strips_whitespace_in_ids(self, registry):
        def handler() -> str:
            return "ok"

        registry.register("  mod-a  ", "  search  ", handler)
        # 注册时已 strip，应可用去空白后的名字命中
        assert registry.has_handler("mod-a", "search") is True
        assert registry.call("c", "mod-a", "search") == "ok"

    def test_register_empty_mod_id_raises_value_error(self, registry):
        with pytest.raises(ValueError, match="non-empty"):
            registry.register("", "search", lambda: None)

    def test_register_empty_channel_raises_value_error(self, registry):
        with pytest.raises(ValueError, match="non-empty"):
            registry.register("mod-a", "   ", lambda: None)

    def test_register_none_inputs_raise_value_error(self, registry):
        with pytest.raises(ValueError, match="non-empty"):
            registry.register(None, None, lambda: None)  # type: ignore[arg-type]

    def test_register_non_callable_handler_raises_type_error(self, registry):
        with pytest.raises(TypeError, match="callable"):
            registry.register("mod-a", "search", "not-callable")  # type: ignore[arg-type]

    def test_register_conflict_without_replace_raises(self, registry):
        registry.register("mod-a", "search", lambda: 1)
        with pytest.raises(ModCommsConflictError, match="mod-a::search"):
            registry.register("mod-a", "search", lambda: 2)

    def test_register_replace_true_overrides_handler(self, registry):
        registry.register("mod-a", "search", lambda: "old")
        registry.register("mod-a", "search", lambda: "new", replace=True)
        assert registry.call("c", "mod-a", "search") == "new"


class TestUnregister:
    def test_unregister_existing_returns_true_and_removes(self, registry):
        registry.register("mod-a", "ch", lambda: 1)
        assert registry.unregister("mod-a", "ch") is True
        assert registry.has_handler("mod-a", "ch") is False

    def test_unregister_missing_returns_false(self, registry):
        assert registry.unregister("nope", "ch") is False

    def test_unregister_strips_whitespace(self, registry):
        registry.register("mod-a", "ch", lambda: 1)
        assert registry.unregister("  mod-a  ", "  ch  ") is True


class TestUnregisterAll:
    def test_unregister_all_removes_only_target_mod(self, registry):
        registry.register("mod-a", "ch1", lambda: 1)
        registry.register("mod-a", "ch2", lambda: 2)
        registry.register("mod-b", "ch1", lambda: 3)

        removed = registry.unregister_all("mod-a")
        assert removed == 2
        assert registry.has_handler("mod-a", "ch1") is False
        assert registry.has_handler("mod-a", "ch2") is False
        # 其他 mod 不受影响
        assert registry.has_handler("mod-b", "ch1") is True

    def test_unregister_all_empty_mod_id_returns_zero(self, registry):
        registry.register("mod-a", "ch1", lambda: 1)
        # 空 mod_id 提前返回 0，不删任何东西
        assert registry.unregister_all("   ") == 0
        assert registry.has_handler("mod-a", "ch1") is True

    def test_unregister_all_no_match_returns_zero(self, registry):
        registry.register("mod-a", "ch1", lambda: 1)
        assert registry.unregister_all("mod-x") == 0
        assert registry.has_handler("mod-a", "ch1") is True


class TestHasHandler:
    def test_has_handler_true_false(self, registry):
        registry.register("mod-a", "ch", lambda: 1)
        assert registry.has_handler("mod-a", "ch") is True
        assert registry.has_handler("mod-a", "other") is False

    def test_has_handler_strips_whitespace(self, registry):
        registry.register("mod-a", "ch", lambda: 1)
        assert registry.has_handler(" mod-a ", " ch ") is True


class TestCall:
    def test_call_passes_args_and_kwargs(self, registry):
        def handler(a, b, *, c):
            return (a, b, c)

        registry.register("mod-a", "ch", handler)
        assert registry.call("src", "mod-a", "ch", 1, 2, c=3) == (1, 2, 3)

    def test_call_unknown_channel_raises_not_found(self, registry):
        with pytest.raises(ModCommsNotFoundError, match="mod-a::ch"):
            registry.call("src", "mod-a", "ch")

    def test_call_sets_caller_context_visible_to_handler(self, registry):
        seen: dict[str, str | None] = {}

        def handler() -> str:
            seen["caller"] = get_caller_mod_id()
            return "done"

        registry.register("mod-a", "ch", handler)
        assert registry.call("source-mod", "mod-a", "ch") == "done"
        assert seen["caller"] == "source-mod"

    def test_call_blank_source_defaults_to_unknown(self, registry):
        seen: dict[str, str | None] = {}

        def handler() -> None:
            seen["caller"] = get_caller_mod_id()

        registry.register("mod-a", "ch", handler)
        registry.call("   ", "mod-a", "ch")
        assert seen["caller"] == "unknown"

    def test_call_resets_caller_context_after_return(self, registry):
        registry.register("mod-a", "ch", lambda: "x")
        # 调用前后上下文都应是 None（finally 里 reset）
        assert get_caller_mod_id() is None
        registry.call("source-mod", "mod-a", "ch")
        assert get_caller_mod_id() is None

    def test_call_resets_caller_context_even_on_handler_exception(self, registry):
        def boom() -> None:
            raise RuntimeError("handler exploded")

        registry.register("mod-a", "ch", boom)
        with pytest.raises(RuntimeError, match="handler exploded"):
            registry.call("source-mod", "mod-a", "ch")
        # finally 仍然执行 reset，调用方上下文不泄漏
        assert get_caller_mod_id() is None


class TestGetCallerModId:
    def test_returns_none_outside_call_context(self):
        assert get_caller_mod_id() is None


class TestListEndpoints:
    def test_list_endpoints_empty(self, registry):
        assert registry.list_endpoints() == []

    def test_list_endpoints_sorted_and_excludes_callable(self, registry):
        def named_handler() -> None:
            return None

        registry.register("mod-b", "z", named_handler)
        registry.register("mod-a", "y", named_handler)
        registry.register("mod-a", "x", named_handler)

        endpoints = registry.list_endpoints()
        # 按 (mod_id, channel) 排序
        assert [(e["mod_id"], e["channel"]) for e in endpoints] == [
            ("mod-a", "x"),
            ("mod-a", "y"),
            ("mod-b", "z"),
        ]
        # 不含可调用对象，只含 handler 名字（__qualname__）
        for e in endpoints:
            assert "handler" in e
            assert not callable(e["handler"])
            assert "named_handler" in e["handler"]

    def test_list_endpoints_handler_name_fallback_for_callable_object(self, registry):
        # 一个没有 __qualname__/__name__ 的可调用对象 -> 回退到 type(fn).__name__
        class CallableObj:
            def __call__(self) -> str:
                return "ok"

        obj = CallableObj()
        registry.register("mod-a", "ch", obj)
        endpoints = registry.list_endpoints()
        assert len(endpoints) == 1
        # __qualname__ 存在于实例方法上时取到的是类的限定名；至少应包含类名
        assert "CallableObj" in endpoints[0]["handler"]


class TestGetModComms:
    def test_get_mod_comms_returns_singleton(self):
        a = get_mod_comms()
        b = get_mod_comms()
        assert a is b
        assert isinstance(a, ModCommsRegistry)

    def test_get_mod_comms_initializes_when_none(self, monkeypatch):
        # 强制把全局单例置空，覆盖惰性初始化分支
        monkeypatch.setattr(comms_mod, "_registry", None)
        reg = get_mod_comms()
        assert isinstance(reg, ModCommsRegistry)
        # 之后再次调用返回同一个
        assert get_mod_comms() is reg
