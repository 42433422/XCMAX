from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.application.workflow.types import (
    ApprovalRequest,
    PlanGraph,
    plan_from_dict,
    plan_to_dict,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 可靠工作流快照在 ``business_data`` 中的键：用于在进程重启后重建/续跑获批计划。
# 仅凭 DB 的 request/status/text 不足以证明存在可执行工作流，必须依赖本快照。
SNAPSHOT_KEY = "durable_workflow_snapshot"
SNAPSHOT_VERSION = 1

# 可靠 AI 工作流执行结束后的终态（原子真值，杜绝重放且失败如实）。
# 复用既有 ApprovalStatus，绝不新增状态字符串：
# - 成功执行 → ``approved``（正常获批终态，工作台过滤器可见）。
# - 执行失败 → ``cancelled``（既有取消态）。
# 两者都是终态，不被任何加载器接受（预审批仅 pending、执行恢复仅 approved），
# 因此重复审批无法重新进入、无法重放业务。
# ``workflow_execution`` 业务数据中的有界安全代码（绝不落原始异常正文）。
WORKFLOW_EXECUTION_SUCCESS_CODE = "workflow_execution_success"
WORKFLOW_EXECUTION_FAILED_CODE = "workflow_execution_failed"
AGENT_RUN_UNAVAILABLE_CODE = "agent_run_unavailable"
WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE = "workflow_snapshot_unavailable"
WORKFLOW_PLAN_UNAVAILABLE_CODE = "workflow_plan_unavailable"

_SAFE_OUTCOME_MESSAGES = {
    WORKFLOW_EXECUTION_SUCCESS_CODE: "AI 工作流执行完成",
    WORKFLOW_EXECUTION_FAILED_CODE: "AI 工作流执行失败",
    AGENT_RUN_UNAVAILABLE_CODE: "Agent Run 不可用",
    WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE: "持久化工作流快照不可用",
    WORKFLOW_PLAN_UNAVAILABLE_CODE: "工作流计划不可用",
}


def canonical_workflow_outcome(*, success: bool, code: str = "") -> tuple[str, str]:
    """返回固定的安全结果码/消息，不处理或转发任何底层文本。"""
    if success:
        safe_code = WORKFLOW_EXECUTION_SUCCESS_CODE
    else:
        requested = str(code or "").strip()
        safe_code = (
            requested
            if requested
            in {
                WORKFLOW_EXECUTION_FAILED_CODE,
                AGENT_RUN_UNAVAILABLE_CODE,
                WORKFLOW_SNAPSHOT_UNAVAILABLE_CODE,
                WORKFLOW_PLAN_UNAVAILABLE_CODE,
            }
            else WORKFLOW_EXECUTION_FAILED_CODE
        )
    return safe_code, _SAFE_OUTCOME_MESSAGES[safe_code]


def _build_workflow_snapshot(
    request: ApprovalRequest,
    runtime_context: dict[str, Any] | None,
    plan: PlanGraph | None,
) -> dict[str, Any]:
    """构造绑定 ``request_no`` 的精确工作流快照（含完整计划与安全运行上下文）。

    ``tenant_id`` 记录创建时的当前租户，供加载时做租户绑定校验（租户错配即 fail-closed）。
    """
    from app.infrastructure.tenant_scope import current_tenant_id

    return {
        "version": SNAPSHOT_VERSION,
        "plan_id": request.plan_id,
        "tenant_id": current_tenant_id(),
        "node": {
            "node_id": request.node_id,
            "tool_id": request.tool_id,
            "action": request.action,
            "params": dict(request.params or {}),
        },
        "plan": plan_to_dict(plan) if plan is not None else None,
        "runtime_context": dict(runtime_context or {}),
        "agent_run_id": "",
        "approved_step_id": "",
    }


def _is_valid_plan_for_snapshot(plan: PlanGraph | None) -> bool:
    """仅对可恢复的合法计划持久化可靠快照。

    合法 = 有 plan_id、至少一个节点，且每个节点都有 node_id/tool_id/action。
    计划不完整/缺失时视为无快照（加载侧会 fail-closed），绝不把坏计划写为可执行证明。
    """
    if plan is None:
        return False
    if not str(plan.plan_id or "").strip() or not plan.nodes:
        return False
    return all(
        str(n.node_id or "") and str(n.tool_id or "") and str(n.action or "") for n in plan.nodes
    )


def _resolve_applicant(db, runtime_context: dict[str, Any] | None):
    from app.db.models.user import User

    context = runtime_context or {}
    raw = next(
        (
            context.get(key)
            for key in ("local_user_id", "actor_id", "user_id")
            if context.get(key) not in (None, "")
        ),
        None,
    )
    if raw is None:
        return None
    text_value = str(raw).strip()
    if text_value.isdigit():
        return db.query(User).filter(User.id == int(text_value), User.is_active == True).first()  # noqa: E712

    user = (
        db.query(User)
        .filter(User.username == text_value, User.is_active == True)  # noqa: E712
        .first()
    )
    if user is not None:
        return user
    matches = (
        db.query(User)
        .filter(
            (User.email == text_value) | (User.display_name == text_value),
            User.is_active == True,  # noqa: E712
        )
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def persist_workflow_approval(
    request: ApprovalRequest,
    runtime_context: dict[str, Any] | None,
    *,
    flow_key: str,
    plan: PlanGraph | None = None,
) -> dict[str, Any] | None:
    """Persist an interactive AI approval with complete foreign keys and audit linkage.

    一并持久化绑定 ``request_no`` 的可靠工作流快照（完整计划 + 安全运行上下文），
    使进程重启后仍可据此重建/续跑获批计划。
    """
    try:
        from app.db.models.approval import (
            ApprovalFlow,
            ApprovalFlowNode,
        )
        from app.db.models.approval import (
            ApprovalRequest as ApprovalRequestModel,
        )
        from app.db.session import get_db

        with get_db() as db:
            existing = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request.request_id)
                .first()
            )
            if existing is not None:
                metadata = {
                    "id": int(existing.id),
                    "request_no": str(existing.request_no),
                    "approval_path": (
                        "/mod/xcagi-approval-bridge/approval-hub/workspace"
                        f"?request_no={existing.request_no}"
                    ),
                }
            else:
                applicant = _resolve_applicant(db, runtime_context)
                if applicant is None:
                    raise RuntimeError("无法从当前登录会话解析审批申请人")
                flow = db.query(ApprovalFlow).filter(ApprovalFlow.flow_key == flow_key).first()
                if flow is None:
                    flow = ApprovalFlow(
                        flow_key=flow_key,
                        flow_name="AI 工作流逐笔审批",
                        description="桌面智能对话数据库写操作的逐笔人工审批",
                        business_type="workflow_tool",
                        node_type="serial",
                        allow_transfer=False,
                        allow_delegate=False,
                        allow_withdraw=True,
                        timeout_hours=48,
                        is_active=True,
                        is_deleted=False,
                        created_by=int(applicant.id),
                    )
                    db.add(flow)
                    db.flush()
                audit_node = (
                    db.query(ApprovalFlowNode)
                    .filter(
                        ApprovalFlowNode.flow_id == flow.id,
                        ApprovalFlowNode.node_name == "AI 工作流审批留痕",
                    )
                    .first()
                )
                if audit_node is None:
                    audit_node = ApprovalFlowNode(
                        flow_id=int(flow.id),
                        node_name="AI 工作流审批留痕",
                        node_order=1,
                        node_type="serial",
                        approver_type="applicant",
                        approver_ids=None,
                        min_approvals=1,
                        is_active=True,
                    )
                    db.add(audit_node)
                    db.flush()

                business_data = {
                    "plan_id": request.plan_id,
                    "node_id": request.node_id,
                    "tool_id": request.tool_id,
                    "action": request.action,
                    "params": request.params or {},
                }
                # 仅对合法计划写入绑定 request_no 的可靠工作流快照；坏/缺计划不落快照。
                if _is_valid_plan_for_snapshot(plan):
                    business_data[SNAPSHOT_KEY] = _build_workflow_snapshot(
                        request, runtime_context, plan
                    )
                persisted = ApprovalRequestModel(
                    request_no=request.request_id,
                    flow_id=int(flow.id),
                    business_type="workflow_tool",
                    business_data=json.dumps(business_data, ensure_ascii=False, default=str),
                    applicant_id=int(applicant.id),
                    applicant_name=str(
                        applicant.display_name or applicant.username or applicant.id
                    ),
                    title=f"智能对话写操作：{request.tool_id}.{request.action}",
                    description=json.dumps(request.params or {}, ensure_ascii=False, default=str)[
                        :500
                    ],
                    current_node_id=None,
                    current_node_order=0,
                    status="pending",
                    priority="normal",
                    submitted_at=request.created_at or datetime.now(),
                    created_at=request.created_at or datetime.now(),
                )
                db.add(persisted)
                db.flush()
                try:
                    db.execute(
                        text(
                            "INSERT INTO ai_action_audit (actor, action, payload) "
                            "VALUES (:actor, :action, :payload)"
                        ),
                        {
                            "actor": str(applicant.id),
                            "action": "approval.submit_ai_workflow",
                            "payload": json.dumps(
                                {
                                    "approval_request_id": persisted.id,
                                    "request_no": persisted.request_no,
                                    "plan_id": request.plan_id,
                                    "node_id": request.node_id,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                except (*RECOVERABLE_ERRORS, SQLAlchemyError):
                    logger.warning("AI 审批提交审计写入失败")
                metadata = {
                    "id": int(persisted.id),
                    "request_no": str(persisted.request_no),
                    "flow_id": int(flow.id),
                    "audit_node_id": int(audit_node.id),
                    "applicant_id": int(applicant.id),
                    "approval_path": (
                        "/mod/xcagi-approval-bridge/approval-hub/workspace"
                        f"?request_no={persisted.request_no}"
                    ),
                }

        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_approval_changed

            neuro_notify_approval_changed(
                "created",
                approval_id=request.request_id,
                flow_id=str(metadata.get("flow_id") or ""),
            )
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_approval_changed skipped")
        return metadata
    except (*RECOVERABLE_ERRORS, SQLAlchemyError) as exc:
        # 有界日志：仅记录异常类型，不向日志暴露原始 DB/异常正文（避免泄露内部细节）。
        logger.warning(
            "AI 审批持久化到 DB 失败 request_no=%s type=%s",
            request.request_id,
            type(exc).__name__,
        )
        return None


def persist_agent_run_link(
    request_id: str,
    *,
    agent_run_id: str,
    approved_step_id: str,
) -> None:
    try:
        from app.db.models.approval import ApprovalRequest as ApprovalRequestModel
        from app.db.session import get_db

        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_id)
                .first()
            )
            if persisted is None:
                return
            business_data = json.loads(persisted.business_data) if persisted.business_data else {}
            business_data["agent_run_id"] = str(agent_run_id or "").strip()
            business_data["approved_step_id"] = str(approved_step_id or "").strip()
            snapshot = business_data.get(SNAPSHOT_KEY)
            if isinstance(snapshot, dict):
                snapshot["agent_run_id"] = str(agent_run_id or "").strip()
                snapshot["approved_step_id"] = str(approved_step_id or "").strip()
            business_data[SNAPSHOT_KEY] = snapshot
            persisted.business_data = json.dumps(business_data, ensure_ascii=False, default=str)
            db.commit()
    except (*RECOVERABLE_ERRORS, SQLAlchemyError) as exc:
        logger.warning("AI 审批关联 Agent Run 持久化失败 type=%s", type(exc).__name__)


def _safe_plan_from_snapshot(plan_data: Any) -> PlanGraph | None:
    """从快照精确还原 ``PlanGraph``；结构不合法返回 ``None``（fail-closed）。"""
    if not isinstance(plan_data, dict):
        return None
    nodes = plan_data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    if not str(plan_data.get("plan_id") or ""):
        return None
    try:
        plan = plan_from_dict(plan_data)
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    if plan is None or not plan.nodes:
        return None
    return plan


def _validated_snapshot(persisted) -> dict[str, Any] | None:
    """对已加载的审批请求做快照结构/匹配/租户校验，返回可执行快照或 ``None``（fail-closed）。

    校验：非 ``workflow_tool`` / 快照缺失 / 畸形 / 版本不符 / 计划不完整 / 计划无匹配节点
    / 租户错配 / 跨请求替换 → ``None``。调用方负责状态与重放守卫。
    """
    from app.infrastructure.tenant_scope import current_tenant_id

    if str(persisted.business_type or "").strip() != "workflow_tool":
        return None
    try:
        business_data = json.loads(persisted.business_data) if persisted.business_data else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(business_data, dict):
        return None
    snapshot = business_data.get(SNAPSHOT_KEY)
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("version") != SNAPSHOT_VERSION:
        return None
    plan_id = str(snapshot.get("plan_id") or "")
    if not plan_id:
        return None
    node = snapshot.get("node")
    if (
        not isinstance(node, dict)
        or not str(node.get("node_id") or "")
        or not str(node.get("tool_id") or "")
        or not str(node.get("action") or "")
    ):
        return None
    node_id = str(node.get("node_id") or "")
    node_tool = str(node.get("tool_id") or "")
    node_action = str(node.get("action") or "")
    # 跨请求替换守卫：快照的 plan_id/node_id/tool_id/action/params 必须与
    # 请求编码的 business_data 顶层精确一致；快照与请求 params 都必须是真实 dict。
    biz_params = business_data.get("params")
    if not isinstance(biz_params, dict):
        return None
    node_params = node.get("params")
    if not isinstance(node_params, dict):
        return None
    if (
        str(business_data.get("plan_id") or "") != plan_id
        or str(business_data.get("node_id") or "") != node_id
        or str(business_data.get("tool_id") or "") != node_tool
        or str(business_data.get("action") or "") != node_action
        or biz_params != node_params
    ):
        return None
    plan = _safe_plan_from_snapshot(snapshot.get("plan"))
    if plan is None:
        return None
    # 还原的计划必须与快照 plan_id 完全一致（防跨计划替换）。
    if str(getattr(plan, "plan_id", "") or "") != plan_id:
        return None
    # 计划必须包含与快照节点精确匹配的节点（node_id + tool_id + action + params）。
    plan_node = next((n for n in plan.nodes if n.node_id == node_id), None)
    if plan_node is None:
        return None
    plan_node_params = plan_node.params
    if not isinstance(plan_node_params, dict):
        return None
    if (
        plan_node.tool_id != node_tool
        or plan_node.action != node_action
        or plan_node_params != node_params
    ):
        return None
    # 租户绑定守卫：快照必须记录有效整数租户，且当前租户必须存在并与之相等；
    # 任一缺失/非法/不匹配一律 fail-closed（绝不放行 tenant_id=null 或无租户快照）。
    try:
        snapshot_tenant_int = int(snapshot.get("tenant_id"))
    except (TypeError, ValueError):
        return None
    current = current_tenant_id()
    if current is None:
        return None
    try:
        current_int = int(current)
    except (TypeError, ValueError):
        return None
    if current_int != snapshot_tenant_int:
        return None
    runtime_context = snapshot.get("runtime_context")
    if not isinstance(runtime_context, dict):
        runtime_context = {}
    return {
        "plan": plan,
        "runtime_context": runtime_context,
        "plan_id": plan_id,
        "agent_run_id": str(snapshot.get("agent_run_id") or "").strip(),
        "approved_step_id": str(snapshot.get("approved_step_id") or "").strip(),
    }


def load_durable_workflow_snapshot(
    request_id: str,
    *,
    allow_terminal: bool = False,
) -> dict[str, Any] | None:
    """严格加载绑定 ``request_no`` 的可靠工作流快照（fail-closed）。

    - 请求不存在 / 非 ``workflow_tool`` / 快照缺失 / 畸形 / 版本不符 / 计划不完整
      / 计划无匹配节点 / 租户错配 / 跨请求替换 → ``None``。
    - ``allow_terminal=False``（工作台列表/详情/审批门）：仅 ``pending`` 可恢复；
      其它任何状态一律 fail-closed。
    - ``allow_terminal=True``（获批后恢复执行）：仅 ``approved`` 这一个可执行获批态；
      ``pending`` 与 rejected/cancelled/withdrawn 等任意/终态一律拒绝，杜绝重复审批重新进入。
    - 重放守卫：一旦写入 ``workflow_execution``（无论成/败）即已执行过，一律拒绝。
    """
    from app.db.models.approval import (
        ApprovalRequest as ApprovalRequestModel,
    )
    from app.db.session import get_db

    try:
        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_id)
                .first()
            )
            if persisted is None:
                return None
            status = str(persisted.status or "").strip()
            # 精确状态守卫：预审批仅 pending；执行恢复仅 approved。
            required = "approved" if allow_terminal else "pending"
            if status != required:
                return None
            try:
                business_data = (
                    json.loads(persisted.business_data) if persisted.business_data else {}
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
            if not isinstance(business_data, dict):
                return None
            # 重放守卫：一旦写入 ``workflow_execution``，说明该请求的工作流已被执行过
            # （无论成/败）并落为终态；后续任何恢复调用都必须拒绝，杜绝重复审批重放业务。
            if "workflow_execution" in business_data:
                return None
            return _validated_snapshot(persisted)
    except (*RECOVERABLE_ERRORS, SQLAlchemyError):
        logger.warning("load durable workflow snapshot failed request_no=%s", request_id)
        return None


def load_workflow_snapshot_for_execution(request_id: str) -> dict[str, Any] | None:
    """获批后恢复执行专用的严格加载器（fail-closed，绝不重放）。

    状态守卫：仅接受预终态 ``pending`` / ``in_progress``（审批尚未写库终态时调用）；
    任何终态一律拒绝——尤其 ``cancelled``（执行失败/取消）与 ``approved``（已获批成功），
    杜绝重复审批重新进入业务。
    重放守卫：一旦写入 ``workflow_execution``（无论成/败）即已执行过，一律拒绝。
    """
    from app.db.models.approval import (
        ApprovalRequest as ApprovalRequestModel,
    )
    from app.db.session import get_db

    try:
        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_id)
                .first()
            )
            if persisted is None:
                return None
            status = str(persisted.status or "").strip()
            if status not in ("pending", "in_progress"):
                return None
            try:
                business_data = (
                    json.loads(persisted.business_data) if persisted.business_data else {}
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
            if not isinstance(business_data, dict):
                return None
            # 重放守卫：已经执行过（workflow_execution 已落）→ 拒绝再现，杜绝重放。
            if "workflow_execution" in business_data:
                return None
            return _validated_snapshot(persisted)
    except (*RECOVERABLE_ERRORS, SQLAlchemyError):
        logger.warning("load workflow snapshot for execution failed request_no=%s", request_id)
        return None


def mark_durable_request_approved_and_load(request_id: str) -> dict[str, Any] | None:
    """直接恢复路径：把仍为 ``pending`` 的可靠请求过渡到获批态并加载可执行快照。

    - 仅接受精确 ``pending``（预审批可用态）；已完成/失败/拒绝/取消/撤回等任意终态
      一律 fail-closed（拒绝重复审批重新进入）。
    - 快照绑定校验与预审批加载（``allow_terminal=False``）完全一致：存在/匹配/可执行/
      租户绑定任一不符即返回 ``None`` 且不写状态。
    """
    from app.db.models.approval import (
        ApprovalRequest as ApprovalRequestModel,
    )
    from app.db.session import get_db

    # 先按预审批（pending）严格校验并取得快照；失败即返回 None（不写任何状态）。
    snapshot = load_durable_workflow_snapshot(request_id, allow_terminal=False)
    if snapshot is None:
        return None
    try:
        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_id)
                .first()
            )
            if persisted is None:
                return None
            if str(persisted.status or "").strip() != "pending":
                return None
            if str(persisted.business_type or "").strip() != "workflow_tool":
                return None
            # 仅记录获批时点；审批人由调用方（_approve_ai_workflow_request_*）负责写入，
            # 本函数不涉及 actor，避免越权/失真。
            persisted.status = "approved"
            persisted.approved_at = datetime.now()
            db.commit()
        return snapshot
    except (*RECOVERABLE_ERRORS, SQLAlchemyError) as exc:
        # 有界日志：不向日志暴露原始 DB/异常正文。
        logger.warning(
            "mark durable request approved failed request_no=%s type=%s",
            request_id,
            type(exc).__name__,
        )
        return None


def mark_durable_outcome(
    request_id: str, *, success: bool, code: str = "", message: str = ""
) -> None:
    """原子真值：执行结束后把可靠请求置为终态，杜绝重放且失败如实。

    - 成功 → ``approved``（正常获批终态，工作台过滤器可见）。
    - 失败 → ``cancelled``（既有取消态）。
    - 仅处理 ``workflow_tool`` 可靠请求；其它请求为 no-op。
    - 终态与可执行态（预审批 pending、执行恢复 approved）严格区分，不被任何加载器
      接受，故重复审批无法重新进入、无法重放业务。
    - 绝不静默吞错：失败也落库为 ``cancelled``，且只落固定安全
      代码/消息；``message`` 参数仅为兼容旧调用保留，永不持久化。
    """
    from app.db.models.approval import (
        ApprovalRequest as ApprovalRequestModel,
    )
    from app.db.models.approval import (
        ApprovalStatus,
    )
    from app.db.session import get_db

    del message  # 兼容参数：原始文本不得参与任何持久化或公共输出。
    status = ApprovalStatus.APPROVED.value if success else ApprovalStatus.CANCELLED.value
    safe_code, safe_message = canonical_workflow_outcome(success=success, code=code)
    try:
        with get_db() as db:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_id)
                .first()
            )
            if persisted is None:
                return
            if str(persisted.business_type or "").strip() != "workflow_tool":
                return
            business_data = json.loads(persisted.business_data) if persisted.business_data else {}
            if not isinstance(business_data, dict):
                business_data = {}
            business_data["workflow_execution"] = {
                "status": status,
                "success": bool(success),
                "code": safe_code,
                "message": safe_message,
            }
            persisted.business_data = json.dumps(business_data, ensure_ascii=False, default=str)
            persisted.status = status
            # 执行失败 → 有界 rejection_reason（绝不落原始异常正文），并写入失败审计留痕。
            if not success:
                persisted.rejection_reason = WORKFLOW_EXECUTION_FAILED_CODE
                try:
                    db.execute(
                        text(
                            "INSERT INTO ai_action_audit (actor, action, payload) "
                            "VALUES (:actor, :action, :payload)"
                        ),
                        {
                            "actor": str(persisted.applicant_id or "").strip(),
                            "action": "approval.execute_ai_workflow_failed",
                            "payload": json.dumps(
                                {
                                    "request_no": request_id,
                                    "code": safe_code,
                                    "message": safe_message,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                except (*RECOVERABLE_ERRORS, SQLAlchemyError):
                    logger.warning("AI 审批执行失败审计写入失败 request_no=%s", request_id)
            persisted.updated_at = datetime.now()
            db.commit()
    except (*RECOVERABLE_ERRORS, SQLAlchemyError) as exc:
        # 有界日志：不向日志暴露原始 DB/异常正文。
        logger.warning(
            "mark durable workflow outcome failed request_no=%s type=%s",
            request_id,
            type(exc).__name__,
        )
