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
    _ai_workflow_audit_node,
    _allow_x_user_id_header,
    _approve_ai_workflow_request_without_node,
    _audit,
    _can_review_ai_workflow_request,
    _close_request_if_needed,
    _drop_pending_ai_workflow_after_rejection,
    _generate_request_no,
    _has_pending_ai_workflow,
    _is_ai_workflow_request,
    _next_node,
    _node_query_for_user,
    _ordered_nodes,
    _persist_ai_workflow_outcome,
    _request_to_dict,
    _resolve_actor,
    _resume_pending_ai_workflow_after_approval,
    _safe_workflow_node_count,
    cleanup_requests,
    get_request_detail,
    list_requests,
    submit_request,
)
from app.application.approval_workspace_app_service_part02 import (
    _normalize_statuses,
    approve_request,
    check_approver_orphan,
    create_flow,
    delete_flow,
    delete_request,
    get_approval_users,
    get_flow_detail,
    list_flows,
    process_approval_timeouts_endpoint,
    reject_request,
    toggle_flow_active,
    update_flow,
    withdraw_request,
)

# ruff: noqa: F401

_FINAL_STATUSES: tuple[str, ...] = (
    ApprovalStatus.APPROVED.value,
    ApprovalStatus.REJECTED.value,
    ApprovalStatus.WITHDRAWN.value,
    ApprovalStatus.CANCELLED.value,
)
