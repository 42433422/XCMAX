# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


from modstore_server.self_maintenance_loop_runner_part03_part01_part01 import (
    _close_items_resolved_by_final as _close_items_resolved_by_final,
    _resume_review_qa_candidate as _resume_review_qa_candidate,
    _resume_steps as _resume_steps,
    _resume_dispatch_context as _resume_dispatch_context,
    _parse_iso as _parse_iso,
    _file_url_to_path as _file_url_to_path,
    _self_maintenance_actor_user_id as _self_maintenance_actor_user_id,
)
from modstore_server.self_maintenance_loop_runner_part03_part01_part02 import (
    _recent_employee_failure_count as _recent_employee_failure_count,
    _recent_incident_signals as _recent_incident_signals,
    evaluate_self_maintenance_need as evaluate_self_maintenance_need,
    _last_started_at as _last_started_at,
)
