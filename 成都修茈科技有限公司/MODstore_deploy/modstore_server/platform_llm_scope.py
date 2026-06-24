"""后台 loop「平台模型」执行作用域。

进入作用域后，所有经 ``chat_dispatch_via_session`` 的 LLM 调用都会被改走
``chat_dispatch_via_platform_only``（平台 API Key、**零配额、不计入任何用户钱包/配额**）；
员工 cognition 也会优先解析平台 bench 模型。这样后台自治/自维护/事件响应等
系统 loop 不再因某个用户 ``llm_calls`` 配额耗尽而 ``403 配额不足`` 熄火。

设计要点：
- 用 ``contextvars`` 标记作用域，作用于当前调用链。
- **跨线程不会自动继承** contextvar，因此凡是在执行链里 fan-out 到线程池/守护线程的
  地方（``employee_orchestrator._run_layer`` 的 ``ThreadPoolExecutor``、
  ``runtime_async.run_coro_sync`` 的守护线程分支）都用 ``contextvars.copy_context()``
  把当前上下文带过去，避免作用域在子线程里丢失而静默回落到用户配额（=钱漏）。
- 无平台 Key 时（``resolve_platform_bench_llm`` 返回 ``(None, None)``）作用域内的调用会
  **干净失败**而不是回落到用户路径——宁可这一轮 loop 跳过，也绝不计入用户。
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
from typing import Callable, Optional, Tuple, TypeVar

_PLATFORM_LLM_SCOPE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "modstore_platform_llm_scope", default=False
)

F = TypeVar("F", bound=Callable[..., object])


def platform_llm_scope_active() -> bool:
    """当前是否处于后台 loop 平台模型作用域内。"""
    return bool(_PLATFORM_LLM_SCOPE.get())


@contextlib.contextmanager
def platform_llm_scope():
    """进入「平台模型」作用域；退出后恢复（支持嵌套）。"""
    token = _PLATFORM_LLM_SCOPE.set(True)
    try:
        yield
    finally:
        _PLATFORM_LLM_SCOPE.reset(token)


def platform_llm_scoped(fn: F) -> F:
    """函数装饰器：整个函数体在平台模型作用域内执行。"""

    @functools.wraps(fn)
    def _wrap(*args, **kwargs):
        with platform_llm_scope():
            return fn(*args, **kwargs)

    return _wrap  # type: ignore[return-value]


def resolve_active_platform_bench() -> Tuple[Optional[str], Optional[str]]:
    """解析平台 bench ``(provider, model)``；无平台 Key 返回 ``(None, None)``。

    封装 ``services.llm.resolve_platform_bench_llm``，让调用方无需直接依赖该模块。
    """
    try:
        from modstore_server.services.llm import resolve_platform_bench_llm

        return resolve_platform_bench_llm()
    except Exception:
        return None, None


__all__ = [
    "platform_llm_scope",
    "platform_llm_scope_active",
    "platform_llm_scoped",
    "resolve_active_platform_bench",
]
