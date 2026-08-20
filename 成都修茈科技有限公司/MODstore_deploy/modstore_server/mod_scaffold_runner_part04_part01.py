# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


from modstore_server.mod_scaffold_runner_part04_part01_part01 import (
    run_mod_suite_ai_scaffold_async as run_mod_suite_ai_scaffold_async,
    _index_mod_with_vibe as _index_mod_with_vibe,
    attach_nl_workflow_to_employee_pack_dir as attach_nl_workflow_to_employee_pack_dir,
)
from modstore_server.mod_scaffold_runner_part04_part01_part02 import (
    run_employee_ai_scaffold_async as run_employee_ai_scaffold_async,
)
