"""Excel 单据 ETL：通用识别 → 知识库记忆 → 预览/入库 → 模板回写。

默认不依赖仓库内置送货单 YAML；版式来自：
- 知识库 ``excel_etl_kb``（同义词 + 可学习表头指纹）
- 可选 ``FHD_EXCEL_ETL_PROFILE_DIR`` 用户 YAML
- 仅当 ``FHD_EXCEL_ETL_ALLOW_BUILTIN=1`` 时加载 examples/

闭环能力：
- preview / execute（指纹幂等）
- batch 目录扫描
- 通用表写出 / 流水写出，并从 notes 反推再出单
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from app.application.excel_etl_kb import (
    TemplateMemory,
    get_excel_etl_kb,
    sheet_layout_fingerprint,
)
from app.application.shipment_etl_profile import (
    ShipmentEtlProfile,
    column_rule_matches,
    get_shipment_etl_profile,
    header_groups_match,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


from app.application.shipment_excel_etl_app_service_part01 import (
    _classify_sheet_role as _classify_sheet_role,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _find_header_row as _find_header_row,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _find_ledger_header_row as _find_ledger_header_row,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _header_cell_texts as _header_cell_texts,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _infer_columns_from_samples as _infer_columns_from_samples,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _joined_row as _joined_row,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _kb_resolve_layout as _kb_resolve_layout,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _map_headers as _map_headers,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _norm_cell as _norm_cell,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _norm_header as _norm_header,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _parse_buyer_meta as _parse_buyer_meta,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _pick_best_profile_for_sheet as _pick_best_profile_for_sheet,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _profiles_for_parse as _profiles_for_parse,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _remember_sheet_layout as _remember_sheet_layout,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _resolve_profile as _resolve_profile,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _row_texts as _row_texts,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _sample_values as _sample_values,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _score_delivery_sheet as _score_delivery_sheet,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _score_ledger_sheet as _score_ledger_sheet,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _to_float as _to_float,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _to_int as _to_int,
)
from app.application.shipment_excel_etl_app_service_part01 import (
    _token_in_compact as _token_in_compact,
)

_CORP_SUFFIX_ONLY = frozenset(
    {
        "ltd",
        "ltd.",
        "limited",
        "inc",
        "inc.",
        "llc",
        "pte",
        "pte.",
        "co",
        "co.",
        "corp",
        "corp.",
        "gmbh",
        "公司",
        "有限公司",
        "股份有限公司",
    }
)


from app.application.shipment_excel_etl_app_service_part02 import (
    _apply_llm_assist_to_layout as _apply_llm_assist_to_layout,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _build_item_from_row as _build_item_from_row,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _build_sheet_probe as _build_sheet_probe,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _enrich_note as _enrich_note,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _excel_date_to_str as _excel_date_to_str,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _extract_adjacent_buyer_meta as _extract_adjacent_buyer_meta,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _fingerprint_store_path as _fingerprint_store_path,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _is_fingerprint_imported as _is_fingerprint_imported,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _legacy_json_has_fingerprint as _legacy_json_has_fingerprint,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _load_fingerprints as _load_fingerprints,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _looks_like_non_product_token as _looks_like_non_product_token,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _looks_like_titleish as _looks_like_titleish,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _merge_meta as _merge_meta,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _parse_delivery_sheet as _parse_delivery_sheet,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _parse_items as _parse_items,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _parse_ledger_sheet as _parse_ledger_sheet,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _record_fingerprint_now as _record_fingerprint_now,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _save_fingerprints as _save_fingerprints,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    _unit_name_looks_truncated as _unit_name_looks_truncated,
)
from app.application.shipment_excel_etl_app_service_part02 import (
    note_fingerprint as note_fingerprint,
)
from app.application.shipment_excel_etl_app_service_part03 import (
    _notes_to_product_records as _notes_to_product_records,
)
from app.application.shipment_excel_etl_app_service_part03 import (
    execute_shipment_excel_etl as execute_shipment_excel_etl,
)
from app.application.shipment_excel_etl_app_service_part03 import (
    parse_delivery_notes as parse_delivery_notes,
)
from app.application.shipment_excel_etl_app_service_part03 import (
    preview_shipment_excel_etl as preview_shipment_excel_etl,
)
from app.application.shipment_excel_etl_app_service_part04 import (
    ShipmentExcelEtlApplicationService as ShipmentExcelEtlApplicationService,
)
from app.application.shipment_excel_etl_app_service_part04 import (
    batch_execute_shipment_excel_etl as batch_execute_shipment_excel_etl,
)
from app.application.shipment_excel_etl_app_service_part04 import (
    batch_preview_shipment_excel_etl as batch_preview_shipment_excel_etl,
)
from app.application.shipment_excel_etl_app_service_part04 import (
    get_shipment_excel_etl_app_service as get_shipment_excel_etl_app_service,
)
from app.application.shipment_excel_etl_app_service_part04 import (
    regenerate_delivery_notes_from_file as regenerate_delivery_notes_from_file,
)
from app.application.shipment_excel_etl_app_service_part04 import (
    write_delivery_note_workbook as write_delivery_note_workbook,
)
from app.application.shipment_excel_etl_app_service_part04 import (
    write_ledger_workbook as write_ledger_workbook,
)

# ruff: noqa: F401

_BUYER_CELL_LABEL = re.compile(
    "^(?:to|bill\\s*to|sold\\s*to|ship\\s*to|consignee|customer|buyer|购货单位|客户名称|客户|采购单位|收货单位|收货方|买方)\\s*[:：]?$",
    re.IGNORECASE,
)

_BUYER_INLINE = re.compile(
    "(?is)(?:bill\\s*to|sold\\s*to|ship\\s*to|(?<![a-z])to|(?<![a-z])buyer|(?<![a-z])customer|购货单位|客户名称|客户|采购单位)\\s*[:：]\\s*([^\\n·|]+?)(?=\\s*(?:·|\\||Incoterms|Payment|Tel|Phone|地址|电话)|$)"
)

_ATTN_CELL_LABEL = re.compile("^(?:attn|attention|联系人)\\s*[:：]?$", re.IGNORECASE)

_ORDER_INLINE = re.compile(
    "(?is)^(?:do\\s*no|invoice\\s*no|buyer\\s*po|po\\s*ref|订单号|订单编号|单号)\\s*[:：]?\\s*([A-Za-z0-9\\-_/]+)"
)

_NON_PRODUCT_TOKENS = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "title",
        "identifier",
        "subject",
        "description",
        "notes",
        "creator",
        "accession",
        "my title",
        "another title",
        "the best image ever",
    }
)

_svc: ShipmentExcelEtlApplicationService | None = None
