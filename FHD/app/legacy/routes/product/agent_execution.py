"""Build product mutation plans and translate their approved Agent results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from app.application.workflow.workflow_types import PlanGraph, RiskLevel, WorkflowNode

from .ports import AgentRunView, Payload, ProductAgentRuntime


def _agent_node_output(run: AgentRunView, node_id: str) -> Payload:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output: Payload = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    run_error = str(getattr(run, "error", False) or "")
    if not output.get("success") and run_error and not output.get("message"):
        output["message"] = run_error
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _products_compat_agent_user_id(request: Request, payload: Payload) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "products-compat-route"
    ).strip()


@dataclass(frozen=True)
class ProductAgentExecution:
    registry: Callable[[], Payload]
    create_runtime: Callable[[], ProductAgentRuntime]
    identify_user: Callable[[Request, Payload], str]
    node_output: Callable[[AgentRunView, str], Payload]
    normalize_risk: Callable[[object], RiskLevel]
    route_module: str

    def run(self, *, request: Request, action: str, params: Payload, route_path: str) -> Payload:
        registry = self.registry()
        action_meta = dict((registry.get("products") or {}).get("actions") or {}).get(action)
        if not isinstance(action_meta, dict):
            return {
                "success": False,
                "message": f"未注册的 products 动作: {action}",
                "agent_status": "failed",
            }
        node_id = f"products_{action}_compat"
        user_id = self.identify_user(request, params)
        plan = PlanGraph(
            plan_id=node_id,
            intent=node_id,
            todo_steps=[f"通过 AgentOrchestrator 执行 legacy products.{action}"],
            nodes=[
                WorkflowNode(
                    node_id=node_id,
                    tool_id="products",
                    action=action,
                    params=dict(params or {}),
                    risk=self.normalize_risk(str(action_meta.get("risk") or "medium")),
                    idempotent=bool(action_meta.get("idempotent", False)),
                    description="Execute legacy products compat mutation through Agent runtime.",
                )
            ],
            risk_level=self.normalize_risk(str(action_meta.get("risk") or "medium")),
            metadata={"source": "product_compat_route", "route": route_path},
        )
        context: Payload = {
            "source": "product_compat_route",
            "route": route_path,
            "request_path": str(request.url.path),
            "user_id": user_id,
            "route_confirmed": True,
            "service_source": "fastapi_product_compat_route",
            "route_module": self.route_module,
        }
        orchestrator = self.create_runtime()
        run = orchestrator.start_run_from_plan(
            user_id=user_id,
            message=str(params.get("message") or f"Products compat {action}"),
            plan=plan,
            runtime_context=context,
        )
        if run.status in {"waiting_user", "running"}:
            continued = orchestrator.continue_run(
                run.run_id,
                approved_by=user_id or "products-compat-route",
                approved_step_id=node_id,
                runtime_context=context,
            )
            if continued is not None:
                run = continued
        return self.node_output(run, node_id)
