"""app/contexts/flags 变异测试强断言。

覆盖 survived 变异体：
- _truthy: strip().lower() 逻辑验证
- is_any_event_primary_enabled: bool(raw) 和 _truthy(raw) 组合验证
- is_event_primary_enabled: context_id.strip().upper() 验证
- 环境变量 key 构造逻辑验证
"""

from __future__ import annotations

import os

import pytest

import app.contexts.flags as flags


@pytest.fixture(autouse=True)
def _clear_env():
    """清理所有相关环境变量。"""
    keys = [k for k in os.environ if k.startswith("XCAGI_EVENT_PRIMARY")]
    saved = {k: os.environ.pop(k) for k in keys}
    try:
        yield
    finally:
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update(saved)


# ── _truthy 强断言 ───────────────────────────────────────────


def test_truthy_exactly_true_tokens():
    """杀死 _truthy 接受错误值的变异。"""
    # 必须接受的
    assert flags._truthy("1") is True
    assert flags._truthy("true") is True
    assert flags._truthy("TRUE") is True
    assert flags._truthy("True") is True
    assert flags._truthy("yes") is True
    assert flags._truthy("YES") is True
    assert flags._truthy("on") is True
    assert flags._truthy("ON") is True
    # 带空格的
    assert flags._truthy(" 1 ") is True
    assert flags._truthy(" true ") is True
    assert flags._truthy("\tyes\n") is True


def test_truthy_exactly_false_tokens():
    """杀死 _truthy 拒绝错误值的变异。"""
    # 必须拒绝的
    assert flags._truthy("0") is False
    assert flags._truthy("false") is False
    assert flags._truthy("no") is False
    assert flags._truthy("off") is False
    assert flags._truthy("") is False
    assert flags._truthy("   ") is False
    assert flags._truthy("maybe") is False
    assert flags._truthy("y") is False  # 只接受完整 "yes"
    assert flags._truthy("t") is False  # 只接受完整 "true"


def test_truthy_strips_whitespace_then_lowercases():
    """杀死 strip/lower 顺序错误的变异。"""
    # 混合大小写 + 空白
    assert flags._truthy("  TrUe  ") is True
    assert flags._truthy("\nYeS\t") is True
    assert flags._truthy("  fAlSe  ") is False


# ── is_any_event_primary_enabled 强断言 ──────────────────────


def test_any_event_primary_unset_returns_false():
    """杀死环境变量未设置时返回 True 的变异。"""
    assert "XCAGI_EVENT_PRIMARY" not in os.environ
    assert flags.is_any_event_primary_enabled() is False


def test_any_event_primary_empty_string_returns_false():
    """杀死空字符串返回 True 的变异。"""
    os.environ["XCAGI_EVENT_PRIMARY"] = ""
    assert flags.is_any_event_primary_enabled() is False


def test_any_event_primary_whitespace_only_returns_false():
    """杀死纯空白返回 True 的变异。"""
    os.environ["XCAGI_EVENT_PRIMARY"] = "   "
    assert flags.is_any_event_primary_enabled() is False


def test_any_event_primary_truthy_values():
    """杀死不接受正确值的变异。"""
    for val in ("1", "true", "YES", "On"):
        os.environ["XCAGI_EVENT_PRIMARY"] = val
        assert flags.is_any_event_primary_enabled() is True, f"failed for {val!r}"


def test_any_event_primary_falsy_values():
    """杀死接受错误值的变异。"""
    for val in ("0", "false", "no", "off"):
        os.environ["XCAGI_EVENT_PRIMARY"] = val
        assert flags.is_any_event_primary_enabled() is False, f"failed for {val!r}"


# ── is_event_primary_enabled 强断言 ──────────────────────────


def test_per_context_unset_returns_false():
    """杀死未设置时返回 True 的变异。"""
    assert flags.is_event_primary_enabled("shipment") is False
    assert flags.is_event_primary_enabled("order") is False


def test_per_context_global_enables_all():
    """杀死全局标志不影响 per-context 的变异。"""
    os.environ["XCAGI_EVENT_PRIMARY"] = "1"
    # 所有 context 都应该启用
    assert flags.is_event_primary_enabled("shipment") is True
    assert flags.is_event_primary_enabled("order") is True
    assert flags.is_event_primary_enabled("inventory") is True
    assert flags.is_event_primary_enabled("any_context") is True


def test_per_context_specific_key_enables_only_that_context():
    """杀死 per-context 标志影响其他 context 的变异。"""
    os.environ["XCAGI_EVENT_PRIMARY_SHIPMENT"] = "1"
    assert flags.is_event_primary_enabled("shipment") is True
    assert flags.is_event_primary_enabled("order") is False
    assert flags.is_event_primary_enabled("inventory") is False


def test_per_context_global_overrides_specific():
    """杀死 per-context 优先级高于全局的变异。"""
    os.environ["XCAGI_EVENT_PRIMARY"] = "1"
    os.environ["XCAGI_EVENT_PRIMARY_SHIPMENT"] = "0"  # 应该被全局覆盖
    assert flags.is_event_primary_enabled("shipment") is True


def test_per_context_key_construction():
    """杀死 key 构造逻辑错误的变异。"""
    # context_id 应该被 strip 后 upper
    os.environ["XCAGI_EVENT_PRIMARY_SHIPMENT"] = "1"
    assert flags.is_event_primary_enabled("  shipment  ") is True
    assert flags.is_event_primary_enabled("SHIPMENT") is True
    assert flags.is_event_primary_enabled("Shipment") is True


def test_per_context_different_contexts_independent():
    """杀死不同 context 共享状态的变异。"""
    os.environ["XCAGI_EVENT_PRIMARY_SHIPMENT"] = "1"
    os.environ["XCAGI_EVENT_PRIMARY_ORDER"] = "0"
    assert flags.is_event_primary_enabled("shipment") is True
    assert flags.is_event_primary_enabled("order") is False


def test_per_context_empty_context_id():
    """杀死空 context_id 处理的变异。"""
    os.environ["XCAGI_EVENT_PRIMARY_"] = "1"  # key = XCAGI_EVENT_PRIMARY_
    # 空字符串 strip().upper() 后仍是空
    assert flags.is_event_primary_enabled("") is True
    assert flags.is_event_primary_enabled("  ") is True
