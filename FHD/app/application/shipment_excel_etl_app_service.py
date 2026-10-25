"""Excel 单据 ETL 公共 API：显式组合识别、入库、补偿和回写服务。

版式由知识库、用户 YAML 或显式启用的内置模板提供。每次调用绑定当前
适配器，保留公开函数及测试注入点；领域组件不回引本模块或共享 globals。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.application.excel_etl_kb import get_excel_etl_kb
from app.application.shipment_etl import (
    batching,
    catalog,
    fingerprints,
    metadata,
    workbook,
    writing,
)
from app.application.shipment_etl.assistance import (
    _apply_llm_assist_to_layout as _apply_llm_assist_to_layout,
)
from app.application.shipment_etl.assistance import _build_sheet_probe as _build_sheet_probe
from app.application.shipment_etl.fingerprints import FingerprintPorts
from app.application.shipment_etl.fingerprints import (
    _fingerprint_store_path as _fingerprint_store_path,
)
from app.application.shipment_etl.fingerprints import (
    _record_fingerprint_now as _record_fingerprint_now,
)
from app.application.shipment_etl.importing import ImportCoordinator, ImportPorts
from app.application.shipment_etl.layout import _classify_sheet_role as _classify_sheet_role
from app.application.shipment_etl.layout import _find_header_row as _find_header_row
from app.application.shipment_etl.layout import _find_ledger_header_row as _find_ledger_header_row
from app.application.shipment_etl.layout import _header_cell_texts as _header_cell_texts
from app.application.shipment_etl.layout import (
    _infer_columns_from_samples as _infer_columns_from_samples,
)
from app.application.shipment_etl.layout import _joined_row as _joined_row
from app.application.shipment_etl.layout import _map_headers as _map_headers
from app.application.shipment_etl.layout import _norm_cell as _norm_cell
from app.application.shipment_etl.layout import _norm_header as _norm_header
from app.application.shipment_etl.layout import (
    _pick_best_profile_for_sheet as _pick_best_profile_for_sheet,
)
from app.application.shipment_etl.layout import _row_texts as _row_texts
from app.application.shipment_etl.layout import _sample_values as _sample_values
from app.application.shipment_etl.layout import _score_delivery_sheet as _score_delivery_sheet
from app.application.shipment_etl.layout import _score_ledger_sheet as _score_ledger_sheet
from app.application.shipment_etl.layout import _to_float as _to_float
from app.application.shipment_etl.layout import _to_int as _to_int
from app.application.shipment_etl.layout import _token_in_compact as _token_in_compact
from app.application.shipment_etl.metadata import (
    _extract_adjacent_buyer_meta as _extract_adjacent_buyer_meta,
)
from app.application.shipment_etl.metadata import _merge_meta as _merge_meta
from app.application.shipment_etl.metadata import (
    _unit_name_looks_truncated as _unit_name_looks_truncated,
)
from app.application.shipment_etl.notes import _build_item_from_row as _build_item_from_row
from app.application.shipment_etl.notes import _enrich_note as _enrich_note
from app.application.shipment_etl.notes import _excel_date_to_str as _excel_date_to_str
from app.application.shipment_etl.notes import (
    _looks_like_non_product_token as _looks_like_non_product_token,
)
from app.application.shipment_etl.notes import _looks_like_titleish as _looks_like_titleish
from app.application.shipment_etl.notes import (
    _notes_to_product_records as _notes_to_product_records,
)
from app.application.shipment_etl.notes import _parse_items as _parse_items
from app.application.shipment_etl.notes import note_fingerprint as note_fingerprint
from app.application.shipment_etl.persistence import ShipmentWriter
from app.application.shipment_etl.sheets import SheetParser, SheetParserPorts
from app.application.shipment_etl.workbook import WorkbookPorts, WorkbookReader
from app.application.shipment_etl_profile import ShipmentEtlProfile, get_shipment_etl_profile

logger = logging.getLogger(__name__)


def _sheet_parser() -> SheetParser:
    return SheetParser(
        SheetParserPorts(
            resolve_memory=_kb_resolve_layout,
            remember=_remember_sheet_layout,
            buyer_metadata=_parse_buyer_meta,
            assist=_apply_llm_assist_to_layout,
        )
    )


def _workbook_reader() -> WorkbookReader:
    return WorkbookReader(
        WorkbookPorts(
            profiles=_profiles_for_parse,
            choose_profile=_pick_best_profile_for_sheet,
            classify=_classify_sheet_role,
            delivery=_parse_delivery_sheet,
            ledger=_parse_ledger_sheet,
        ),
        logger,
    )


def _import_product_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    from app.domain.shared_services.tools_workflow_registered import _execute_excel_import_records

    return _execute_excel_import_records(records)


def _shipment_service() -> ShipmentWriter:
    from app.bootstrap import get_shipment_app_service

    return get_shipment_app_service()


def _import_coordinator() -> ImportCoordinator:
    from app.application.shipment_excel_etl_fingerprint_store import delete_fingerprint

    return ImportCoordinator(
        ImportPorts(
            _resolve_profile, parse_delivery_notes, _import_product_records, _shipment_service
        ),
        FingerprintPorts(_is_fingerprint_imported, _record_fingerprint_now, delete_fingerprint),
        logger,
    )


def _resolve_profile(
    profile: ShipmentEtlProfile | None = None, profile_id: str | None = None
) -> ShipmentEtlProfile:
    return catalog._resolve_profile(profile, profile_id, load_profile=get_shipment_etl_profile)


def _profiles_for_parse(
    profile: ShipmentEtlProfile | None = None, profile_id: str | None = None
) -> list[ShipmentEtlProfile]:
    return catalog._profiles_for_parse(profile, profile_id, load_profile=get_shipment_etl_profile)


def _kb_resolve_layout(ws) -> tuple[int | None, dict[str, int], str]:
    return catalog._kb_resolve_layout(ws, get_kb=get_excel_etl_kb)


def _remember_sheet_layout(
    ws,
    *,
    header_row: int,
    mapping: dict[str, int],
    profile: ShipmentEtlProfile,
    source: str = "learned",
) -> str:
    return catalog._remember_sheet_layout(
        ws,
        header_row=header_row,
        mapping=mapping,
        profile=profile,
        source=source,
        get_kb=get_excel_etl_kb,
        logger=logger,
    )


def _parse_buyer_meta(ws, header_row: int, profile: ShipmentEtlProfile) -> dict[str, str]:
    return metadata._parse_buyer_meta(
        ws, header_row, profile, adjacent_buyer=_extract_adjacent_buyer_meta
    )


def _legacy_json_has_fingerprint(fingerprint: str) -> bool:
    return fingerprints._legacy_json_has_fingerprint(
        fingerprint, path_provider=_fingerprint_store_path
    )


def _is_fingerprint_imported(tenant_key: str, fingerprint: str) -> bool:
    return fingerprints._is_fingerprint_imported(
        tenant_key, fingerprint, legacy_lookup=_legacy_json_has_fingerprint
    )


def _load_fingerprints() -> dict[str, Any]:
    return fingerprints._load_fingerprints(path_provider=_fingerprint_store_path, logger=logger)


def _save_fingerprints(data: dict[str, Any]) -> None:
    return fingerprints._save_fingerprints(data, path_provider=_fingerprint_store_path)


def _parse_delivery_sheet(
    ws, *, fallback_unit: str, profile: ShipmentEtlProfile, allow_llm: bool = True
) -> dict[str, Any] | None:
    return _sheet_parser().delivery(
        ws, fallback_unit=fallback_unit, profile=profile, allow_llm=allow_llm
    )


def _parse_ledger_sheet(
    ws, *, fallback_unit: str, profile: ShipmentEtlProfile, allow_llm: bool = True
) -> list[dict[str, Any]]:
    return _sheet_parser().ledger(
        ws, fallback_unit=fallback_unit, profile=profile, allow_llm=allow_llm
    )


def parse_delivery_notes(
    file_path: str | Path,
    *,
    min_score: int | None = None,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
    allow_ocr: bool = True,
) -> dict[str, Any]:
    return _workbook_reader().parse(
        file_path,
        min_score=min_score,
        include_ledger=include_ledger,
        unit_name_hint=unit_name_hint,
        profile_id=profile_id,
        profile=profile,
        allow_ocr=allow_ocr,
    )


def preview_shipment_excel_etl(
    file_path: str | Path,
    *,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
    workspace_root: str | Path | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
) -> dict[str, Any]:
    return workbook.preview(
        file_path,
        include_ledger=include_ledger,
        unit_name_hint=unit_name_hint,
        workspace_root=workspace_root,
        profile_id=profile_id,
        profile=profile,
        parse_notes=parse_delivery_notes,
        contains=_is_fingerprint_imported,
    )


def execute_shipment_excel_etl(
    file_path: str | Path,
    *,
    import_products: bool = True,
    import_shipments: bool = True,
    notes: list[dict[str, Any]] | None = None,
    idempotent: bool = True,
    include_ledger: bool | str = False,
    confirm_ledger: bool = False,
    dry_run: bool = False,
    compensate_on_failure: bool = True,
    unit_name_hint: str | None = None,
    workspace_root: str | Path | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
    direct: bool = False,
    force_shipment_target: bool = False,
) -> dict[str, Any]:
    return _import_coordinator().execute(
        file_path,
        import_products=import_products,
        import_shipments=import_shipments,
        notes=notes,
        idempotent=idempotent,
        include_ledger=include_ledger,
        confirm_ledger=confirm_ledger,
        dry_run=dry_run,
        compensate_on_failure=compensate_on_failure,
        unit_name_hint=unit_name_hint,
        workspace_root=workspace_root,
        profile_id=profile_id,
        profile=profile,
        direct=direct,
        force_shipment_target=force_shipment_target,
    )


def write_delivery_note_workbook(
    notes: list[dict[str, Any]],
    output_path: str | Path,
    *,
    seller_title: str | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
) -> dict[str, Any]:
    return writing.write_delivery(
        notes,
        output_path,
        seller_title=seller_title,
        profile_id=profile_id,
        profile=profile,
        resolve_profile=_resolve_profile,
    )


def write_ledger_workbook(
    rows: list[dict[str, Any]],
    output_path: str | Path,
    *,
    sheet_name: str | None = None,
    unit_name: str | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
) -> dict[str, Any]:
    return writing.write_ledger(
        rows,
        output_path,
        sheet_name=sheet_name,
        unit_name=unit_name,
        profile_id=profile_id,
        profile=profile,
        resolve_profile=_resolve_profile,
    )


def regenerate_delivery_notes_from_file(
    file_path: str | Path,
    output_path: str | Path,
    *,
    include_ledger: bool | str = "auto",
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
) -> dict[str, Any]:
    return writing.regenerate(
        file_path,
        output_path,
        include_ledger=include_ledger,
        profile_id=profile_id,
        profile=profile,
        resolve_profile=_resolve_profile,
        parse_notes=parse_delivery_notes,
        write_notes=write_delivery_note_workbook,
    )


def batch_preview_shipment_excel_etl(
    directory: str | Path,
    *,
    include_ledger: bool | str = "auto",
    pattern: str = "*.xlsx",
    workspace_root: str | Path | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
) -> dict[str, Any]:
    return batching.preview_directory(
        directory,
        include_ledger=include_ledger,
        pattern=pattern,
        workspace_root=workspace_root,
        profile_id=profile_id,
        profile=profile,
        resolve_profile=_resolve_profile,
        preview_file=preview_shipment_excel_etl,
    )


def batch_execute_shipment_excel_etl(
    directory: str | Path,
    *,
    include_ledger: bool | str = False,
    pattern: str = "*.xlsx",
    idempotent: bool = True,
    import_products: bool = True,
    import_shipments: bool = True,
    confirm_ledger: bool = False,
    dry_run: bool = False,
    workspace_root: str | Path | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
) -> dict[str, Any]:
    return batching.execute_directory(
        directory,
        include_ledger=include_ledger,
        pattern=pattern,
        idempotent=idempotent,
        import_products=import_products,
        import_shipments=import_shipments,
        confirm_ledger=confirm_ledger,
        dry_run=dry_run,
        workspace_root=workspace_root,
        profile_id=profile_id,
        profile=profile,
        resolve_profile=_resolve_profile,
        execute_file=execute_shipment_excel_etl,
    )


class ShipmentExcelEtlApplicationService:
    def __init__(self, profile_id: str | None = None) -> None:
        self._profile_id = profile_id

    def _profile_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if "profile" in kwargs or "profile_id" in kwargs:
            return kwargs
        if self._profile_id:
            return {**kwargs, "profile_id": self._profile_id}
        return kwargs

    def preview(self, file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        return preview_shipment_excel_etl(file_path, **self._profile_kwargs(kwargs))

    def execute(self, file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        return execute_shipment_excel_etl(file_path, **self._profile_kwargs(kwargs))

    def batch_preview(self, directory: str | Path, **kwargs: Any) -> dict[str, Any]:
        return batch_preview_shipment_excel_etl(directory, **self._profile_kwargs(kwargs))

    def batch_execute(self, directory: str | Path, **kwargs: Any) -> dict[str, Any]:
        return batch_execute_shipment_excel_etl(directory, **self._profile_kwargs(kwargs))

    def write_delivery_template(
        self,
        notes: list[dict[str, Any]],
        output_path: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return write_delivery_note_workbook(notes, output_path, **self._profile_kwargs(kwargs))

    def write_ledger_template(
        self,
        rows: list[dict[str, Any]],
        output_path: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return write_ledger_workbook(rows, output_path, **self._profile_kwargs(kwargs))

    def regenerate(
        self,
        file_path: str | Path,
        output_path: str | Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return regenerate_delivery_notes_from_file(
            file_path, output_path, **self._profile_kwargs(kwargs)
        )

    def ocr_preview(self, file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        from app.application.shipment_excel_etl_ocr import parse_ocr_document

        return parse_ocr_document(file_path, **self._profile_kwargs(kwargs))


_svc: ShipmentExcelEtlApplicationService | None = None


def get_shipment_excel_etl_app_service() -> ShipmentExcelEtlApplicationService:
    global _svc
    if _svc is None:
        _svc = ShipmentExcelEtlApplicationService()
    return _svc
