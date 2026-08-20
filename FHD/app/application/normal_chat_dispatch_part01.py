# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.normal_chat_dispatch")


from app.application.normal_chat_dispatch_part01_part01 import (
    _as_closed_loop_number as _as_closed_loop_number,
)
from app.application.normal_chat_dispatch_part01_part01 import (
    _decimal_prefix as _decimal_prefix,
)
from app.application.normal_chat_dispatch_part01_part01 import (
    _first_marker as _first_marker,
)
from app.application.normal_chat_dispatch_part01_part01 import (
    _is_sales_closed_loop_write as _is_sales_closed_loop_write,
)
from app.application.normal_chat_dispatch_part01_part01 import (
    _parse_sales_write_request as _parse_sales_write_request,
)
from app.application.normal_chat_dispatch_part01_part01 import (
    _sales_write_idempotency_key as _sales_write_idempotency_key,
)
from app.application.normal_chat_dispatch_part01_part01 import (
    route_normal_mode_message as route_normal_mode_message,
)
from app.application.normal_chat_dispatch_part01_part02 import (
    _request_tenant_id as _request_tenant_id,
)
from app.application.normal_chat_dispatch_part01_part02 import (
    build_product_query_response_dict as build_product_query_response_dict,
)
from app.application.normal_chat_dispatch_part01_part02 import (
    resolve_tool_execution_profile as resolve_tool_execution_profile,
)
from app.application.normal_chat_dispatch_part01_part02 import (
    run_normal_slot_product_query_from_message as run_normal_slot_product_query_from_message,
)
from app.application.normal_chat_dispatch_part01_part02 import (
    run_normal_slot_shipment_preview as run_normal_slot_shipment_preview,
)
from app.application.normal_chat_dispatch_part01_part02 import (
    run_workflow_products_query_normal_profile as run_workflow_products_query_normal_profile,
)
from app.application.normal_chat_dispatch_part01_part02 import (
    try_normal_slot_read_payload as try_normal_slot_read_payload,
)
from app.application.normal_chat_dispatch_part01_part03 import (
    build_customers_query_response_dict as build_customers_query_response_dict,
)
