"""Built-in task discovery for synchronous and desktop fallbacks."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Callable, cast

_TASK_MODULES = (
    "app.tasks.inference_tasks",
    "app.tasks.shipment_tasks",
)


def get_task_function(task_name: str) -> Callable[..., Any]:
    """Resolve a registered Celery task by its public short name."""
    normalized = str(task_name or "").strip().rsplit(".", 1)[-1]
    if not normalized:
        raise LookupError("task name is required")
    for module_name in _TASK_MODULES:
        module = import_module(module_name)
        candidate = getattr(module, normalized, None)
        if callable(candidate):
            return cast("Callable[..., Any]", candidate)
    raise LookupError(f"unknown task: {normalized}")


__all__ = ["get_task_function"]
