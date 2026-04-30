"""Workflow tools application facade (Phase 4B absorbed).

``app.application.tools`` re-export 自 :mod:`app.application.tools.workflow`,
其中 ``handle_price_list_export`` 在当前代码库并不存在(backend → app.legacy 清理
时丢失),保留 ``__getattr__`` 惰性路径抛出带上下文的 ImportError,避免
顶层 import 就崩。
"""

from __future__ import annotations

from app.application.tools.workflow import (  # noqa: F401
    execute_workflow_tool,
    get_workflow_tool_registry,
    handle_excel_analysis,
    resolve_safe_excel_path,
    run_natural_language_pandas,
)

__all__ = [
    "execute_workflow_tool",
    "get_workflow_tool_registry",
    "handle_excel_analysis",
    "handle_price_list_export",
    "resolve_safe_excel_path",
    "run_natural_language_pandas",
]


_LOST_LEGACY_SYMBOLS = frozenset({
    "handle_price_list_export",
    "flatten_tool_result_dict_for_client",
    "get_last_tool_result",
})


def __getattr__(name: str):
    if name in _LOST_LEGACY_SYMBOLS:
        raise ImportError(
            f"{name!r} is not implemented in app.application.tools; "
            "this function was lost in the backend → app.legacy cleanup."
        )
    raise AttributeError(f"module 'app.application.tools' has no attribute {name!r}")
