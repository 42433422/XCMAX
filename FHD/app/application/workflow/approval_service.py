from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.application.workflow.types import (
    ApprovalRequest,
    ApprovalStatus,
    PlanGraph,
    WorkflowNode,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS
from resources.config.approval_config import (
    ApprovalConfig,
    get_approval_config,
    reload_approval_config,
)

logger = logging.getLogger(__name__)


class ApprovalService:
    _AI_WORKFLOW_FLOW_KEY = "ai-workflow-interactive"

    def __init__(self):
        self._config: ApprovalConfig = get_approval_config()
        self._pending_requests: dict[str, ApprovalRequest] = {}
        self._pending_workflows: dict[str, dict[str, Any]] = {}
        self._request_metadata: dict[str, dict[str, Any]] = {}

    def reload_config(self) -> None:
        self._config = reload_approval_config()

    def is_approval_enabled(self) -> bool:
        return self._config.enabled

    def check_node_requires_approval(self, node: WorkflowNode) -> bool:
        if not self._config.enabled:
            return False

        for rule in self._config.rules:
            if rule.get("tool_id") == node.tool_id and rule.get("action") == node.action:
                trigger = rule.get("trigger", "never")
                if trigger == "always":
                    return True
                elif trigger == "conditional":
                    return self._evaluate_conditions(rule.get("conditions", {}), node)
        try:
            from resources.config.risk_actions_loader import (
                get_action_approval,
                requires_write_approval,
            )

            if get_action_approval(node.tool_id, node.action) in {"always", "interactive"}:
                return True
            if requires_write_approval(node.tool_id, node.action):
                return True
        except Exception:  # noqa: BLE001
            logger.debug("risk_actions registry lookup skipped", exc_info=True)
        return False

    def _evaluate_conditions(self, conditions: dict[str, Any], node: WorkflowNode) -> bool:
        if not conditions:
            return False

        for key, expected in conditions.items():
            actual = node.params.get(key)
            if actual is None:
                return False
            if isinstance(expected, dict):
                op = expected.get("op", "eq")
                value = expected.get("value")
                if (
                    op == "gt"
                    and not (actual > value)
                    or op == "gte"
                    and not (actual >= value)
                    or op == "lt"
                    and not (actual < value)
                    or op == "lte"
                    and not (actual <= value)
                    or op == "neq"
                    and actual == value
                    or op == "eq"
                    and actual != value
                    or op == "contains"
                    and value not in str(actual)
                ):
                    return False
            elif actual != expected:
                return False
        return True

    def get_approval_required_nodes(self, plan: PlanGraph) -> list[WorkflowNode]:
        if not self._config.enabled:
            return []

        required_nodes: list[WorkflowNode] = []
        for node in plan.nodes:
            if self.check_node_requires_approval(node):
                required_nodes.append(node)
        return required_nodes

    def create_approval_request(
        self,
        plan_id: str,
        node: WorkflowNode,
        runtime_context: dict[str, Any] | None = None,
        plan: PlanGraph | None = None,
        require_persistence: bool = False,
    ) -> ApprovalRequest:
        request_id = uuid.uuid4().hex
        request = ApprovalRequest(
            request_id=request_id,
            plan_id=plan_id,
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=node.action,
            params=node.params.copy() if node.params else {},
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(),
        )
        self._pending_requests[request_id] = request
        if plan is not None:
            self._pending_workflows[request_id] = {
                "plan": plan,
                "runtime_context": runtime_context or {},
                "plan_id": plan_id,
            }
        logger.info("创建审批请求: %s for %s.%s", request_id, node.tool_id, node.action)

        # 同时持久化到 DB（防止重启丢失，且与 /api/approval/requests 工作台共享可见性）
        metadata = self._persist_request_to_db(request, runtime_context=runtime_context)
        if metadata is None and require_persistence:
            self._pending_requests.pop(request_id, None)
            self._pending_workflows.pop(request_id, None)
            raise RuntimeError("审批请求未能持久化，已阻止数据库写入")
        if metadata is not None:
            self._request_metadata[request_id] = metadata
        return request

    @staticmethod
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

    def _persist_request_to_db(
        self,
        request: ApprovalRequest,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """将内存审批请求写入 DB approval_requests 表（幂等且外键完整）。"""
        import json as _json

        try:
            from sqlalchemy import text

            from app.db.models.approval import (
                ApprovalFlow as ApprovalFlowModel,
            )
            from app.db.models.approval import (
                ApprovalFlowNode as ApprovalFlowNodeModel,
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
                    applicant = self._resolve_applicant(db, runtime_context)
                    if applicant is None:
                        raise RuntimeError("无法从当前登录会话解析审批申请人")
                    flow = (
                        db.query(ApprovalFlowModel)
                        .filter(ApprovalFlowModel.flow_key == self._AI_WORKFLOW_FLOW_KEY)
                        .first()
                    )
                    if flow is None:
                        flow = ApprovalFlowModel(
                            flow_key=self._AI_WORKFLOW_FLOW_KEY,
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
                        db.query(ApprovalFlowNodeModel)
                        .filter(
                            ApprovalFlowNodeModel.flow_id == flow.id,
                            ApprovalFlowNodeModel.node_name == "AI 工作流审批留痕",
                        )
                        .first()
                    )
                    if audit_node is None:
                        audit_node = ApprovalFlowNodeModel(
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
                    persisted = ApprovalRequestModel(
                        request_no=request.request_id,
                        flow_id=int(flow.id),
                        business_type="workflow_tool",
                        business_data=_json.dumps(business_data, ensure_ascii=False, default=str),
                        applicant_id=int(applicant.id),
                        applicant_name=str(
                            applicant.display_name or applicant.username or applicant.id
                        ),
                        title=f"智能对话写操作：{request.tool_id}.{request.action}",
                        description=_json.dumps(
                            request.params or {}, ensure_ascii=False, default=str
                        )[:500],
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
                                "payload": _json.dumps(
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
                        logger.warning("AI 审批提交审计写入失败", exc_info=True)
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
            # P2 NeuroBus: 广播审批创建事件
            try:
                from app.neuro_bus.application_neuro_bridge import (
                    neuro_notify_approval_changed,
                )

                neuro_notify_approval_changed(
                    "created",
                    approval_id=request.request_id,
                    flow_id=str(metadata.get("flow_id") or ""),
                )
            except RECOVERABLE_ERRORS:
                logger.debug("neuro_notify_approval_changed skipped", exc_info=True)
            return metadata
        except (*RECOVERABLE_ERRORS, SQLAlchemyError) as e:
            logger.warning("AI 审批持久化到 DB 失败: %s", e, exc_info=True)
            return None

    def get_request_metadata(self, request_id: str) -> dict[str, Any] | None:
        metadata = self._request_metadata.get(request_id)
        return dict(metadata) if metadata is not None else None

    def get_pending_workflow(self, request_id: str) -> dict[str, Any] | None:
        return self._pending_workflows.get(request_id)

    def attach_pending_agent_run(
        self,
        request_id: str,
        *,
        agent_run_id: str,
        approved_step_id: str,
    ) -> bool:
        pending = self._pending_workflows.get(request_id)
        if pending is None:
            return False
        pending["agent_run_id"] = str(agent_run_id or "").strip()
        pending["approved_step_id"] = str(approved_step_id or "").strip()
        metadata = self._request_metadata.get(request_id)
        if metadata is not None:
            metadata["agent_run_id"] = str(agent_run_id or "").strip()
        try:
            import json as _json

            from app.db.models.approval import ApprovalRequest as ApprovalRequestModel
            from app.db.session import get_db

            with get_db() as db:
                persisted = (
                    db.query(ApprovalRequestModel)
                    .filter(ApprovalRequestModel.request_no == request_id)
                    .first()
                )
                if persisted is not None:
                    business_data = (
                        _json.loads(persisted.business_data) if persisted.business_data else {}
                    )
                    business_data["agent_run_id"] = str(agent_run_id or "").strip()
                    business_data["approved_step_id"] = str(approved_step_id or "").strip()
                    persisted.business_data = _json.dumps(
                        business_data, ensure_ascii=False, default=str
                    )
                    db.commit()
        except (*RECOVERABLE_ERRORS, SQLAlchemyError):
            logger.warning("AI 审批关联 Agent Run 持久化失败", exc_info=True)
        return True

    def remove_pending_workflow(self, request_id: str) -> dict[str, Any] | None:
        return self._pending_workflows.pop(request_id, None)

    def get_pending_request(self, request_id: str) -> ApprovalRequest | None:
        return self._pending_requests.get(request_id)

    def get_pending_request_by_plan(self, plan_id: str) -> ApprovalRequest | None:
        for req in self._pending_requests.values():
            if req.plan_id == plan_id and req.status == ApprovalStatus.PENDING:
                return req
        return None

    def approve(self, request_id: str, comment: str = "") -> bool:
        request = self._pending_requests.get(request_id)
        if not request:
            logger.warning("审批请求不存在: %s", request_id)
            return False
        if request.status != ApprovalStatus.PENDING:
            logger.warning("审批请求状态不是pending: %s, status=%s", request_id, request.status)
            return False

        request.status = ApprovalStatus.APPROVED
        request.approved_at = datetime.now()
        request.approver_comment = comment
        logger.info("审批通过: %s", request_id)
        return True

    def reject(self, request_id: str, comment: str = "") -> bool:
        request = self._pending_requests.get(request_id)
        if not request:
            logger.warning("审批请求不存在: %s", request_id)
            return False
        if request.status != ApprovalStatus.PENDING:
            logger.warning("审批请求状态不是pending: %s, status=%s", request_id, request.status)
            return False

        request.status = ApprovalStatus.REJECTED
        request.rejected_at = datetime.now()
        request.approver_comment = comment
        logger.info("审批拒绝: %s", request_id)
        return True

    def cancel(self, request_id: str) -> bool:
        request = self._pending_requests.get(request_id)
        if not request:
            return False
        request.status = ApprovalStatus.CANCELLED
        logger.info("审批取消: %s", request_id)
        return True

    def is_approved(self, plan_id: str) -> bool:
        request = self.get_pending_request_by_plan(plan_id)
        return request is not None and request.status == ApprovalStatus.APPROVED

    def is_rejected(self, plan_id: str) -> bool:
        request = self.get_pending_request_by_plan(plan_id)
        return request is not None and request.status == ApprovalStatus.REJECTED

    def get_pending_approval_info(self, plan_id: str) -> dict[str, Any] | None:
        request = self.get_pending_request_by_plan(plan_id)
        if not request:
            return None
        return {
            "request_id": request.request_id,
            "plan_id": request.plan_id,
            "node_id": request.node_id,
            "tool_id": request.tool_id,
            "action": request.action,
            "params": request.params,
            "status": request.status.value,
            "created_at": request.created_at.isoformat() if request.created_at else None,
        }


from app.neuro_bus.neuro_application_instrumentation import instrument_approval_service_class

instrument_approval_service_class(ApprovalService)

_approval_service: ApprovalService | None = None


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service


def process_approval_timeouts() -> dict[str, Any]:
    """
    扫描 DB 中超时的审批请求并自动处理（超时动作：auto_reject / auto_approve / escalate）。

    供定时任务或 /api/approval/process-timeouts 端点调用。
    """
    results: list[dict] = []
    try:
        from datetime import datetime as _dt

        from sqlalchemy import and_

        from app.db.models.approval import ApprovalFlow, ApprovalRequest, ApprovalStatus
        from app.db.session import get_db

        now = _dt.utcnow()
        with get_db() as db:
            expired = (
                db.query(ApprovalRequest)
                .filter(
                    and_(
                        ApprovalRequest.status == ApprovalStatus.PENDING,
                        ApprovalRequest.expired_at != None,  # noqa: E711
                        ApprovalRequest.expired_at < now,
                    )
                )
                .all()
            )
            for req in expired:
                flow = db.query(ApprovalFlow).filter(ApprovalFlow.id == req.flow_id).first()
                timeout_action = "auto_reject"
                if flow:
                    node = next(
                        (n for n in (flow.nodes or []) if n.id == req.current_node_id), None
                    )
                    if node:
                        timeout_action = getattr(node, "timeout_action", None) or "auto_reject"

                if timeout_action == "auto_approve":
                    req.status = ApprovalStatus.APPROVED
                    note = "超时自动通过"
                else:
                    req.status = ApprovalStatus.REJECTED
                    note = "超时自动拒绝"

                results.append({"request_id": req.id, "action": timeout_action, "note": note})
                logger.info("审批超时处理: request_id=%s, action=%s", req.id, timeout_action)

            if results:
                db.commit()
                # P2 NeuroBus: 广播审批超时事件
                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_approval_changed,
                    )

                    for r in results:
                        action = "approved" if r.get("action") == "auto_approve" else "rejected"
                        neuro_notify_approval_changed(
                            action,
                            approval_id=r.get("request_id", ""),
                            decision=r.get("note", ""),
                        )
                except RECOVERABLE_ERRORS:
                    logger.debug("neuro_notify_approval_changed skipped", exc_info=True)
    except RECOVERABLE_ERRORS as e:
        logger.error("审批超时处理失败: %s", e, exc_info=True)
        return {"success": False, "error": str(e), "processed": 0}

    return {"success": True, "processed": len(results), "results": results}


def reload_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is not None:
        _approval_service.reload_config()
    return get_approval_service()
