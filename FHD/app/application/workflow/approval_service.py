from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

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
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            # fail-closed：风险注册表缺失或查询异常时默认要求审批，绝不静默放行写动作。
            logger.warning(
                "risk_actions registry lookup failed; fail-closed requiring approval for %s.%s",
                node.tool_id,
                node.action,
            )
            return True
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
                    and str(value) not in str(actual)
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

        # 同时持久化到 DB（防止重启丢失，且与 /api/approval/requests 工作台共享可见性）。
        # 携带 plan 使持久化层能写入绑定 request_no 的可靠工作流快照，供重启后重建/续跑。
        metadata = self._persist_request_to_db(request, runtime_context=runtime_context, plan=plan)
        if metadata is None and require_persistence:
            self._pending_requests.pop(request_id, None)
            self._pending_workflows.pop(request_id, None)
            raise RuntimeError("审批请求未能持久化，已阻止数据库写入")
        if metadata is not None:
            self._request_metadata[request_id] = metadata
        return request

    def _persist_request_to_db(
        self,
        request: ApprovalRequest,
        runtime_context: dict[str, Any] | None = None,
        *,
        plan: PlanGraph | None = None,
    ) -> dict[str, Any] | None:
        """将内存审批请求写入 DB approval_requests 表（幂等且外键完整）。

        ``plan`` 非空时一并持久化绑定 request_no 的可靠工作流快照（完整计划 + 安全
        运行上下文），使进程重启后仍可据此重建并继续执行获批计划。
        """
        from app.application.workflow.approval_persistence import persist_workflow_approval

        return persist_workflow_approval(
            request,
            runtime_context,
            flow_key=self._AI_WORKFLOW_FLOW_KEY,
            plan=plan,
        )

    def get_request_metadata(self, request_id: str) -> dict[str, Any] | None:
        metadata = self._request_metadata.get(request_id)
        return dict(metadata) if metadata is not None else None

    def get_pending_workflow(self, request_id: str) -> dict[str, Any] | None:
        return self._pending_workflows.get(request_id)

    def load_durable_workflow_snapshot(self, request_id: str) -> dict[str, Any] | None:
        """从 DB 加载绑定 ``request_no`` 的可靠工作流快照（获批后可据此重建/续跑）。

        仅返回经过严格校验（存在、匹配、可执行、非拒绝终态）的快照；缺失/畸形/
        不匹配一律 ``None``（fail-closed），绝不把 DB 的通用 status/text 当作可执行
        工作流的证明。
        """
        from app.application.workflow.approval_persistence import load_durable_workflow_snapshot

        return load_durable_workflow_snapshot(request_id, allow_terminal=True)

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
        from app.application.workflow.approval_persistence import persist_agent_run_link

        persist_agent_run_link(
            request_id,
            agent_run_id=agent_run_id,
            approved_step_id=approved_step_id,
        )
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

    def get_requests_by_plan(self, plan_id: str) -> list[ApprovalRequest]:
        """返回某计划下的全部审批请求（含 PENDING/APPROVED/REJECTED/CANCELLED）。"""
        return [req for req in self._pending_requests.values() if req.plan_id == plan_id]

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
        # 不应只查 PENDING 请求：审批通过后状态变 APPROVED，此时仍应能判定为已批准。
        approved = next(
            (
                req
                for req in self.get_requests_by_plan(plan_id)
                if req.status == ApprovalStatus.APPROVED
            ),
            None,
        )
        return approved is not None

    def is_rejected(self, plan_id: str) -> bool:
        rejected = next(
            (
                req
                for req in self.get_requests_by_plan(plan_id)
                if req.status == ApprovalStatus.REJECTED
            ),
            None,
        )
        return rejected is not None

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
                    logger.debug("neuro_notify_approval_changed skipped")
    except RECOVERABLE_ERRORS as e:
        logger.error("审批超时处理失败 type=%s", type(e).__name__)
        return {"success": False, "error": "approval_timeout_processing_failed", "processed": 0}

    return {"success": True, "processed": len(results), "results": results}


def reload_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is not None:
        _approval_service.reload_config()
    return get_approval_service()
