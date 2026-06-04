"""PEP 562 延迟转发：避免 domains 互引时顶层 shim 循环导入。"""
from __future__ import annotations

from importlib import import_module
from typing import Any


def lazy_domain_shim(impl_module: str) -> dict[str, Any]:
    """返回可 ``exec`` 进 shim 模块 namespace 的 __getattr__ / __dir__ 实现。"""

    def __getattr__(name: str) -> Any:  # noqa: N807
        return getattr(import_module(impl_module), name)

    def __dir__() -> list[str]:  # noqa: N807
        return dir(import_module(impl_module))

    return {"__getattr__": __getattr__, "__dir__": __dir__}
