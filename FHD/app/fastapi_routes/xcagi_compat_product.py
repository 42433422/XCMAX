"""
XCAGI 前端兼容 API — 产品 / 库存 / 报价表导出路由。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.application.workflow.types import normalize_workflow_risk
from app.fastapi_routes.xcagi_compat_product_actions import (
    execute_product_action,
    price_list_word_response,
)
from app.infrastructure.auth.db_token import verify_db_read_token_header
from app.infrastructure.persistence.compat_db.base import (
    _business_mod_json_block,
    _product_parse_id,
    _product_parse_is_active,
    _product_parse_quantity,
    _products_write_raise,
)
from app.infrastructure.persistence.compat_db.product_queries import (
    _load_products_all_for_export,
    _load_products_list_impl_pg,
)
from app.infrastructure.persistence.compat_db.queries import (
    _merged_purchase_unit_entries,
    _products_units_for_select,
)
from app.infrastructure.persistence.compat_db.writes import (
    products_pg_batch_delete_rows,
    products_pg_delete_row,
    products_pg_insert_row,
    products_pg_update_row,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(tags=["xcagi-compat"])
logger = logging.getLogger(__name__)


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
    if not output.get("success") and getattr(run, "error", False) and not output.get("message"):
        output["message"] = getattr(run, "error", False)
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _products_compat_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "products-compat-route"
    ).strip()


def _products_compat_status_code(result: dict[str, Any]) -> int:
    if result.get("success"):
        return 200
    status_code = result.get("status_code")
    if status_code is None:
        parsed = 0
    else:
        try:
            parsed = int(status_code)
        except RECOVERABLE_ERRORS:
            parsed = 0
    if 400 <= parsed < 600:
        return parsed
    if str(result.get("error_code") or "") in {"tool_exception", "http_exception"}:
        return 500
    return 200


def _normalize_products_create_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    name = str(
        data.get("name")
        or data.get("product_name")
        or data.get("name_or_model")
        or data.get("model_number")
        or data.get("product_code")
        or ""
    ).strip()
    if name:
        data.setdefault("name", name)
        data.setdefault("product_name", name)
        data.setdefault("name_or_model", name)
    data.setdefault("unit_name", data.get("unit") or "个")
    return data


def _products_compat_via_service_enabled() -> bool:
    try:
        from app.mod_sdk.erp_products_facade import is_erp_products_via_service_enabled

        return bool(is_erp_products_via_service_enabled())
    except RECOVERABLE_ERRORS:
        logger.debug("products compat service flag check skipped", exc_info=True)
        return False


def _products_compat_preflight(
    request: Request, action: str, payload: dict[str, Any]
) -> dict | None:
    if _products_compat_via_service_enabled():
        return None
    _products_write_raise(request)
    gate = _business_mod_json_block()
    if gate:
        return cast("dict[Any, Any]", gate)
    if action in {"update", "delete"}:
        pid = _product_parse_id(payload.get("id"))
        if pid is None:
            raise HTTPException(status_code=400, detail="id 无效或缺失")
        payload["id"] = pid
    if action == "batch_delete":
        ids = payload.get("ids") or payload.get("product_ids") or []
        if not isinstance(ids, list) or not ids:
            raise HTTPException(status_code=400, detail="ids 须为非空数组")
        payload["ids"] = ids
    return None


def _http_exception_result(exc: HTTPException) -> dict[str, Any]:
    return {
        "success": False,
        "message": str(exc.detail),
        "status_code": int(exc.status_code),
        "error_code": "http_exception",
    }


def _execute_products_compat_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    data = _normalize_products_create_payload(params) if action == "create" else dict(params or {})
    return execute_product_action(
        action,
        data,
        parse_id=_product_parse_id,
        parse_quantity=_product_parse_quantity,
        parse_is_active=_product_parse_is_active,
        insert_row=products_pg_insert_row,
        update_row=products_pg_update_row,
        delete_row=products_pg_delete_row,
        batch_delete_rows=products_pg_batch_delete_rows,
        http_exception_result=_http_exception_result,
        recoverable_errors=RECOVERABLE_ERRORS,
        logger=logger,
    )


def _run_products_compat_agent(
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
    action_meta = dict((registry.get("products") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 products 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"products_{action}_compat"
    user_id = _products_compat_agent_user_id(request, params)
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
                risk=normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
                idempotent=bool(action_meta.get("idempotent", False)),
                description="Execute legacy products compat mutation through Agent runtime.",
            )
        ],
        risk_level=normalize_workflow_risk(str(action_meta.get("risk") or "medium")),
        metadata={"source": "product_compat_route", "route": route_path},
    )
    runtime_context = {
        "source": "product_compat_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_product_compat_route",
        "route_module": __name__,
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Products compat {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "products-compat-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


def _products_price_list_word_response(
    unit: str | None,
    keyword: str | None,
    export_date: str | None,
    template_slug: str | None = None,
) -> Response:
    return price_list_word_response(
        unit,
        keyword,
        export_date,
        template_slug,
        load_products=_load_products_all_for_export,
        recoverable_errors=RECOVERABLE_ERRORS,
        logger=logger,
    )


@router.get("/products/units")
def products_units(request: Request) -> dict:
    verify_db_read_token_header(request)
    return cast("dict[Any, Any]", _products_units_for_select())


@router.get("/shipment/shipment-records/units")
@router.get("/shipment/shipment-records/units/")
def shipment_records_units() -> dict:
    return cast("dict[Any, Any]", _products_units_for_select())


@router.get("/mod/taiyangniao-pro/shipment/shipment-records/units")
@router.get("/mod/taiyangniao-pro/shipment/shipment-records/units/")
def taiyangniao_shipment_records_units_host_alias() -> dict:
    """Stable host alias for desktop clients with independently updated private Mods."""
    from app.application.attendance_reference_data import attendance_unit_names

    units = attendance_unit_names(_products_units_for_select())
    return {"success": True, "data": units, "units": units, "source": "host_compat"}


@router.get("/purchase_units")
@router.get("/purchase_units/")
def purchase_units_list() -> dict:
    return {"success": True, "data": _merged_purchase_unit_entries()}


@router.get("/products/list")
def products_list(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=2000),
    keyword: str | None = Query(None),
    unit: str | None = Query(None),
) -> dict:
    try:
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

        mod_out = try_invoke_erp_domain_handler(
            "products",
            "list",
            request=request,
            page=page,
            per_page=per_page,
            keyword=keyword,
            unit=unit,
        )
        if mod_out is not None:
            return cast("dict[Any, Any]", mod_out)
    except RECOVERABLE_ERRORS:
        logger.debug("erp domain products.list dispatch skipped", exc_info=True)
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import products_list as products_list_via_service

        if is_erp_products_via_service_enabled():
            return cast(
                "dict[Any, Any]",
                products_list_via_service(
                    request, page=page, per_page=per_page, keyword=keyword, unit=unit
                ),
            )
    except RECOVERABLE_ERRORS:
        logger.debug("products list via service skipped", exc_info=True)
    verify_db_read_token_header(request)
    try:
        items, total, schema_hint = _load_products_list_impl_pg(page, per_page, keyword, unit)
        out: dict = {"success": True, "data": items, "total": total}
        if schema_hint:
            out["schema_hint"] = schema_hint
        return out
    except RECOVERABLE_ERRORS:
        logger.exception("products list failed (postgresql)")
        return {"success": False, "message": "产品服务暂时不可用", "data": [], "total": 0}


@router.get("/products/{product_id:int}", response_model=None)
@router.get("/products/{product_id:int}/", response_model=None)
def products_get_by_id(request: Request, product_id: int) -> dict | JSONResponse:
    try:
        from app.mod_sdk.erp_products_facade import (
            is_erp_products_via_service_enabled,
        )
        from app.mod_sdk.erp_products_facade import products_get as products_get_via_service

        if is_erp_products_via_service_enabled():
            return products_get_via_service(request, product_id)
    except RECOVERABLE_ERRORS:
        logger.debug("products get via service skipped", exc_info=True)
    verify_db_read_token_header(request)
    from app.bootstrap import get_products_service

    result = get_products_service().get_product(product_id)
    if result.get("success"):
        return result
    return JSONResponse(result, status_code=404)


@router.post("/products/resolve-name-hints")
@router.post("/products/resolve-name-hints/")
def products_resolve_name_hints(request: Request, body: dict = Body(default_factory=dict)) -> dict:
    verify_db_read_token_header(request)
    raw = body.get("hints") or body.get("names") or []
    if not isinstance(raw, list):
        return {"success": False, "message": "hints 须为字符串数组", "data": []}
    hints = [str(x).strip() for x in raw if str(x).strip()]
    if not hints:
        return {"success": False, "message": "hints 不能为空", "data": []}

    gate = _business_mod_json_block()
    if gate:
        return {**gate, "data": []}

    raise HTTPException(
        status_code=501,
        detail=(
            "products/resolve-name-hints 未启用：product_name_resolve 模块已在清理过程中被移除，"
            "请使用销售合同流程中的 name_hint 解析能力。"
        ),
    )


@router.post("/products/update", response_model=None)
@router.post("/products/update/", response_model=None)
def products_update(request: Request, body: dict = Body(default_factory=dict)) -> dict | Response:
    payload = dict(body or {})
    gate = _products_compat_preflight(request, "update", payload)
    if gate:
        return gate
    result = _run_products_compat_agent(
        request=request,
        action="update",
        params=payload,
        route_path="/products/update",
    )
    return JSONResponse(result, status_code=_products_compat_status_code(result))


@router.post("/products/add", response_model=None)
@router.post("/products/add/", response_model=None)
def products_add(request: Request, body: dict = Body(default_factory=dict)) -> dict | Response:
    payload = _normalize_products_create_payload(dict(body or {}))
    gate = _products_compat_preflight(request, "create", payload)
    if gate:
        return gate
    result = _run_products_compat_agent(
        request=request,
        action="create",
        params=payload,
        route_path="/products/add",
    )
    return JSONResponse(result, status_code=_products_compat_status_code(result))


@router.post("/products/delete", response_model=None)
@router.post("/products/delete/", response_model=None)
def products_delete(request: Request, body: dict = Body(default_factory=dict)) -> dict | Response:
    payload = dict(body or {})
    gate = _products_compat_preflight(request, "delete", payload)
    if gate:
        return gate
    result = _run_products_compat_agent(
        request=request,
        action="delete",
        params=payload,
        route_path="/products/delete",
    )
    return JSONResponse(result, status_code=_products_compat_status_code(result))


@router.post("/products/batch-delete", response_model=None)
@router.post("/products/batch-delete/", response_model=None)
def products_batch_delete(
    request: Request, body: dict = Body(default_factory=dict)
) -> dict | Response:
    payload = dict(body or {})
    gate = _products_compat_preflight(request, "batch_delete", payload)
    if gate:
        return gate
    result = _run_products_compat_agent(
        request=request,
        action="batch_delete",
        params=payload,
        route_path="/products/batch-delete",
    )
    return JSONResponse(result, status_code=_products_compat_status_code(result))


@router.get("/products/price-list-export")
@router.get("/products/price-list-export/")
def products_price_list_export(
    request: Request,
    unit: str | None = Query(None),
    keyword: str | None = Query(None),
    export_date: str | None = Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
    template_id: str | None = Query(
        None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
    ),
) -> Response:
    verify_db_read_token_header(request)
    return _products_price_list_word_response(unit, keyword, export_date, template_id)


@router.get("/products/export.docx")
@router.get("/products/export.docx/")
def products_export_docx(
    request: Request,
    unit: str | None = Query(None),
    keyword: str | None = Query(None),
    export_date: str | None = Query(None, description="报价日期 YYYY-MM-DD，默认当天"),
    template_id: str | None = Query(
        None, description="模板 slug（GET /api/document-templates?role=price_list_docx）"
    ),
) -> Response:
    verify_db_read_token_header(request)
    return _products_price_list_word_response(unit, keyword, export_date, template_id)


@router.get("/products/price-list-template-preview")
@router.get("/products/price-list-template-preview/")
def products_price_list_template_preview(
    request: Request,
    template_id: str | None = Query(None, description="模板 slug（与 price-list-export 一致）"),
) -> dict:
    from app.infrastructure.documents.price_list_export import (
        build_price_list_template_preview_json,
    )

    verify_db_read_token_header(request)
    from app.shell.mod_business_scope import business_data_exposed, business_data_hidden_reason

    if not business_data_exposed():
        raise HTTPException(
            status_code=503,
            detail=business_data_hidden_reason() or "扩展 Mod 未就绪。",
        )
    return cast("dict[Any, Any]", build_price_list_template_preview_json(template_id))
