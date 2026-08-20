# ruff: noqa: E402, F401
"""Workflow tool registry, dispatcher, and Excel/import handlers."""

from __future__ import annotations

import importlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd

logger = logging.getLogger(__name__)

from app.application.tools.registered_capabilities import (
    ERP_CAPABILITY_TOOL_NAME,
    execute_registered_capability,
    extend_workflow_tool_registry,
)
from app.application.tools.workflow_business_db import (
    business_db_tool_specs,
    try_execute_business_db_tool,
)
from app.infrastructure.auth.db_token import configured_db_write_token  # noqa: F401
from app.infrastructure.excel.schema_service import ExcelSchemaUnderstandingService
from app.infrastructure.excel.text_to_pandas import _safe_exec_pandas
from app.utils.operational_errors import RECOVERABLE_ERRORS

_workflow_tool_registry_cache: list[dict[str, Any]] | None = None
_workflow_tool_registry_bulk_token_present: bool | None = None
_workflow_registry_cache_ver: int | None = None
# 递增以使进程内工具注册表缓存失效（新增工具时 bump）
# 2026-07-21: bump 2→3 新增订单/客户/报表/RBAC 工具集
_WORKFLOW_REG_VER = 3


from app.application.tools.safe_dataframe_query import safe_filter_dataframe
from app.application.tools.workflow_excel_paths import (
    _parse_excel_header_row_1based,
    resolve_safe_excel_path,
)
from app.application.tools.workflow_part01 import (
    _base_registry as _base_registry,
)
from app.application.tools.workflow_part01 import (
    _read_excel_dataframe as _read_excel_dataframe,
)
from app.application.tools.workflow_part01 import (
    execute_workflow_tool as execute_workflow_tool,
)
from app.application.tools.workflow_part01 import (
    get_workflow_tool_registry as get_workflow_tool_registry,
)
from app.application.tools.workflow_part01 import (
    handle_excel_analysis as handle_excel_analysis,
)
from app.application.tools.workflow_part01 import (
    invalidate_workflow_tool_registry as invalidate_workflow_tool_registry,
)
from app.application.tools.workflow_part01 import (
    run_natural_language_pandas as run_natural_language_pandas,
)

# 新增工具名 → 执行器函数 懒映射。缓存以避免每次 dispatch 都重新 import。
_NEW_TOOL_DISPATCH_CACHE: dict[str, Any] | None = None


from app.application.tools.workflow_part02 import (
    _excel_cell_as_clean_str as _excel_cell_as_clean_str,
)
from app.application.tools.workflow_part02 import (
    _excel_cell_as_float as _excel_cell_as_float,
)
from app.application.tools.workflow_part02 import (
    _handle_import_excel_to_database as _handle_import_excel_to_database,
)
from app.application.tools.workflow_part02 import (
    _infer_product_field_mapping as _infer_product_field_mapping,
)
from app.application.tools.workflow_part02 import (
    _resolve_new_tool_dispatch as _resolve_new_tool_dispatch,
)

# 报价单 / 合同表尾常见语句（命中则不作为产品行导入）
_CLAUSE_SUBSTRINGS = (
    "含税价",
    "含税",
    "月结",
    "数期",
    "担保",
    "付款责任",
    "保质保量",
    "验收签名",
    "所送货物",
    "若贵司",
    "未能按时付款",
    "配套使用",
    "我厂产品",
    "所示比例施工",
    "供应方签名",
    "供应方",
    "采购方",
    "盖章",
    "出资人",
    "签名及盖章",
    "以上价格为",
    "以上各种产品",
    "请严格按",
    "请配套",
)


from app.application.tools.workflow_part03 import (
    _import_customers_preview_or_execute as _import_customers_preview_or_execute,
)
from app.application.tools.workflow_part03 import (
    _import_orders_preview_or_execute as _import_orders_preview_or_execute,
)
from app.application.tools.workflow_part03 import (
    _import_products_preview_or_execute as _import_products_preview_or_execute,
)
from app.application.tools.workflow_part03 import (
    _looks_like_contract_or_footer_line as _looks_like_contract_or_footer_line,
)

__all__ = [
    "resolve_safe_excel_path",
    "run_natural_language_pandas",
    "handle_excel_analysis",
    "get_workflow_tool_registry",
    "execute_workflow_tool",
]
