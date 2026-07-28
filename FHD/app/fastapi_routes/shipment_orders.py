"""
出货单 / 订单 / 出货记录 —— 继承自归档 ``ai_assistant_compat`` + ``shipment`` 蓝图端点契约的 FastAPI 补全。

覆盖：

- ``/api/orders*``、``/orders/next_number``（AI 助手根路径）
- ``/api/shipment/generate|print|download/*`` 与 ``/api/shipment/orders*``（与归档 ``shipment`` 蓝图对齐）
- ``GET /api/shipment/list`` 统一注册
- ``/api/shipment/shipment-records/*``

历史：统一 FastAPI 入口后兼容层未挂载上述路径时，前端会出现大量 404。
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse

from app.application.facades.query_facade import query_service
from app.bootstrap import get_shipment_application_service_core
from app.db.models import ShipmentRecord
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["shipment-orders-compat"])


def _svc():
    return get_shipment_application_service_core()


def _authenticated_owner_user_id(request: Request) -> int | None:
    """Return only the middleware-authenticated owner identity.

    The old shipment compatibility endpoints accept a number of legacy body
    and header fields for tracing.  They are never an authority for a private
    ETL-derived document or a post-print state transition.  The middleware is
    the single source of the authenticated owner identity.
    """

    try:
        raw_value = getattr(request.state, "user_id", None)
        user_id = int(raw_value) if raw_value is not None else 0
    except (AttributeError, TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


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


def _next_order_number_payload(suffix: str = "A") -> dict[str, Any]:
    today = datetime.now()
    year = today.strftime("%y")
    month = today.strftime("%m")
    start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (start + timedelta(days=32)).replace(day=1)
    count = query_service.count(
        ShipmentRecord,
        created_at__gte=start,
        created_at__lt=next_month,
    )
    next_sequence = int(count) + 1
    order_number = f"{year}-{month}-{next_sequence:05d}{suffix}"
    return {
        "success": True,
        "data": {
            "order_number": order_number,
            "sequence": next_sequence,
            "year_month": f"{year}-{month}",
        },
    }


@router.get("/orders/next_number")
def orders_next_number_root(suffix: str = Query(default="A")):
    return _next_order_number_payload(suffix)


@router.get("/api/shipment/orders/next_number")
def orders_next_number_under_shipment(suffix: str = Query(default="A")):
    # 与归档 ``shipment.get_next_order_number`` 一致：后缀须为单个大写字母，否则回退 A
    suf = (suffix or "").strip().upper()
    if not (len(suf) == 1 and re.fullmatch(r"[A-Z]", suf)):
        suf = "A"
    return _next_order_number_payload(suf)


@router.get("/api/orders/next_number")
def orders_next_number_under_api(suffix: str = Query(default="A")):
    return _next_order_number_payload(suffix)


# ----- /api/shipment（归档 shipment 蓝图，与 /api/orders* 镜像）-----


@router.post("/api/shipment/generate-batch")
def shipment_generate_batch(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    """Preview a legacy batch; each document still needs an explicit click."""
    shipments = payload.get("shipments") or []
    if not isinstance(shipments, list) or not shipments:
        raise HTTPException(status_code=400, detail="shipments 不能为空")
    try:
        result = _shipment_batch_confirmation_preview(shipments)
        return JSONResponse(jsonable_encoder(result), status_code=200)
    except RECOVERABLE_ERRORS as e:
        logger.exception("shipment batch preview: %s", e)
        return JSONResponse(
            {
                "success": False,
                "error_code": "shipment_preview_failed",
                "message": "发货单预演失败",
            },
            status_code=500,
        )


@router.post("/api/shipment/generate")
def shipment_generate(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    unit_name = str(payload.get("unit_name") or "").strip()
    products = payload.get("products") or []
    date = payload.get("date")
    if not unit_name:
        raise HTTPException(status_code=400, detail="单位名称不能为空")
    if not products:
        raise HTTPException(status_code=400, detail="产品列表不能为空")
    if not isinstance(products, list) or not all(isinstance(product, dict) for product in products):
        raise HTTPException(status_code=400, detail="产品列表条目必须是对象")
    try:
        result = _shipment_confirmation_preview(
            unit_name=unit_name,
            products=products,
            payload={**payload, "date": date},
            compatibility_endpoint="/api/shipment/generate",
        )
        return JSONResponse(jsonable_encoder(result), status_code=200)
    except RECOVERABLE_ERRORS as e:
        logger.exception("shipment generate preview: %s", e)
        return JSONResponse(
            {
                "success": False,
                "error_code": "shipment_preview_failed",
                "message": "发货单预演失败",
            },
            status_code=500,
        )


@router.post("/api/shipment/print")
def shipment_print(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    """Mark a shipment printed only after a server-issued print receipt.

    This historical endpoint never submits a physical print job itself.  Its
    only remaining responsibility is the record-state transition after
    ``/api/print/document`` has successfully spent the owner-bound document
    capability.  A guessed local file path, legacy header, or JSON user id is
    not sufficient authority to mark a shipment as printed.
    """

    file_path = str(payload.get("file_path") or "").strip()
    order_id = payload.get("order_id")
    printer_name = payload.get("printer_name")
    post_print_receipt = payload.get("post_print_receipt")

    if not file_path:
        raise HTTPException(status_code=400, detail="文件路径不能为空")
    if not str(post_print_receipt or "").strip():
        return JSONResponse(
            {
                "success": False,
                "error_code": "PRINT_RECEIPT_REQUIRED",
                "message": "缺少打印回执，不能直接更新打印状态",
            },
            status_code=409,
        )

    try:
        normalized_order_id: int | None = None
        if order_id not in (None, ""):
            try:
                normalized_order_id = int(order_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="order_id 无效")
            if normalized_order_id <= 0:
                raise HTTPException(status_code=400, detail="order_id 无效")

        from app.application.print_authorization import consume_post_print_receipt

        receipt = consume_post_print_receipt(
            post_print_receipt,
            owner_user_id=_authenticated_owner_user_id(request),
            file_path=file_path,
            order_id=normalized_order_id,
        )
        if not receipt.get("success"):
            error_code = str(receipt.get("error_code") or "")
            status_code = 403 if error_code == "PRINT_RECEIPT_OWNER_MISMATCH" else 409
            return JSONResponse(receipt, status_code=status_code)

        # The receipt canonicalises the generated artifact path.  Use that
        # value rather than a client spelling/symlink variant in the audit
        # response.  No Agent auto-continue occurs on this route.
        confirmed_file_path = str(receipt.get("file_path") or file_path)
        receipt_order_id = receipt.get("order_id")
        if normalized_order_id is None:
            return JSONResponse(
                {
                    "success": True,
                    "message": "发货单已打印，但未更新记录（缺少 order_id）",
                    "printed_at": datetime.now().isoformat(),
                    "file_path": confirmed_file_path,
                    "updated": False,
                    "warning": "缺少 order_id，已跳过数据库状态更新",
                },
                status_code=200,
            )

        result = dict(
            _svc().mark_as_printed(
                normalized_order_id,
                printer_name=str(printer_name or ""),
            )
            or {}
        )
        result["file_path"] = confirmed_file_path
        result["order_id"] = receipt_order_id or normalized_order_id
        result.setdefault("updated", bool(result.get("success")))
        return JSONResponse(
            jsonable_encoder(result), status_code=200 if result.get("success") else 400
        )
    except HTTPException:
        raise
    except RECOVERABLE_ERRORS as e:
        logger.exception("shipment printed-state update: %s", e)
        return JSONResponse(
            {
                "success": False,
                "error_code": "shipment_print_state_update_failed",
                "message": "打印状态更新失败",
            },
            status_code=500,
        )


@router.get("/api/shipment/download/{filename:path}")
def shipment_download(filename: str):
    from app.utils.path_utils import get_app_data_dir

    output_dir = os.path.join(get_app_data_dir(), "shipment_outputs")
    safe = os.path.basename(filename) or filename
    file_path = os.path.join(output_dir, safe)
    if file_path and os.path.exists(file_path):
        return FileResponse(
            file_path,
            filename=safe,
            media_type="application/octet-stream",
        )
    return JSONResponse(
        {"success": False, "message": "文件不存在"},
        status_code=404,
    )


@router.get("/api/shipment/orders/purchase-units")
def shipment_orders_purchase_units():
    units = _svc().get_purchase_units()
    return {"success": True, "data": units, "count": len(units)}


@router.post("/api/shipment/orders/clear-shipment")
def shipment_orders_clear_shipment(
    request: Request, payload: dict[str, Any] = Body(default_factory=dict)
):
    purchase_unit = str(payload.get("purchase_unit") or "").strip()
    if not purchase_unit:
        raise HTTPException(status_code=400, detail="缺少购买单位参数")
    result = _run_shipment_orders_agent(
        request=request,
        action="clear_shipment",
        params={"purchase_unit": purchase_unit},
        route_path="/api/shipment/orders/clear-shipment",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/shipment/orders")
def shipment_orders_list(limit: int = Query(default=100, ge=1, le=5000)):
    orders_list = _svc().get_orders(limit=limit) or []
    inner = {"success": True, "data": orders_list, "count": len(orders_list)}
    return {"success": True, "data": inner, "count": len(inner)}


@router.get("/api/shipment/orders/search")
def shipment_orders_search(q: str = Query(default="")):
    qs = (q or "").strip()
    if not qs:
        return {"success": True, "data": [], "count": 0}
    rows = _svc().search_orders(qs)
    return {"success": True, "data": rows, "count": len(rows)}


@router.get("/api/shipment/orders/latest")
def shipment_orders_latest():
    orders = _svc().get_orders(limit=10) or []
    return {"success": True, "data": orders}


@router.post("/api/shipment/orders/set-sequence")
def shipment_orders_set_sequence(
    request: Request, payload: dict[str, Any] = Body(default_factory=dict)
):
    sequence = int(payload.get("sequence", 1))
    result = _run_shipment_orders_agent(
        request=request,
        action="set_sequence",
        params={"sequence": sequence},
        route_path="/api/shipment/orders/set-sequence",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.post("/api/shipment/orders/reset-sequence")
def shipment_orders_reset_sequence(request: Request):
    result = _run_shipment_orders_agent(
        request=request,
        action="reset_sequence",
        params={},
        route_path="/api/shipment/orders/reset-sequence",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.delete("/api/shipment/orders/clear-all")
def shipment_orders_clear_all(request: Request):
    result = _run_shipment_orders_agent(
        request=request,
        action="clear_all",
        params={},
        route_path="/api/shipment/orders/clear-all",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/shipment/orders/{order_number}")
def shipment_orders_get(order_number: str):
    order = _svc().get_order(str(order_number))
    if order:
        return {"success": True, "data": order}
    raise HTTPException(status_code=404, detail="订单不存在")


# ----- /api/orders（静态子路径必须早于 /api/orders/{order_number}）-----


@router.get("/api/orders")
def api_orders_list(limit: int = Query(default=100, ge=1, le=5000)):
    orders = _svc().get_orders(limit=limit) or []
    return {"success": True, "data": orders, "count": len(orders)}


@router.post("/api/orders", status_code=201)
def api_orders_create(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    """Create the shipment record shown by the desktop Orders page.

    ``/api/orders`` is the historical desktop name for shipment records.  Keep
    the public contract here so callers do not need to know the internal
    ``/api/shipment/shipment-records/record`` compatibility path.
    """
    purchase_unit = str(
        payload.get("purchase_unit")
        or payload.get("unit_name")
        or payload.get("customer_name")
        or ""
    ).strip()
    products = payload.get("products") or payload.get("items") or []
    if not purchase_unit:
        raise HTTPException(status_code=400, detail="缺少购买单位")
    if not isinstance(products, list) or not products:
        raise HTTPException(status_code=400, detail="产品列表不能为空")
    result = _run_shipment_records_agent(
        request=request,
        action="create",
        params={
            "unit_name": purchase_unit,
            "products": products,
            "contact_person": payload.get("contact_person"),
            "contact_phone": payload.get("contact_phone"),
        },
        route_path="/api/orders",
    )
    return JSONResponse(result, status_code=201 if result.get("success") else 400)


@router.delete("/api/orders")
@router.delete("/api/orders/", include_in_schema=False)
def api_orders_delete_root(request: Request):
    result = _run_shipment_orders_agent(
        request=request,
        action="clear_all",
        params={},
        route_path="/api/orders",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/orders/latest")
def api_orders_latest():
    orders = _svc().get_orders(limit=10) or []
    return {"success": True, "data": orders, "count": len(orders)}


@router.get("/api/orders/search")
def api_orders_search(q: str = Query(default="")):
    qs = (q or "").strip()
    rows = _svc().search_orders(qs) if qs else []
    return {"success": True, "data": rows, "count": len(rows)}


@router.post("/api/orders/set-sequence")
def api_orders_set_sequence(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
    sequence = int(payload.get("sequence", 1))
    result = _run_shipment_orders_agent(
        request=request,
        action="set_sequence",
        params={"sequence": sequence},
        route_path="/api/orders/set-sequence",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.post("/api/orders/reset-sequence")
def api_orders_reset_sequence(request: Request):
    result = _run_shipment_orders_agent(
        request=request,
        action="reset_sequence",
        params={},
        route_path="/api/orders/reset-sequence",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/orders/purchase-units")
def api_orders_purchase_units():
    units = _svc().get_purchase_units()
    return {"success": True, "data": units, "count": len(units)}


@router.post("/api/orders/clear-shipment")
def api_orders_clear_shipment(
    request: Request, payload: dict[str, Any] = Body(default_factory=dict)
):
    purchase_unit = str(payload.get("purchase_unit") or "").strip()
    if not purchase_unit:
        raise HTTPException(status_code=400, detail="缺少购买单位参数")
    result = _run_shipment_orders_agent(
        request=request,
        action="clear_shipment",
        params={"purchase_unit": purchase_unit},
        route_path="/api/orders/clear-shipment",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.get("/api/orders/export")
def api_orders_export(
    unit: str | None = Query(default=None),
    purchase_unit: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    """Export the current Orders page data as a real XLSX workbook."""
    selected_unit = (unit or purchase_unit or "").strip() or None
    result = _svc().export_shipment_records(
        unit_name=selected_unit,
        template_id=template_id,
        status_filter=status,
    )
    file_path = _safe_shipment_export_path(result)
    if result.get("success") and file_path:
        return FileResponse(
            file_path,
            filename=os.path.basename(file_path),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return JSONResponse(result, status_code=400 if not result.get("success") else 500)


@router.delete("/api/orders/clear-all")
def api_orders_clear_all(request: Request):
    result = _run_shipment_orders_agent(
        request=request,
        action="clear_all",
        params={},
        route_path="/api/orders/clear-all",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)


@router.patch("/api/orders/{order_number}")
def api_orders_update(
    request: Request,
    order_number: str,
    payload: dict[str, Any] = Body(default_factory=dict),
):
    try:
        record_id = int(order_number)
    except ValueError:
        raise HTTPException(status_code=404, detail="订单不存在")

    requested_status = payload.get("status")
    if requested_status is not None and str(requested_status) not in {
        "pending",
        "printed",
        "completed",
        "cancelled",
    }:
        raise HTTPException(status_code=400, detail="无效的订单状态")

    update_params = {
        "id": record_id,
        "unit_name": payload.get("purchase_unit") or payload.get("unit_name"),
        "product_name": payload.get("product_name"),
        "model_number": payload.get("model_number"),
        "quantity_kg": payload.get("quantity_kg"),
        "quantity_tins": payload.get("quantity_tins"),
        "tin_spec": payload.get("tin_spec"),
        "unit_price": payload.get("unit_price"),
        "amount": payload.get("amount"),
        "status": requested_status,
    }
    result = _run_shipment_records_agent(
        request=request,
        action="update",
        params={key: value for key, value in update_params.items() if value is not None},
        route_path="/api/orders/{order_number}",
    )
    if not result.get("success"):
        return JSONResponse(result, status_code=404)
    result["data"] = _svc().get_order(str(record_id))
    return JSONResponse(jsonable_encoder(result), status_code=200)


@router.get("/api/orders/{order_number}")
def api_orders_get(order_number: str):
    try:
        int(order_number)
    except ValueError:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = _svc().get_order(str(order_number))
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {"success": True, "data": order}


@router.delete("/api/shipment/orders/{order_number}")
def shipment_orders_delete(request: Request, order_number: str):
    try:
        shipment_id = int(order_number)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的订单编号格式：{order_number}")
    result = _run_shipment_orders_agent(
        request=request,
        action="delete",
        params={"id": shipment_id, "order_number": order_number},
        route_path="/api/shipment/orders/{order_number}",
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "删除失败"))
    result["message"] = f"订单 {order_number} 已删除"
    return result


# ----- /api/shipment/shipment-records -----


@router.get("/api/shipment/records")
def shipment_records_dashboard_alias(
    unit: str | None = Query(default=None),
    unit_name: str | None = Query(default=None),
    per_page: int = Query(default=100, ge=1, le=500),
    sort: str | None = Query(default=None),
):
    """企业客服等页面使用的短路径；与 shipment-records/records 同源，支持 per_page。"""
    _ = sort  # 预留与前端 sort=created_at_desc 对齐；列表默认按 created_at 倒序
    u = (unit or unit_name or "").strip() or None
    records = _svc().get_shipment_records(u, limit=per_page)
    return {"success": True, "data": records}


@router.get("/api/shipment/shipment-records/records")
@router.get("/api/shipment/shipment-records/records/", include_in_schema=False)
def shipment_records_list(
    unit: str | None = Query(default=None),
    unit_name: str | None = Query(default=None),
):
    try:
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

        mod_out = try_invoke_erp_domain_handler(
            "shipment",
            "records_list",
            unit=unit,
            unit_name=unit_name,
        )
        if mod_out is not None:
            return mod_out
    except RECOVERABLE_ERRORS:
        logger.debug("erp domain shipment.records_list dispatch skipped", exc_info=True)
    u = (unit or unit_name or "").strip() or None
    records = _svc().get_shipment_records(u)
    return {"success": True, "data": records}


@router.post("/api/shipment/shipment-records/record")
def shipment_records_create(request: Request, payload: dict[str, Any] = Body(...)):
    """新建出货记录（从出货记录管理页手动建单）。"""
    unit_name = str(payload.get("unit_name") or payload.get("purchase_unit") or "").strip()
    if not unit_name:
        raise HTTPException(status_code=400, detail="缺少购买单位")
    products = payload.get("products") or []
    if not isinstance(products, list):
        products = []
    result = _run_shipment_records_agent(
        request=request,
        action="create",
        params={
            "unit_name": unit_name,
            "products": products,
            "contact_person": payload.get("contact_person"),
            "contact_phone": payload.get("contact_phone"),
        },
        route_path="/api/shipment/shipment-records/record",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.patch("/api/shipment/shipment-records/record")
def shipment_records_patch(request: Request, payload: dict[str, Any] = Body(...)):
    record_id = payload.get("id")
    if not record_id:
        raise HTTPException(status_code=400, detail="缺少记录 ID")
    result = _run_shipment_records_agent(
        request=request,
        action="update",
        params={
            "id": int(record_id),
            "unit_name": payload.get("unit_name"),
            "products": payload.get("products"),
            "date": payload.get("date"),
            **{
                k: v for k, v in payload.items() if k not in ("id", "unit_name", "products", "date")
            },
        },
        route_path="/api/shipment/shipment-records/record",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 404)


@router.delete("/api/shipment/shipment-records/record")
def shipment_records_delete(request: Request, payload: dict[str, Any] = Body(...)):
    record_id = payload.get("id")
    if not record_id:
        raise HTTPException(status_code=400, detail="缺少记录 ID")
    result = _run_shipment_records_agent(
        request=request,
        action="delete",
        params={"id": int(record_id)},
        route_path="/api/shipment/shipment-records/record",
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 404)


@router.get("/api/shipment/shipment-records/export")
def shipment_records_export(
    unit: str | None = Query(default=None),
    unit_name: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    u = (unit or unit_name or "").strip() or None
    result = _svc().export_shipment_records(
        unit_name=u,
        template_id=template_id,
        status_filter=status,
    )
    fp = _safe_shipment_export_path(result)
    if result.get("success") and fp:
        return FileResponse(
            fp,
            filename=os.path.basename(fp),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return JSONResponse(result, status_code=200 if result.get("success") else 500)
