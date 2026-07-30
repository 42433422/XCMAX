"""app/contexts/context_notifier 变异测试强断言。

覆盖 survived 变异体：
- get_context_notifier 返回值必须是 None（is None 验证）
"""

from __future__ import annotations

from app.contexts.context_notifier import get_context_notifier


def test_get_context_notifier_returns_exactly_none():
    """杀死 get_context_notifier 返回非 None 的变异。"""
    result = get_context_notifier()
    assert result is None  # 必须是 None，不是假值


def test_get_context_notifier_return_type():
    """杀死返回类型错误的变异。"""
    result = get_context_notifier()
    assert type(result) is type(None)  # 必须是 NoneType
