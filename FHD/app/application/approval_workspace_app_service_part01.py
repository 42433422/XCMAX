# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# ruff: noqa: E402, F401
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.approval_workspace_app_service")


from app.application.approval_workspace_app_service_part01_part01 import (
    _ai_workflow_audit_node,
    _allow_x_user_id_header,
    _audit,
    _can_review_ai_workflow_request,
    _generate_request_no,
    _has_pending_ai_workflow,
    _is_ai_workflow_request,
    _next_node,
    _node_query_for_user,
    _ordered_nodes,
    _request_to_dict,
    _resolve_actor,
    cleanup_requests,
    get_request_detail,
    list_requests,
)
from app.application.approval_workspace_app_service_part01_part02 import (
    _close_request_if_needed,
    _drop_pending_ai_workflow_after_rejection,
    _persist_ai_workflow_outcome,
    _resume_pending_ai_workflow_after_approval,
    _safe_workflow_node_count,
    submit_request,
)
from app.application.approval_workspace_app_service_part01_part03 import (
    _approve_ai_workflow_request_without_node,
)
