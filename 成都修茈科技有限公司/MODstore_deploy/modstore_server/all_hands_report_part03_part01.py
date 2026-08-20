# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.all_hands_report")


from modstore_server.all_hands_report_part03_part01_part01 import (
    _should_standby_manifest_report as _should_standby_manifest_report,
    _craft_pipeline_standby_context as _craft_pipeline_standby_context,
    _is_standby_pipeline_json_noise as _is_standby_pipeline_json_noise,
    _coerce_standby_excerpt as _coerce_standby_excerpt,
    _resolve_employee_pairs as _resolve_employee_pairs,
    _recent_failures as _recent_failures,
    _load_yuangon_employee_meta as _load_yuangon_employee_meta,
    _snapshot_pending_change_requests as _snapshot_pending_change_requests,
    _snapshot_employee_cron_overview as _snapshot_employee_cron_overview,
    _all_hands_role_context as _all_hands_role_context,
)
from modstore_server.all_hands_report_part03_part01_part02 import (
    _manifest_signals as _manifest_signals,
    _standby_manifest_report_via_bench as _standby_manifest_report_via_bench,
    _report_one_employee as _report_one_employee,
)
