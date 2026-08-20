"""普通版聊天槽位路由，供统一聊天、工作流和 normal_slot_dispatch 复用。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from app.application.chat_tool_intent import looks_like_explicit_workflow_tool_intent
from app.application.product_query_context import is_full_product_list_phrase
from app.utils.ai_helpers import format_money, safe_float
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SALES_WRITE_SELL_MARKERS = ("卖给", "销售给", "出售给")


from app.application.normal_chat_dispatch_part01 import (
    _as_closed_loop_number as _as_closed_loop_number,
)
from app.application.normal_chat_dispatch_part01 import (
    _decimal_prefix as _decimal_prefix,
)
from app.application.normal_chat_dispatch_part01 import (
    _first_marker as _first_marker,
)
from app.application.normal_chat_dispatch_part01 import (
    _is_sales_closed_loop_write as _is_sales_closed_loop_write,
)
from app.application.normal_chat_dispatch_part01 import (
    _parse_sales_write_request as _parse_sales_write_request,
)
from app.application.normal_chat_dispatch_part01 import (
    _request_tenant_id as _request_tenant_id,
)
from app.application.normal_chat_dispatch_part01 import (
    _sales_write_idempotency_key as _sales_write_idempotency_key,
)
from app.application.normal_chat_dispatch_part01 import (
    build_customers_query_response_dict as build_customers_query_response_dict,
)
from app.application.normal_chat_dispatch_part01 import (
    build_product_query_response_dict as build_product_query_response_dict,
)
from app.application.normal_chat_dispatch_part01 import (
    resolve_tool_execution_profile as resolve_tool_execution_profile,
)
from app.application.normal_chat_dispatch_part01 import (
    route_normal_mode_message as route_normal_mode_message,
)
from app.application.normal_chat_dispatch_part01 import (
    run_normal_slot_product_query_from_message as run_normal_slot_product_query_from_message,
)
from app.application.normal_chat_dispatch_part01 import (
    run_normal_slot_shipment_preview as run_normal_slot_shipment_preview,
)
from app.application.normal_chat_dispatch_part01 import (
    run_workflow_products_query_normal_profile as run_workflow_products_query_normal_profile,
)
from app.application.normal_chat_dispatch_part01 import (
    try_normal_slot_read_payload as try_normal_slot_read_payload,
)
from app.application.normal_chat_dispatch_part02 import (
    build_aging_report_response_dict as build_aging_report_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_finance_query_response_dict as build_finance_query_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_inventory_alert_response_dict as build_inventory_alert_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_inventory_count_response_dict as build_inventory_count_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_knowledge_query_response_dict as build_knowledge_query_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_label_print_response_dict as build_label_print_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_materials_query_response_dict as build_materials_query_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_mrp_production_response_dict as build_mrp_production_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_purchase_query_response_dict as build_purchase_query_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_replenishment_suggest_response_dict as build_replenishment_suggest_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_reports_query_response_dict as build_reports_query_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_sales_query_response_dict as build_sales_query_response_dict,
)
from app.application.normal_chat_dispatch_part02 import (
    build_shipment_records_query_response_dict as build_shipment_records_query_response_dict,
)
# ruff: noqa: F401
