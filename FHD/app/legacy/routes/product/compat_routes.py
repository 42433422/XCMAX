# ruff: noqa: F401
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


from app.legacy.routes.product.compat_routes_part01 import (
    _agent_node_output as _agent_node_output,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _execute_products_compat_action as _execute_products_compat_action,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _http_exception_result as _http_exception_result,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _normalize_products_create_payload as _normalize_products_create_payload,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _products_compat_agent_user_id as _products_compat_agent_user_id,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _products_compat_preflight as _products_compat_preflight,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _products_compat_status_code as _products_compat_status_code,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _products_compat_via_service_enabled as _products_compat_via_service_enabled,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _products_price_list_word_response as _products_price_list_word_response,
)
from app.legacy.routes.product.compat_routes_part01 import (
    _run_products_compat_agent as _run_products_compat_agent,
)
from app.legacy.routes.product.compat_routes_part01 import (
    products_get_by_id as products_get_by_id,
)
from app.legacy.routes.product.compat_routes_part01 import (
    products_list as products_list,
)
from app.legacy.routes.product.compat_routes_part01 import (
    products_resolve_name_hints as products_resolve_name_hints,
)
from app.legacy.routes.product.compat_routes_part01 import (
    products_units as products_units,
)
from app.legacy.routes.product.compat_routes_part01 import (
    purchase_units_list as purchase_units_list,
)
from app.legacy.routes.product.compat_routes_part01 import (
    shipment_records_units as shipment_records_units,
)
from app.legacy.routes.product.compat_routes_part01 import (
    taiyangniao_shipment_records_units_host_alias as taiyangniao_shipment_records_units_host_alias,
)
from app.legacy.routes.product.compat_routes_part02 import (
    products_add as products_add,
)
from app.legacy.routes.product.compat_routes_part02 import (
    products_batch_delete as products_batch_delete,
)
from app.legacy.routes.product.compat_routes_part02 import (
    products_delete as products_delete,
)
from app.legacy.routes.product.compat_routes_part02 import (
    products_export_docx as products_export_docx,
)
from app.legacy.routes.product.compat_routes_part02 import (
    products_price_list_export as products_price_list_export,
)
from app.legacy.routes.product.compat_routes_part02 import (
    products_price_list_template_preview as products_price_list_template_preview,
)
from app.legacy.routes.product.compat_routes_part02 import (
    products_update as products_update,
)
