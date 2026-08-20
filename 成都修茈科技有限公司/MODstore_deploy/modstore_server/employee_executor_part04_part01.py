# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


from modstore_server.employee_executor_part04_part01_part01 import (
    _action_wechat_notify as _action_wechat_notify,
    _action_openapi_tool as _action_openapi_tool,
    _tpl_str as _tpl_str,
    _tpl_obj as _tpl_obj,
    _action_fhd_business as _action_fhd_business,
    _merge_original_input_into_reasoning as _merge_original_input_into_reasoning,
    _trusted_system_burn_in_project_root as _trusted_system_burn_in_project_root,
    _trusted_system_duty_contract_execution as _trusted_system_duty_contract_execution,
)
from modstore_server.employee_executor_part04_part01_part02 import (
    _action_agent_runner as _action_agent_runner,
)
