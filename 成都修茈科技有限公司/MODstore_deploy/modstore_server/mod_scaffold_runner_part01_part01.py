# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


from modstore_server.mod_scaffold_runner_part01_part01_part01 import (
    _parse_positive_int as _parse_positive_int,
    _employee_node_ids_for_workflow as _employee_node_ids_for_workflow,
    _ensure_minimal_employee_workflow_graph as _ensure_minimal_employee_workflow_graph,
    _resolve_workflow_entry_pack_id as _resolve_workflow_entry_pack_id,
    analyze_mod_employee_readiness as analyze_mod_employee_readiness,
    modstore_library_path as modstore_library_path,
    _pick_employee_pack_catalog_record as _pick_employee_pack_catalog_record,
    materialize_employee_pack_if_missing as materialize_employee_pack_if_missing,
)
from modstore_server.mod_scaffold_runner_part01_part01_part02 import (
    rehydrate_employee_pack_bundles as rehydrate_employee_pack_bundles,
    mod_compileall_warnings as mod_compileall_warnings,
    employee_pack_consistency_warnings as employee_pack_consistency_warnings,
)
