"""Preserve legacy module injection points for extracted mixin methods."""

from __future__ import annotations

import functools
import inspect
import sys
from collections.abc import Callable, Iterable
from types import ModuleType
from typing import Any


def _sync_globals(
    target: dict[str, Any],
    source_module: str,
    source_ref: ModuleType | None = None,
) -> None:
    source = source_ref or sys.modules.get(source_module)
    if not isinstance(source, ModuleType):
        return
    target.update(
        {name: value for name, value in vars(source).items() if not name.startswith("__")}
    )


def _wrapped(
    function: Callable[..., Any],
    *,
    target: dict[str, Any],
    source_module: str,
) -> Callable[..., Any]:
    source_ref = sys.modules.get(source_module)
    captured_source = source_ref if isinstance(source_ref, ModuleType) else None
    if inspect.isasyncgenfunction(function):

        @functools.wraps(function)
        async def invoke_async_generator(*args: Any, **kwargs: Any):
            _sync_globals(target, source_module, captured_source)
            async for item in function(*args, **kwargs):
                yield item

        return invoke_async_generator
    if inspect.iscoroutinefunction(function):

        @functools.wraps(function)
        async def invoke_async(*args: Any, **kwargs: Any) -> Any:
            _sync_globals(target, source_module, captured_source)
            return await function(*args, **kwargs)

        return invoke_async
    if inspect.isgeneratorfunction(function):

        @functools.wraps(function)
        def invoke_generator(*args: Any, **kwargs: Any):
            _sync_globals(target, source_module, captured_source)
            yield from function(*args, **kwargs)

        return invoke_generator

    @functools.wraps(function)
    def invoke(*args: Any, **kwargs: Any) -> Any:
        _sync_globals(target, source_module, captured_source)
        return function(*args, **kwargs)

    return invoke


def sync_mixin_methods(
    mixin: type[Any],
    *,
    target: dict[str, Any],
    source_module: str,
    method_names: Iterable[str],
) -> None:
    """Wrap extracted descriptors so old module-level patches still apply."""

    for name in method_names:
        descriptor = vars(mixin)[name]
        if isinstance(descriptor, staticmethod):
            replacement: Any = staticmethod(
                _wrapped(
                    descriptor.__func__,
                    target=target,
                    source_module=source_module,
                )
            )
        elif isinstance(descriptor, classmethod):
            replacement = classmethod(
                _wrapped(
                    descriptor.__func__,
                    target=target,
                    source_module=source_module,
                )
            )
        else:
            replacement = _wrapped(
                descriptor,
                target=target,
                source_module=source_module,
            )
        setattr(mixin, name, replacement)


def sync_module_functions(
    *,
    target: dict[str, Any],
    source_module: str,
    function_names: Iterable[str],
) -> None:
    """Apply the same compatibility boundary to extracted module functions."""

    for name in function_names:
        target[name] = _wrapped(
            target[name],
            target=target,
            source_module=source_module,
        )


__all__ = ["sync_mixin_methods", "sync_module_functions"]
