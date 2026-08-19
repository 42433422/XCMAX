"""
Approval workspace 应用服务（自 fastapi_routes/approval 下沉）。

为前端 ``frontend/src/api/approval.ts`` 提供数据源；底层使用
``app/db/models/approval.py`` 中的 ORM 模型，每个状态变更同时写入
``approval_records`` 与 ``ai_action_audit``，构建完整审计轨迹。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime
from typing import Any, cast

from fastapi import Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.application.approval_notifications import completed_workflow_notification
from app.application.mobile_push_app_service import notify_mobile_user
from app.application.workflow.approval_persistence import (
    AGENT_RUN_UNAVAILABLE_CODE,
    WORKFLOW_EXECUTION_FAILED_CODE,
    WORKFLOW_EXECUTION_SUCCESS_CODE,
    WORKFLOW_PLAN_UNAVAILABLE_CODE,
    WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE,
    canonical_workflow_outcome,
)
from app.db.models.approval import (
    ApprovalAction,
    ApprovalFlow,
    ApprovalFlowNode,
    ApprovalRecord,
    ApprovalRequest,
    ApprovalStatus,
)
from app.db.models.user import User
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)

AI_WORKFLOW_BUSINESS_TYPE = "workflow_tool"
AI_WORKFLOW_NODE_NAME = "AI 工作流审批"


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


from app.application.approval_workspace_app_service_part01 import (
    _ai_workflow_audit_node as _ai_workflow_audit_node,
)
from app.application.approval_workspace_app_service_part01 import (
    _allow_x_user_id_header as _allow_x_user_id_header,
)
from app.application.approval_workspace_app_service_part01 import (
    _approve_ai_workflow_request_without_node as _approve_ai_workflow_request_without_node,
)
from app.application.approval_workspace_app_service_part01 import (
    _audit as _audit,
)
from app.application.approval_workspace_app_service_part01 import (
    _can_review_ai_workflow_request as _can_review_ai_workflow_request,
)
from app.application.approval_workspace_app_service_part01 import (
    _close_request_if_needed as _close_request_if_needed,
)
from app.application.approval_workspace_app_service_part01 import (
    _drop_pending_ai_workflow_after_rejection as _drop_pending_ai_workflow_after_rejection,
)
from app.application.approval_workspace_app_service_part01 import (
    _generate_request_no as _generate_request_no,
)
from app.application.approval_workspace_app_service_part01 import (
    _has_pending_ai_workflow as _has_pending_ai_workflow,
)
from app.application.approval_workspace_app_service_part01 import (
    _is_ai_workflow_request as _is_ai_workflow_request,
)
from app.application.approval_workspace_app_service_part01 import (
    _next_node as _next_node,
)
from app.application.approval_workspace_app_service_part01 import (
    _node_query_for_user as _node_query_for_user,
)
from app.application.approval_workspace_app_service_part01 import (
    _ordered_nodes as _ordered_nodes,
)
from app.application.approval_workspace_app_service_part01 import (
    _persist_ai_workflow_outcome as _persist_ai_workflow_outcome,
)
from app.application.approval_workspace_app_service_part01 import (
    _request_to_dict as _request_to_dict,
)
from app.application.approval_workspace_app_service_part01 import (
    _resolve_actor as _resolve_actor,
)
from app.application.approval_workspace_app_service_part01 import (
    _resume_pending_ai_workflow_after_approval as _resume_pending_ai_workflow_after_approval,
)
from app.application.approval_workspace_app_service_part01 import (
    _safe_workflow_node_count as _safe_workflow_node_count,
)
from app.application.approval_workspace_app_service_part01 import (
    cleanup_requests as cleanup_requests,
)
from app.application.approval_workspace_app_service_part01 import (
    get_request_detail as get_request_detail,
)
from app.application.approval_workspace_app_service_part01 import (
    list_requests as list_requests,
)
from app.application.approval_workspace_app_service_part01 import (
    submit_request as submit_request,
)
from app.application.approval_workspace_app_service_part02 import (
    _normalize_statuses as _normalize_statuses,
)
from app.application.approval_workspace_app_service_part02 import (
    approve_request as approve_request,
)
from app.application.approval_workspace_app_service_part02 import (
    check_approver_orphan as check_approver_orphan,
)
from app.application.approval_workspace_app_service_part02 import (
    create_flow as create_flow,
)
from app.application.approval_workspace_app_service_part02 import (
    delete_flow as delete_flow,
)
from app.application.approval_workspace_app_service_part02 import (
    delete_request as delete_request,
)
from app.application.approval_workspace_app_service_part02 import (
    get_approval_users as get_approval_users,
)
from app.application.approval_workspace_app_service_part02 import (
    get_flow_detail as get_flow_detail,
)
from app.application.approval_workspace_app_service_part02 import (
    list_flows as list_flows,
)
from app.application.approval_workspace_app_service_part02 import (
    process_approval_timeouts_endpoint as process_approval_timeouts_endpoint,
)
from app.application.approval_workspace_app_service_part02 import (
    reject_request as reject_request,
)
from app.application.approval_workspace_app_service_part02 import (
    toggle_flow_active as toggle_flow_active,
)
from app.application.approval_workspace_app_service_part02 import (
    update_flow as update_flow,
)
from app.application.approval_workspace_app_service_part02 import (
    withdraw_request as withdraw_request,
)

# ruff: noqa: F401

_FINAL_STATUSES: tuple[str, ...] = (ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value, ApprovalStatus.WITHDRAWN.value, ApprovalStatus.CANCELLED.value)
