"""
XCAGI 前端兼容 API — 产品 / 库存 / 报价表导出路由。
"""

from __future__ import annotations

import logging
from typing import Any
from typing import cast as cast

from fastapi import APIRouter, Depends, Request
from fastapi import Body as Body
from fastapi import HTTPException as HTTPException
from fastapi import Query as Query
from fastapi.responses import JSONResponse, Response

from app.application.workflow.workflow_types import normalize_workflow_risk
from app.fastapi_routes.xcagi_compat_product_actions import (
    execute_product_action,
    price_list_word_response,
)
from app.infrastructure.auth.business_scope_gate import require_scoped_business_permission
from app.infrastructure.auth.db_token import verify_db_read_token_header
from app.infrastructure.persistence.compat_db.compat_db_base import (
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
    _shipment_units_for_select,
)
from app.infrastructure.persistence.compat_db.writes import (
    products_pg_batch_delete_rows,
    products_pg_delete_row,
    products_pg_insert_row,
    products_pg_update_row,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .agent_execution import ProductAgentExecution
from .agent_execution import _agent_node_output as _agent_node_output
from .agent_execution import _products_compat_agent_user_id as _products_compat_agent_user_id
from .export_flow import ProductExports
from .export_routes import ProductExportRoutes
from .mutation_flow import ProductMutations, mutation_preflight, response_status, service_enabled
from .mutation_flow import _http_exception_result as _http_exception_result
from .mutation_flow import _normalize_products_create_payload as _normalize_products_create_payload
from .mutation_routes import ProductMutationRoutes
from .port_contracts import (
    create_product_agent,
    load_business_visibility,
    load_price_preview,
    load_product_dispatcher,
    load_product_lookup,
    load_product_registry,
    load_product_service_facade,
)
from .query_flow import ProductQueries
from .query_routes import ProductQueryRoutes

router = APIRouter(
    tags=["xcagi-compat"],
    dependencies=[Depends(require_scoped_business_permission("product.view", "product.edit"))],
)
logger = logging.getLogger(__name__)


def _queries() -> ProductQueries:
    return ProductQueries(
        verify_read=verify_db_read_token_header,
        legacy_list=_load_products_list_impl_pg,
        business_block=_business_mod_json_block,
        dispatcher_factory=load_product_dispatcher,
        service_factory=load_product_service_facade,
        lookup_factory=load_product_lookup,
        recoverable_errors=RECOVERABLE_ERRORS,
        logger=logger,
    )


def _mutations() -> ProductMutations:
    return ProductMutations(
        normalize_create=_normalize_products_create_payload,
        preflight=_products_compat_preflight,
        run_agent=_run_products_compat_agent,
        status_code=_products_compat_status_code,
        response=lambda payload, status: JSONResponse(payload, status_code=status),
    )


def _exports() -> ProductExports:
    return ProductExports(
        verify_read=verify_db_read_token_header,
        word_response=_products_price_list_word_response,
        visibility_factory=load_business_visibility,
        preview_factory=load_price_preview,
    )


def _products_compat_status_code(result: dict[str, Any]) -> int:
    return response_status(result, RECOVERABLE_ERRORS)


def _products_compat_via_service_enabled() -> bool:
    return service_enabled(load_product_service_facade, RECOVERABLE_ERRORS, logger)


def _products_compat_preflight(
    request: Request, action: str, payload: dict[str, Any]
) -> dict | None:
    return mutation_preflight(
        request,
        action,
        payload,
        via_service=_products_compat_via_service_enabled,
        verify_write=_products_write_raise,
        business_block=_business_mod_json_block,
        parse_id=_product_parse_id,
    )


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
    *, request: Request, action: str, params: dict[str, Any], route_path: str
) -> dict[str, Any]:
    return ProductAgentExecution(
        registry=load_product_registry,
        create_runtime=create_product_agent,
        identify_user=_products_compat_agent_user_id,
        node_output=_agent_node_output,
        normalize_risk=normalize_workflow_risk,
        route_module=__name__,
    ).run(request=request, action=action, params=params, route_path=route_path)


def _products_price_list_word_response(
    unit: str | None, keyword: str | None, export_date: str | None, template_slug: str | None = None
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


# Route owners receive late-bound service factories; legacy import paths remain public.

_query_routes = ProductQueryRoutes(
    queries=lambda: _queries(),
    verify_read=lambda request: verify_db_read_token_header(request),
    product_units=lambda: _products_units_for_select(),
    shipment_units=lambda: _shipment_units_for_select(),
    purchase_units=lambda: _merged_purchase_unit_entries(),
)
_mutation_routes = ProductMutationRoutes(mutations=lambda: _mutations())
_export_routes = ProductExportRoutes(exports=lambda: _exports())

router.include_router(_query_routes.router)
router.include_router(_mutation_routes.router)
router.include_router(_export_routes.router)

products_units = _query_routes.products_units
shipment_records_units = _query_routes.shipment_records_units
taiyangniao_shipment_records_units_host_alias = (
    _query_routes.taiyangniao_shipment_records_units_host_alias
)
purchase_units_list = _query_routes.purchase_units_list
products_list = _query_routes.products_list
products_get_by_id = _query_routes.products_get_by_id
products_resolve_name_hints = _query_routes.products_resolve_name_hints
products_update = _mutation_routes.products_update
products_add = _mutation_routes.products_add
products_delete = _mutation_routes.products_delete
products_batch_delete = _mutation_routes.products_batch_delete
products_price_list_export = _export_routes.products_price_list_export
products_export_docx = _export_routes.products_export_docx
products_price_list_template_preview = _export_routes.products_price_list_template_preview
