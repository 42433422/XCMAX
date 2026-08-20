# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


from modstore_server.mod_scaffold_runner_part02_part01_part01 import (
    global_registered_employee_ids as global_registered_employee_ids,
    employee_pack_compileall_errors as employee_pack_compileall_errors,
    _collect_pack_depends_on_ids as _collect_pack_depends_on_ids,
    _collect_pack_skill_paths as _collect_pack_skill_paths,
    _manifest_validation_stage as _manifest_validation_stage,
    _consistency_check_stage as _consistency_check_stage,
    _xcemp_validation_stage as _xcemp_validation_stage,
    run_employee_pack_code_validation_report as run_employee_pack_code_validation_report,
)
from modstore_server.mod_scaffold_runner_part02_part01_part02 import (
    resolve_llm_provider_model as resolve_llm_provider_model,
    resolve_llm_provider_model_auto as resolve_llm_provider_model_auto,
)
