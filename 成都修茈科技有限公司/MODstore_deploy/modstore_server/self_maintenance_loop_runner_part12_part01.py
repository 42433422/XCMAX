# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


from modstore_server.self_maintenance_loop_runner_part12_part01_part01 import (
    _evict_loop_memory_items as _evict_loop_memory_items,
    evict_loop_memory_items as evict_loop_memory_items,
    _update_loop_memory as _update_loop_memory,
)
from modstore_server.self_maintenance_loop_runner_part12_part01_part02 import (
    _run_self_maintenance_loop_unlocked as _run_self_maintenance_loop_unlocked,
    run_self_maintenance_loop as run_self_maintenance_loop,
)
from modstore_server.self_maintenance_loop_runner_part12_part01_part03 import (
    cron_trigger_for_self_maintenance as cron_trigger_for_self_maintenance,
    record_self_maintenance_heartbeat as record_self_maintenance_heartbeat,
)
