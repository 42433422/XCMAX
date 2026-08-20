# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_bench")


from modstore_server.employee_bench_part03_part01_part01 import (
    _parse_machine_score_from_text as _parse_machine_score_from_text,
    _peer_review_gate_enabled as _peer_review_gate_enabled,
    _peer_review_min_score as _peer_review_min_score,
    _run_pack_peer_review_optional as _run_pack_peer_review_optional,
    _read_employee_brief as _read_employee_brief,
    _collect_reviewer_candidate_ids as _collect_reviewer_candidate_ids,
    _snapshot_reviewer_candidate as _snapshot_reviewer_candidate,
    _dimensions_still_open as _dimensions_still_open,
    _llm_assign_reviewers_to_dimensions as _llm_assign_reviewers_to_dimensions,
    _parse_router_json as _parse_router_json,
    resolve_auto_dimension_reviewers as resolve_auto_dimension_reviewers,
    _load_audit_dimension_env_defaults as _load_audit_dimension_env_defaults,
)
from modstore_server.employee_bench_part03_part01_part02 import (
    _audit_single_pack as _audit_single_pack,
    _run_five_dim_audit as _run_five_dim_audit,
)
