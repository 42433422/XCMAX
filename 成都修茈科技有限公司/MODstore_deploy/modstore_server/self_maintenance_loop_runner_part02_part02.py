# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def close_loop_memory_items(
    *,
    actor: str = "self_maintenance",
    branches: _facade().Optional[_facade().List[str]] = None,
    reasons: _facade().Optional[_facade().List[str]] = None,
    resolution_reason: str,
    run_ids: _facade().Optional[_facade().List[str]] = None,
    task_ids: _facade().Optional[_facade().List[str]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Close resolved loop-memory risks without deleting audit history."""
    memory = _facade()._load_loop_memory()
    result = _facade()._close_open_items_in_memory(
        memory,
        actor=actor,
        branches=branches,
        reasons=reasons,
        resolution_reason=resolution_reason,
        run_ids=run_ids,
        task_ids=task_ids,
    )
    _facade()._write_loop_memory(memory)
    return {
        **result,
        "memory_path": str(_facade().loop_memory_path()),
        "open_items_remaining": len(memory.get("open_items") or []),
    }
