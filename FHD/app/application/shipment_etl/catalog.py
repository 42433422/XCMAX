"""Profile selection and learned layout memory through explicit loaders."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.application.excel_etl_kb import (
    ExcelEtlKnowledgeBase,
    TemplateMemory,
    sheet_layout_fingerprint,
)
from app.application.shipment_etl_profile import (
    ShipmentEtlProfile,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .layout import _header_cell_texts


def _resolve_profile(
    profile: ShipmentEtlProfile | None = None,
    profile_id: str | None = None,
    *,
    load_profile: Callable[[str | None], ShipmentEtlProfile],
) -> ShipmentEtlProfile:
    if profile is not None:
        return profile
    return load_profile(profile_id)


def _profiles_for_parse(
    profile: ShipmentEtlProfile | None = None,
    profile_id: str | None = None,
    *,
    load_profile: Callable[[str | None], ShipmentEtlProfile],
) -> list[ShipmentEtlProfile]:
    """解析用 profile 列表：显式指定则单 profile；否则加载全部做竞分。"""
    if profile is not None:
        return [profile]
    raw = str(profile_id or "").strip()
    if not raw:
        import os

        raw = (
            str(os.environ.get("FHD_EXCEL_ETL_PROFILE") or "").strip()
            or str(os.environ.get("FHD_SHIPMENT_ETL_PROFILE") or "").strip()
        )
    if raw and raw.lower() not in {"auto", "*"}:
        return [load_profile(raw)]
    from app.application.shipment_etl_profile import load_all_profiles

    profiles = load_all_profiles()
    return profiles or [load_profile("universal")]


def _kb_resolve_layout(
    ws, *, get_kb: Callable[[], ExcelEtlKnowledgeBase]
) -> tuple[int | None, dict[str, int], str]:
    """按表头指纹查知识库；命中则返回 (header_row, columns, fingerprint)。"""
    kb = get_kb()
    max_row = int(ws.max_row or 0)
    max_col = min(16, int(ws.max_column or 0) or 16)
    for row in range(1, min(20, max_row) + 1):
        headers = _header_cell_texts(ws, row, max_col=max_col)
        if len(headers) < 2:
            continue
        fp = sheet_layout_fingerprint(sheet_title=str(ws.title or ""), header_cells=headers)
        mem = kb.get_template(fp)
        if mem is None or not mem.columns:
            continue
        if "product_name" not in mem.columns and "model_number" not in mem.columns:
            continue
        kb.touch(fp)
        return (row, {str(k): int(v) for (k, v) in mem.columns.items()}, fp)
    return (None, {}, "")


def _remember_sheet_layout(
    ws,
    *,
    header_row: int,
    mapping: dict[str, int],
    profile: ShipmentEtlProfile,
    source: str = "learned",
    get_kb: Callable[[], ExcelEtlKnowledgeBase],
    logger: logging.Logger,
) -> str:
    """解析成功后把表头映射写入知识库。"""
    if not mapping or header_row is None:
        return ""
    headers = _header_cell_texts(ws, header_row)
    if len(headers) < 2:
        return ""
    fp = sheet_layout_fingerprint(sheet_title=str(ws.title or ""), header_cells=headers)
    try:
        get_kb().remember(
            TemplateMemory(
                fingerprint=fp,
                label=str(profile.label or profile.id),
                target=str(profile.target or "preview_only"),
                header_row=int(header_row),
                columns={str(k): int(v) for (k, v) in mapping.items()},
                meta={},
                write=dict(profile.write or {}),
                source=source,
            )
        )
    except RECOVERABLE_ERRORS:
        logger.debug("excel etl kb remember skipped", exc_info=True)
        return ""
    return fp
