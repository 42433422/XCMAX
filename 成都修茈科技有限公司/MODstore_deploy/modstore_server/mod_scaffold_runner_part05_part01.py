# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


from modstore_server.mod_scaffold_runner_part05_part01_part01 import (
    register_mod_employee_packs_async as register_mod_employee_packs_async,
    _employee_node_ids_for_workflow_cfg as _employee_node_ids_for_workflow_cfg,
    _ensure_workflow_start_end_skeleton as _ensure_workflow_start_end_skeleton,
)
from modstore_server.mod_scaffold_runner_part05_part01_part02 import (
    patch_workflow_graph_employee_nodes as patch_workflow_graph_employee_nodes,
)
