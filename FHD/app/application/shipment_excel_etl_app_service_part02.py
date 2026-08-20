# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.shipment_excel_etl_app_service")


from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _build_item_from_row as _build_item_from_row,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _build_sheet_probe as _build_sheet_probe,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _enrich_note as _enrich_note,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _extract_adjacent_buyer_meta as _extract_adjacent_buyer_meta,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _fingerprint_store_path as _fingerprint_store_path,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _is_fingerprint_imported as _is_fingerprint_imported,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _legacy_json_has_fingerprint as _legacy_json_has_fingerprint,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _load_fingerprints as _load_fingerprints,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _looks_like_non_product_token as _looks_like_non_product_token,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _looks_like_titleish as _looks_like_titleish,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _merge_meta as _merge_meta,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _parse_items as _parse_items,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _record_fingerprint_now as _record_fingerprint_now,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _save_fingerprints as _save_fingerprints,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    _unit_name_looks_truncated as _unit_name_looks_truncated,
)
from app.application.shipment_excel_etl_app_service_part02_part01 import (
    note_fingerprint as note_fingerprint,
)
from app.application.shipment_excel_etl_app_service_part02_part02 import (
    _apply_llm_assist_to_layout as _apply_llm_assist_to_layout,
)
from app.application.shipment_excel_etl_app_service_part02_part02 import (
    _excel_date_to_str as _excel_date_to_str,
)
from app.application.shipment_excel_etl_app_service_part02_part02 import (
    _parse_delivery_sheet as _parse_delivery_sheet,
)
from app.application.shipment_excel_etl_app_service_part02_part02 import (
    _parse_ledger_sheet as _parse_ledger_sheet,
)
