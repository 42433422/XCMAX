# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


from modstore_server.self_maintenance_loop_runner_part06_part01_part01 import (
    _fetch_para_task_report_excerpt as _fetch_para_task_report_excerpt,
    _fetch_para_task_state as _fetch_para_task_state,
    _reconcile_requested_merge_feedback as _reconcile_requested_merge_feedback,
    _base_para_input as _base_para_input,
    _python_supports_focused_tests as _python_supports_focused_tests,
    _focused_test_command as _focused_test_command,
    _code_task_text as _code_task_text,
)
from modstore_server.self_maintenance_loop_runner_part06_part01_part02 import (
    _evaluate_retort_clarification_before_review as _evaluate_retort_clarification_before_review,
    _review_task_text as _review_task_text,
    _qa_task_text as _qa_task_text,
    _json_after_marker as _json_after_marker,
)
