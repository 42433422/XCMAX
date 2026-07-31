"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def _shipment_preview_order_text(
    *, unit_name: str, products: list[dict[str, Any]], payload: dict[str, Any]
) -> str:
    """Keep a deterministic source string for legacy structured requests.

    ``shipment_generate`` execution receives the structured ``products`` too,
    so this text is intentionally only a transparent fallback rather than a
    second parser authority.  Prefer the caller's original order text when it
    exists; otherwise make a minimal readable representation for the
    confirmation card and the later explicit execution click.
    """

    original = str(payload.get("order_text") or "").strip()
    if original:
        return original

    parts: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        name = str(
            product.get("name")
            or product.get("product_name")
            or product.get("model_number")
            or product.get("model")
            or "产品"
        ).strip()
        quantity = product.get("quantity_tins") or product.get("quantity") or product.get("qty")
        specification = product.get("tin_spec") or product.get("spec") or product.get("规格")
        fragment = name
        if quantity not in (None, ""):
            fragment += f" {quantity}桶"
        if specification not in (None, ""):
            fragment += f" 规格{specification}"
        parts.append(fragment)
    return f"{unit_name}，{'；'.join(parts)}" if parts else unit_name


def _shipment_confirmation_preview(
    *,
    unit_name: str,
    products: list[dict[str, Any]],
    payload: dict[str, Any],
    compatibility_endpoint: str,
) -> dict[str, Any]:
    """Return the shared card used by chat before shipment generation.

    This route used to mark a high-risk Agent node as confirmed and continue
    it immediately.  Compatibility clients now receive the same declarative
    task as chat: only its explicit button sends the payload to
    ``/api/tools/execute``.  In particular, do not include an owner id from a
    JSON body/header; that endpoint injects the authenticated owner itself.
    """

    from app.application.ai_chat_helpers import build_shipment_preview_response_dict

    order_text = _shipment_preview_order_text(
        unit_name=unit_name,
        products=products,
        payload=payload,
    )
    preview = build_shipment_preview_response_dict(unit_name, products, order_text)
    params = preview["task"]["payload"]["params"]

    # Layout preferences describe a user choice, not access rights.  Preserve
    # them across the preview while deliberately excluding user/owner fields.
    for key, value in {
        "template_name": payload.get("template_name") or payload.get("template"),
        "template_id": payload.get("template_id"),
        "preferred_template": payload.get("preferred_template") or payload.get("template"),
        "date": payload.get("date"),
        "order_number": payload.get("order_number"),
    }.items():
        if value is not None and str(value).strip():
            params[key] = value

    preview["confirmation_required"] = True
    preview["data"] = {
        **(preview.get("data") or {}),
        "compatibility_endpoint": compatibility_endpoint,
        "execution_endpoint": "/api/tools/execute",
    }
    return preview


def _shipment_batch_confirmation_preview(
    shipments: list[Any],
) -> dict[str, Any]:
    """Build one explicit confirmation task per valid legacy batch item.

    A batch must not turn into one hidden write after a broad confirmation.
    Each child remains the ordinary ``shipment_generate`` task whose explicit
    click goes through the owner-bound tools endpoint.  Invalid items are
    returned as preview issues and never invoke the shipment service.
    """

    tasks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, shipment in enumerate(shipments):
        if not isinstance(shipment, dict):
            errors.append(
                {
                    "index": index,
                    "error_code": "invalid_shipment_item",
                    "message": "条目必须是对象",
                }
            )
            continue
        unit_name = str(shipment.get("unit_name") or shipment.get("customer_name") or "").strip()
        products = shipment.get("products") or shipment.get("items") or []
        if not unit_name:
            errors.append(
                {
                    "index": index,
                    "error_code": "shipment_unit_required",
                    "message": "单位名称不能为空",
                }
            )
            continue
        if not isinstance(products, list) or not products:
            errors.append(
                {
                    "index": index,
                    "error_code": "shipment_products_required",
                    "message": "产品列表不能为空",
                }
            )
            continue
        if not all(isinstance(product, dict) for product in products):
            errors.append(
                {
                    "index": index,
                    "error_code": "shipment_product_invalid",
                    "message": "产品列表条目必须是对象",
                }
            )
            continue
        preview = _shipment_confirmation_preview(
            unit_name=unit_name,
            products=products,
            payload=shipment,
            compatibility_endpoint="/api/shipment/generate-batch",
        )
        task = dict(preview["task"])
        task["title"] = f"发货单预览 {index + 1}"
        task["batch_index"] = index
        tasks.append(task)

    count = len(tasks)
    all_valid = not errors
    return {
        "success": bool(tasks),
        "confirmation_required": True,
        "message": (
            f"已生成 {count} 条发货单预演，请逐条确认执行"
            if all_valid
            else f"已生成 {count} 条可确认预演，另有 {len(errors)} 条需要修正"
        ),
        "response": "批量发货单尚未生成，请逐条点击“确认执行”。",
        # Keep a singular ``task`` for old renderers when there is exactly one
        # item.  Multiple tasks intentionally have no batch execution URL.
        "task": tasks[0] if count == 1 else None,
        "tasks": tasks,
        "data": {
            "routing": "legacy_shipment_batch_preview",
            "compatibility_endpoint": "/api/shipment/generate-batch",
            "execution_endpoint": "/api/tools/execute",
            "total": len(shipments),
            "preview_count": count,
            "errors": errors,
        },
    }


def _safe_shipment_export_path(result: dict[str, Any]) -> str | None:
    from pathlib import Path

    from app.infrastructure.workspace import resolve_existing_file_under_root
    from app.utils.path_utils import get_data_dir

    filename = os.path.basename(str(result.get("filename") or ""))
    if not re.fullmatch(r"shipment_records_[^/\\]{1,160}_\d{8}_\d{6}\.xlsx", filename):
        return None
    try:
        candidate = resolve_existing_file_under_root(
            Path(get_data_dir()).resolve() / "exports", filename
        )
    except (OSError, ValueError):
        return None
    return str(candidate)


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
    if not output.get("success"):
        output["message"] = "出货单操作失败"
        output.pop("error", None)
        output.pop("traceback", None)
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _shipment_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "shipment-route"
    ).strip()


def _run_shipment_records_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("shipment_records") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 shipment_records 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"shipment_records_{action}"
    user_id = _shipment_agent_user_id(request, params)
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 shipment_records.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="shipment_records",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute shipment_records.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "shipment_records_route", "route": route_path},
    )
    runtime_context = {
        "source": "shipment_records_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_shipment_records_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Shipment records {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "shipment-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


def _run_shipment_orders_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("shipment_orders") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 shipment_orders 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"shipment_orders_{action}"
    user_id = _shipment_agent_user_id(request, params)
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 shipment_orders.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="shipment_orders",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "high"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute shipment_orders.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "high"),
        metadata={"source": "shipment_orders_route", "route": route_path},
    )
    runtime_context = {
        "source": "shipment_orders_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_shipment_orders_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Shipment orders {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "shipment-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


sync_module_functions(
    target=globals(),
    source_module="app.fastapi_routes.shipment_orders",
    function_names=(
        "_shipment_preview_order_text",
        "_shipment_confirmation_preview",
        "_shipment_batch_confirmation_preview",
        "_safe_shipment_export_path",
        "_agent_node_output",
        "_shipment_agent_user_id",
        "_run_shipment_records_agent",
        "_run_shipment_orders_agent",
    ),
)
