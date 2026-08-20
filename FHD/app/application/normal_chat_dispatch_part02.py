# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.normal_chat_dispatch")


from app.application.normal_chat_dispatch_part02_part01 import (
    build_aging_report_response_dict as build_aging_report_response_dict,
)
from app.application.normal_chat_dispatch_part02_part01 import (
    build_inventory_alert_response_dict as build_inventory_alert_response_dict,
)
from app.application.normal_chat_dispatch_part02_part01 import (
    build_inventory_count_response_dict as build_inventory_count_response_dict,
)
from app.application.normal_chat_dispatch_part02_part01 import (
    build_label_print_response_dict as build_label_print_response_dict,
)
from app.application.normal_chat_dispatch_part02_part01 import (
    build_materials_query_response_dict as build_materials_query_response_dict,
)
from app.application.normal_chat_dispatch_part02_part01 import (
    build_mrp_production_response_dict as build_mrp_production_response_dict,
)
from app.application.normal_chat_dispatch_part02_part01 import (
    build_purchase_query_response_dict as build_purchase_query_response_dict,
)
from app.application.normal_chat_dispatch_part02_part01 import (
    build_shipment_records_query_response_dict as build_shipment_records_query_response_dict,
)
from app.application.normal_chat_dispatch_part02_part02 import (
    build_finance_query_response_dict as build_finance_query_response_dict,
)
from app.application.normal_chat_dispatch_part02_part02 import (
    build_knowledge_query_response_dict as build_knowledge_query_response_dict,
)
from app.application.normal_chat_dispatch_part02_part02 import (
    build_replenishment_suggest_response_dict as build_replenishment_suggest_response_dict,
)
from app.application.normal_chat_dispatch_part02_part02 import (
    build_reports_query_response_dict as build_reports_query_response_dict,
)
from app.application.normal_chat_dispatch_part02_part02 import (
    build_sales_query_response_dict as build_sales_query_response_dict,
)
