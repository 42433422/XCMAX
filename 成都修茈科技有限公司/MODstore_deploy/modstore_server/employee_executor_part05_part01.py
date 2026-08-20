# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


from modstore_server.employee_executor_part05_part01_part01 import (
    _employee_pack_extract_root as _employee_pack_extract_root,
    _action_direct_python as _action_direct_python,
    _prefer_para_with_local_fallback as _prefer_para_with_local_fallback,
    _filter_handlers_vibe_coding_maintainer as _filter_handlers_vibe_coding_maintainer,
)
from modstore_server.employee_executor_part05_part01_part02 import (
    _actions_real as _actions_real,
    _extract_token_count as _extract_token_count,
)
