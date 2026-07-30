"""Read-only ETL preview candidates for one confirmed shipment document.

An ETL preview is deliberately not master data.  These helpers make a
*validated*, owner-scoped candidate usable for a single confirmed document
without silently importing it into the customer/product libraries or saving a
new document-template record.

The module is intentionally a narrow bridge between the generic ETL run store
and the shipment generator.  It does not accept file paths or row payloads
from a caller: every candidate is re-read from the current tenant and owner in
the persisted preview snapshot.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from datetime import UTC, date
from pathlib import Path
from typing import Any

from app.application.etl.service_support import load_json, utcnow
from app.application.etl.shipment_template_extractor import extract_shipment_template
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.db.session import get_db
from app.infrastructure.tenant_scope import current_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_app_data_dir

_PREVIEW_READY = "preview_ready"
_PRODUCT_ACTIONS = frozenset({"new", "update"})
_LAYOUT_SUFFIXES = frozenset({".xlsx", ".xlsm"})
_TEMP_PREFIX = "fhd-etl-preview-layout-"
_PARENTHETICAL_CUSTOMER_ALIAS_RE = re.compile(r"[（(][^）)]*[）)]")

PRODUCT_PREVIEW_WARNING = (
    "产品信息来自尚未执行的 ETL 预演候选，仅用于本次已确认的发货单；未写入产品库。"
)
LAYOUT_PREVIEW_WARNING = (
    "发货单版式来自尚未保存的 ETL 预演候选，仅用于本次已确认的发货单；未写入模板库。"
)


def _normalize_customer_name(value: Any) -> str:
    """Keep customer alias comparison aligned with shipment-number mode."""

    text = str(value or "").strip().lower()
    if not text:
        return ""
    # The ETL parser records a parenthetical trade/shop marker as alias
    # provenance and chooses the delivery-note customer as canonical.  Apply
    # that same conservative normalization here so preview product/layout
    # lookups do not lose known aliases before the confirmation service runs.
    text = _PARENTHETICAL_CUSTOMER_ALIAS_RE.sub("", text)
    text = re.sub(r"(有限责任公司|有限公司|公司|家私|家具|商贸|贸易|建材|装饰)", "", text)
    return re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)


def _normalize_product_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-_()（）【】\[\]·,，.。/\\]+", "", text)


def _valid_owner_and_tenant(owner_user_id: int | None) -> tuple[int, int] | None:
    try:
        owner = int(owner_user_id) if owner_user_id is not None else 0
    except (TypeError, ValueError):
        return None
    tenant = current_tenant_id()
    if owner <= 0 or tenant is None:
        return None
    try:
        tenant_value = int(tenant)
    except (TypeError, ValueError):
        return None
    return tenant_value, owner


def _row_is_valid_candidate(row: EtlRunRow) -> dict[str, Any] | None:
    """Return a normalized snapshot only for a user-approved valid row."""

    if str(row.final_action or "").strip().lower() not in _PRODUCT_ACTIONS:
        return None
    issues = load_json(row.validation_json, None)
    if not isinstance(issues, list) or issues:
        return None
    normalized = load_json(row.normalized_json, None)
    return normalized if isinstance(normalized, dict) else None


def _candidate_customer_name(normalized: dict[str, Any]) -> str:
    for key in ("customer_name", "purchase_unit", "unit_name"):
        value = str(normalized.get(key) or "").strip()
        if value:
            return value
    return ""


def _candidate_product_name(normalized: dict[str, Any]) -> str:
    for key in ("name", "product_name"):
        value = str(normalized.get(key) or "").strip()
        if value:
            return value
    return ""


def _candidate_price(normalized: dict[str, Any]) -> float | None:
    value = normalized.get("price")
    if value in (None, ""):
        value = normalized.get("unit_price")
    if value in (None, ""):
        return None
    try:
        price = float(str(value).replace(",", "").replace("￥", "").replace("¥", ""))
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price >= 0 else None


def _candidate_specification(normalized: dict[str, Any]) -> float | None:
    value = normalized.get("specification")
    if value in (None, ""):
        value = normalized.get("tin_spec")
    if value in (None, ""):
        return None
    try:
        specification = float(str(value).replace(",", "").replace("KG", "").replace("kg", ""))
    except (TypeError, ValueError):
        return None
    return specification if math.isfinite(specification) and specification > 0 else None


def _candidate_source_date(row: EtlRunRow) -> str:
    """Return only an evidenced ISO business date from a persisted row."""

    provenance = load_json(row.provenance_json, {})
    if not isinstance(provenance, dict):
        return ""
    value = str(provenance.get("source_date") or provenance.get("order_date") or "").strip()
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return ""


def _preview_runs(
    db: Any,
    *,
    tenant_id: int,
    owner_user_id: int,
    target_type: str,
) -> list[EtlRun]:
    """Read preview-ready runs in deterministic newest-first order."""

    return (
        db.query(EtlRun)
        .filter(
            EtlRun.tenant_id == tenant_id,
            EtlRun.owner_user_id == owner_user_id,
            EtlRun.target_type == target_type,
            EtlRun.status == _PREVIEW_READY,
        )
        .order_by(EtlRun.updated_at.desc(), EtlRun.created_at.desc(), EtlRun.id.desc())
        .limit(50)
        .all()
    )


def resolve_preview_product_candidate_outcome(
    *,
    owner_user_id: int | None,
    unit_name: str,
    product_name: str,
) -> dict[str, Any]:
    """Resolve a scoped preview candidate without hiding a data conflict.

    This is an intentionally conservative match.  The requested customer and
    product must match exactly after the same harmless alias normalization used
    by the shipment flow.  ``status`` is one of ``resolved``, ``not_found``,
    ``conflict`` or ``unavailable``.  The structured status lets confirmed
    shipment execution distinguish a genuinely absent personal preview from
    conflicting personal preview facts: the latter must not silently fall back
    to stale master-product data.

    The legacy :func:`resolve_preview_product_candidate` wrapper below retains
    its original ``dict | None`` contract for display-only callers.
    """

    scope = _valid_owner_and_tenant(owner_user_id)
    normalized_unit = _normalize_customer_name(unit_name)
    normalized_product = _normalize_product_name(product_name)
    if scope is None or not normalized_unit or not normalized_product:
        return {"status": "unavailable", "candidate": None}
    tenant_id, owner = scope

    try:
        with get_db() as db:
            matches: list[dict[str, Any]] = []
            for run_rank, run in enumerate(
                _preview_runs(
                    db,
                    tenant_id=tenant_id,
                    owner_user_id=owner,
                    target_type="customer_products",
                )
            ):
                rows = (
                    db.query(EtlRunRow)
                    .filter(
                        EtlRunRow.run_id == run.id,
                        EtlRunRow.tenant_id == tenant_id,
                        EtlRunRow.owner_user_id == owner,
                    )
                    .order_by(
                        EtlRunRow.source_sheet.asc(),
                        EtlRunRow.source_row.asc(),
                        EtlRunRow.id.asc(),
                    )
                    .all()
                )
                for row in rows:
                    normalized = _row_is_valid_candidate(row)
                    if normalized is None:
                        continue
                    candidate_unit = _candidate_customer_name(normalized)
                    candidate_name = _candidate_product_name(normalized)
                    if (
                        _normalize_customer_name(candidate_unit) != normalized_unit
                        or _normalize_product_name(candidate_name) != normalized_product
                    ):
                        continue
                    model_number = str(normalized.get("model_number") or "").strip().upper()
                    price = _candidate_price(normalized)
                    matches.append(
                        {
                            "run": run,
                            "run_rank": run_rank,
                            "row": row,
                            "normalized": normalized,
                            "name": candidate_name,
                            "model_number": model_number,
                            "price": price,
                            "specification": _candidate_specification(normalized),
                            "source_date": _candidate_source_date(row),
                        }
                    )

            if not matches:
                return {"status": "not_found", "candidate": None}

            # Prefer the newest *business fact*, not the most recently
            # uploaded workbook.  An old upload with a newer delivery date is
            # still more authoritative than a newly uploaded historical file.
            dated = [match for match in matches if match["source_date"]]
            if dated:
                newest_date = max(str(match["source_date"]) for match in dated)
                finalists = [match for match in dated if match["source_date"] == newest_date]
            else:
                # Legacy previews without provenance dates retain their
                # newest-preview ordering, but must still agree exactly.
                newest_run_rank = min(int(match["run_rank"]) for match in matches)
                finalists = [
                    match for match in matches if int(match["run_rank"]) == newest_run_rank
                ]

            # Repeated delivery rows are normal.  Conflicting same-date facts
            # are not: do not choose a model/price/specification based on a
            # worksheet or upload ordering the user never confirmed.
            identities = {
                (
                    _normalize_product_name(str(match["name"])),
                    str(match["model_number"]),
                    match["price"],
                    match["specification"],
                )
                for match in finalists
            }
            if len(identities) != 1:
                return {"status": "conflict", "candidate": None}

            finalist = sorted(
                finalists,
                key=lambda match: (
                    int(match["run_rank"]),
                    str(match["row"].source_sheet or ""),
                    int(match["row"].source_row),
                    int(match["row"].id or 0),
                ),
            )[0]
            row = finalist["row"]
            candidate_name = str(finalist["name"])
            model_number = str(finalist["model_number"])
            price = finalist["price"]
            specification = finalist["specification"]
            source_date = str(finalist["source_date"])
            return {
                "status": "resolved",
                "candidate": {
                    "name": candidate_name,
                    "model_number": model_number,
                    "price": price,
                    "specification": specification,
                    "source_date": source_date or None,
                    "unit_name": str(unit_name or "").strip(),
                    "warning": PRODUCT_PREVIEW_WARNING,
                    "provenance": {
                        "kind": "etl_preview_product_candidate",
                        "run_id": str(finalist["run"].id),
                        "source_sheet": str(row.source_sheet or ""),
                        "source_row": int(row.source_row),
                        "source_date": source_date or None,
                        "resolved_product": {
                            "name": candidate_name,
                            "model_number": model_number,
                            "unit_price": price,
                            "specification": specification,
                        },
                    },
                },
            }
    except RECOVERABLE_ERRORS:
        # A preview fallback must never turn an unavailable ETL store into a
        # permissive document generation path.  Callers retain their normal
        # strict product-not-found response unless a known conflict was found.
        return {"status": "unavailable", "candidate": None}
    return {"status": "not_found", "candidate": None}


def resolve_preview_product_candidate(
    *,
    owner_user_id: int | None,
    unit_name: str,
    product_name: str,
) -> dict[str, Any] | None:
    """Find one exact, valid product candidate from this user's ETL preview.

    Backward-compatible display-oriented wrapper.  Callers that must keep a
    confirmed shipment from falling back to stale master data on a known ETL
    conflict should use :func:`resolve_preview_product_candidate_outcome`.
    """

    outcome = resolve_preview_product_candidate_outcome(
        owner_user_id=owner_user_id,
        unit_name=unit_name,
        product_name=product_name,
    )
    if not isinstance(outcome, dict) or outcome.get("status") != "resolved":
        return None
    candidate = outcome.get("candidate")
    return dict(candidate) if isinstance(candidate, dict) else None


from app.application.etl.preview_layout_candidates import (
    cleanup_ephemeral_preview_layout,
    find_latest_preview_layout_candidate,
    materialize_preview_layout_candidate,
)

__all__ = [
    "LAYOUT_PREVIEW_WARNING",
    "PRODUCT_PREVIEW_WARNING",
    "cleanup_ephemeral_preview_layout",
    "find_latest_preview_layout_candidate",
    "materialize_preview_layout_candidate",
    "resolve_preview_product_candidate",
    "resolve_preview_product_candidate_outcome",
]
