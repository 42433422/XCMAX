# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


from modstore_server.self_maintenance_loop_runner_part05_part01_part01 import (
    _employee_result_ok as _employee_result_ok,
    _delivery_validation_command_failed as _delivery_validation_command_failed,
    _delivery_validation_gate as _delivery_validation_gate,
    _find_delivery_validation as _find_delivery_validation,
    _collect_delivery_validation_candidates as _collect_delivery_validation_candidates,
    _extract_failure_reason as _extract_failure_reason,
    _extract_para_meta as _extract_para_meta,
    _collect_text_fields as _collect_text_fields,
    _extract_report_excerpt as _extract_report_excerpt,
    _is_transient_employee_dispatch_failure as _is_transient_employee_dispatch_failure,
    _coerce_truthy_flag as _coerce_truthy_flag,
    _para_item_is_accepted_wait_timeout as _para_item_is_accepted_wait_timeout,
    _is_accepted_para_wait_timeout as _is_accepted_para_wait_timeout,
    _loop_platform_bench_override as _loop_platform_bench_override,
)
from modstore_server.self_maintenance_loop_runner_part05_part01_part02 import (
    _execute_employee_task_with_retries as _execute_employee_task_with_retries,
    _run_step_with_inner_retries as _run_step_with_inner_retries,
)
