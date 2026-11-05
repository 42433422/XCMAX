"""Execute governed dataset actions through the existing Agent runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.knowledge.protocols import AgentRuntime, RecallMerger
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, normalize_workflow_risk
from app.fastapi_routes.knowledge.serialization import _public_dataset_payload


def _agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", False) and (not output.get("message")):
        output["message"] = getattr(run, "error", False)
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return cast("dict[str, Any]", _public_dataset_payload(output))


def _dataset_agent_user_id(request: Request, params: dict[str, Any]) -> str:
    access_context = (
        params.get("access_context") if isinstance(params.get("access_context"), dict) else {}
    )
    if not isinstance(access_context, dict):
        access_context = {}
    return str(access_context.get("actor_id") or "dataset-rag-route").strip()


class DatasetAgent:
    """Only the runtime, principal projection and result adapters are dependencies."""

    def __init__(
        self,
        *,
        runtime: Callable[[], AgentRuntime],
        registry: Callable[[], dict[str, Any]],
        access_payload: Callable[[Request], dict[str, Any]],
        actor: Callable[[Request, dict[str, Any]], str],
        output: Callable[[Any, str], dict[str, Any]],
        recall: RecallMerger,
    ) -> None:
        self._runtime = runtime
        self._registry = registry
        self._access_payload = access_payload
        self._actor = actor
        self._output = output
        self._recall = recall

    def run(
        self, *, request: Request, action: str, params: dict[str, Any], route_path: str
    ) -> JSONResponse:
        data = dict(params or {})
        access_payload = self._access_payload(request)
        if access_payload:
            data["access_context"] = access_payload
            if access_payload.get("tenant_id"):
                if not str(data.get("tenant_id") or "").strip():
                    data["tenant_id"] = access_payload["tenant_id"]
        registry = self._registry()
        action_meta = dict((registry.get("dataset_rag") or {}).get("actions") or {}).get(action)
        if not isinstance(action_meta, dict):
            return JSONResponse(
                {"success": False, "message": f"未注册的 Dataset/RAG 动作: {action}"},
                status_code=400,
            )
        node_id = f"dataset_rag_{action}"
        plan = PlanGraph(
            plan_id=node_id,
            intent=node_id,
            todo_steps=[f"通过 AgentOrchestrator 执行 dataset_rag.{action}"],
            nodes=[
                WorkflowNode(
                    node_id=node_id,
                    tool_id="dataset_rag",
                    action=action,
                    params=data,
                    risk=normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
                    idempotent=bool(action_meta.get("idempotent", False)),
                    description=f"Execute dataset_rag.{action} through the unified Agent runtime.",
                )
            ],
            risk_level=normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
            metadata={"source": "dataset_rag_route", "route": route_path},
        )
        user_id = self._actor(request, data)
        runtime_context = {
            "source": "dataset_rag_route",
            "route": route_path,
            "request_path": str(request.url.path),
            "user_id": user_id,
            "route_confirmed": True,
        }
        if access_payload:
            runtime_context["dataset_access_context"] = access_payload
            if access_payload.get("tenant_id"):
                runtime_context["dataset_tenant_id"] = access_payload["tenant_id"]
            runtime_context["dataset_permissions"] = list(access_payload.get("permissions") or [])
            runtime_context["dataset_admin"] = bool(access_payload.get("is_admin"))
        orchestrator = self._runtime()
        run = orchestrator.start_run_from_plan(
            user_id=user_id,
            message=str(data.get("message") or f"Dataset/RAG {action}"),
            plan=plan,
            runtime_context=runtime_context,
        )
        if run.status in {"waiting_user", "running"}:
            continued = orchestrator.continue_run(
                run.run_id,
                approved_by=user_id or "dataset-rag-route",
                approved_step_id=node_id,
                runtime_context=runtime_context,
            )
            if continued is not None:
                run = continued
        payload = self._output(run, node_id)
        if action == "query":
            payload = self._recall(payload, request=request, params=data)
        if run.status in {"waiting_user", "blocked"}:
            status_code = 202
        elif payload.get("error_code") == "dataset_permission_denied":
            status_code = 403
        elif payload.get("error_code") == "tool_exception":
            status_code = 500
        else:
            status_code = 200
        return JSONResponse(payload, status_code=status_code)
