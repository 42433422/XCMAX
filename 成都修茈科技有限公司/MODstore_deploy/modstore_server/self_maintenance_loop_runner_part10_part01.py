# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


from modstore_server.self_maintenance_loop_runner_part10_part01_part01 import (
    _wait_for_para_device_online as _wait_for_para_device_online,
    _mark_para_task_merged as _mark_para_task_merged,
    _request_para_task_merge as _request_para_task_merge,
    _loop_steps_roster_gate as _loop_steps_roster_gate,
    _auto_merge_low_risk_branch as _auto_merge_low_risk_branch,
)
from modstore_server.self_maintenance_loop_runner_part10_part01_part02 import (
    _auto_merge_local_repo as _auto_merge_local_repo,
    _auto_dispatch_deploy_envs as _auto_dispatch_deploy_envs,
    _dispatch_fhd_deploy_action as _dispatch_fhd_deploy_action,
    _dispatch_deploy_for_merge as _dispatch_deploy_for_merge,
    _emit_deploy_callback as _emit_deploy_callback,
    _record_verified_deploy_employee_metric as _record_verified_deploy_employee_metric,
    _append_deploy_receipt_event as _append_deploy_receipt_event,
)
from modstore_server.self_maintenance_loop_runner_part10_part01_part03 import (
    _run_deploy_receipts_after_merge as _run_deploy_receipts_after_merge,
)
