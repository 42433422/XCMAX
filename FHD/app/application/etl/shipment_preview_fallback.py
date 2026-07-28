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
from datetime import UTC
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


def resolve_preview_product_candidate(
    *,
    owner_user_id: int | None,
    unit_name: str,
    product_name: str,
) -> dict[str, Any] | None:
    """Find one exact, valid product candidate from this user's ETL preview.

    This is an intentionally conservative match.  The requested customer and
    product must match exactly after the same harmless alias normalization used
    by the shipment flow.  If a newer run contains conflicting candidate
    details for the same product, the function fails closed instead of choosing
    a price or model on the user's behalf.
    """

    scope = _valid_owner_and_tenant(owner_user_id)
    normalized_unit = _normalize_customer_name(unit_name)
    normalized_product = _normalize_product_name(product_name)
    if scope is None or not normalized_unit or not normalized_product:
        return None
    tenant_id, owner = scope

    try:
        with get_db() as db:
            for run in _preview_runs(
                db,
                tenant_id=tenant_id,
                owner_user_id=owner,
                target_type="customer_products",
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
                matches: list[tuple[EtlRunRow, dict[str, Any], str, str, float | None]] = []
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
                    matches.append((row, normalized, candidate_name, model_number, price))

                if not matches:
                    continue

                # Repeated delivery rows are normal.  They are safe only when
                # all business attributes that could affect the printed order
                # agree; otherwise the user needs to select/correct the row in
                # the ETL preview first.
                identities = {
                    (
                        _normalize_product_name(name),
                        model_number,
                        price,
                    )
                    for _row, _normalized, name, model_number, price in matches
                }
                if len(identities) != 1:
                    return None

                row, _normalized, candidate_name, model_number, price = matches[0]
                return {
                    "name": candidate_name,
                    "model_number": model_number,
                    "price": price,
                    "unit_name": str(unit_name or "").strip(),
                    "warning": PRODUCT_PREVIEW_WARNING,
                    "provenance": {
                        "kind": "etl_preview_product_candidate",
                        "run_id": str(run.id),
                        "source_sheet": str(row.source_sheet or ""),
                        "source_row": int(row.source_row),
                        "resolved_product": {
                            "name": candidate_name,
                            "model_number": model_number,
                            "unit_price": price,
                        },
                    },
                }
    except RECOVERABLE_ERRORS:
        # A preview fallback must never turn an unavailable ETL store into a
        # permissive document generation path.  Callers retain their normal
        # strict product-not-found response.
        return None
    return None


def _selected_region(
    source_features: dict[str, Any], source_region_id: str
) -> dict[str, Any] | None:
    for region in source_features.get("regions") or []:
        if not isinstance(region, dict):
            continue
        if (
            str(region.get("id") or "") == source_region_id
            and str(region.get("status") or "") == "selected"
        ):
            return region
    return None


def _layout_candidate_for_run(
    db: Any,
    *,
    run: EtlRun,
    tenant_id: int,
    owner_user_id: int,
    unit_name: str,
) -> dict[str, Any] | None:
    source_features = load_json(run.source_features_json, {})
    if not isinstance(source_features, dict):
        return None
    candidate = source_features.get("shipment_template_candidate")
    if not isinstance(candidate, dict):
        # Runs produced before the visible-candidate UI shipped still carry the
        # same selected region evidence.  Build the metadata only; do not save
        # a template record.
        from app.application.etl.service_shipment_templates import shipment_template_candidate

        candidate = shipment_template_candidate(source_features, "发货单.xlsx")
    if not isinstance(candidate, dict) or candidate.get("status") != "detected":
        return None
    source_region_id = str(candidate.get("source_region_id") or "").strip()
    if not source_region_id:
        return None
    region = _selected_region(source_features, source_region_id)
    if region is None:
        return None
    customer_name = str(region.get("customer_name") or candidate.get("customer_name") or "").strip()
    if not customer_name or _normalize_customer_name(customer_name) != _normalize_customer_name(
        unit_name
    ):
        return None
    upload = (
        db.query(EtlUpload)
        .filter(
            EtlUpload.id == run.upload_id,
            EtlUpload.tenant_id == tenant_id,
            EtlUpload.owner_user_id == owner_user_id,
        )
        .first()
    )
    if upload is None:
        return None
    return {
        "run_id": str(run.id),
        "template_id": f"etl-preview:{run.id}",
        "name": str(candidate.get("name") or f"{customer_name}-发货单版式").strip(),
        "customer_name": customer_name,
        "source_region_id": source_region_id,
        "sheet": str(region.get("sheet") or candidate.get("sheet") or ""),
        "header_row": int(region.get("header_row") or candidate.get("header_row") or 0),
        "file_name": str(upload.file_name or ""),
        "file_sha256": str(run.file_sha256 or ""),
        "source_features": source_features,
        # Copy scalar upload metadata while the read session is alive.  The
        # normal ``get_db`` context commits on exit and expires ORM objects;
        # returning an ORM upload here would make the later one-use extraction
        # depend on a detached instance.
        "upload_storage_path": str(upload.storage_path or ""),
        "upload_suffix": str(upload.suffix or ""),
        "upload_expires_at": upload.expires_at,
    }


def _public_layout_candidate(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": record["run_id"],
        "template_id": record["template_id"],
        "name": record["name"],
        "customer_name": record["customer_name"],
        "source_region_id": record["source_region_id"],
        "sheet": record["sheet"],
        "header_row": record["header_row"],
        "file_name": record["file_name"],
        "warning": LAYOUT_PREVIEW_WARNING,
        "provenance": {
            "kind": "etl_preview_layout_candidate",
            "run_id": record["run_id"],
            "source_region_id": record["source_region_id"],
            "source_sheet": record["sheet"],
            "source_header_row": record["header_row"],
        },
    }


def _find_preview_layout_record(
    *,
    owner_user_id: int | None,
    unit_name: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    scope = _valid_owner_and_tenant(owner_user_id)
    if scope is None or not _normalize_customer_name(unit_name):
        return None
    tenant_id, owner = scope
    try:
        with get_db() as db:
            if run_id:
                run = (
                    db.query(EtlRun)
                    .filter(
                        EtlRun.id == str(run_id),
                        EtlRun.tenant_id == tenant_id,
                        EtlRun.owner_user_id == owner,
                        EtlRun.target_type == "shipment_records",
                        EtlRun.status == _PREVIEW_READY,
                    )
                    .first()
                )
                if run is None:
                    return None
                return _layout_candidate_for_run(
                    db,
                    run=run,
                    tenant_id=tenant_id,
                    owner_user_id=owner,
                    unit_name=unit_name,
                )

            for run in _preview_runs(
                db,
                tenant_id=tenant_id,
                owner_user_id=owner,
                target_type="shipment_records",
            ):
                candidate = _layout_candidate_for_run(
                    db,
                    run=run,
                    tenant_id=tenant_id,
                    owner_user_id=owner,
                    unit_name=unit_name,
                )
                if candidate is not None:
                    return candidate
    except RECOVERABLE_ERRORS:
        return None
    return None


def find_latest_preview_layout_candidate(
    *,
    owner_user_id: int | None,
    unit_name: str,
) -> dict[str, Any] | None:
    """Return display-safe metadata for the newest matching ETL layout.

    The result intentionally has no source path and creates no file.  It is
    suitable for a confirmation card or a data-docking history view.
    """

    record = _find_preview_layout_record(
        owner_user_id=owner_user_id,
        unit_name=unit_name,
    )
    return _public_layout_candidate(record) if record is not None else None


def _safe_owned_upload_path(
    storage_path: str,
    suffix: str,
    expires_at: Any,
    *,
    tenant_id: int,
    owner_user_id: int,
) -> Path | None:
    """Allow extraction only from the managed upload sandbox for this owner."""

    try:
        root = (
            Path(get_app_data_dir()).resolve()
            / "etl"
            / "uploads"
            / str(tenant_id)
            / str(owner_user_id)
        ).resolve()
        path = Path(str(storage_path or "")).resolve()
    except (OSError, TypeError, ValueError):
        return None
    if (
        root not in path.parents
        or not path.is_file()
        or path.suffix.lower() not in _LAYOUT_SUFFIXES
        or str(suffix or "").lower() not in _LAYOUT_SUFFIXES
    ):
        return None
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < utcnow():
            return None
    return path


def materialize_preview_layout_candidate(
    *,
    owner_user_id: int | None,
    unit_name: str,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Extract a one-use layout into a private OS temp file.

    This is called only by the confirmed document generation flow.  The caller
    must call :func:`cleanup_ephemeral_preview_layout` after the synchronous
    generator has consumed the file.
    """

    record = _find_preview_layout_record(
        owner_user_id=owner_user_id,
        unit_name=unit_name,
        run_id=run_id,
    )
    scope = _valid_owner_and_tenant(owner_user_id)
    if record is None or scope is None:
        return None
    tenant_id, owner = scope
    upload_path = _safe_owned_upload_path(
        record["upload_storage_path"],
        record["upload_suffix"],
        record["upload_expires_at"],
        tenant_id=tenant_id,
        owner_user_id=owner,
    )
    if upload_path is None:
        return None

    descriptor, raw_destination = tempfile.mkstemp(prefix=_TEMP_PREFIX, suffix=".xlsx")
    os.close(descriptor)
    destination = Path(raw_destination)
    try:
        extract_shipment_template(
            upload_path,
            source_features=record["source_features"],
            destination=destination,
        )
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise OSError("ETL preview layout extraction produced no file")
        public = _public_layout_candidate(record)
        public.update(
            {
                "path": str(destination),
                "cleanup_path": str(destination),
                "source": "etl_preview_candidate",
            }
        )
        return public
    except RECOVERABLE_ERRORS:
        cleanup_ephemeral_preview_layout(destination)
        return None


def cleanup_ephemeral_preview_layout(value: str | Path | None) -> None:
    """Delete only a path we created under the OS temp directory."""

    try:
        path = Path(value or "").resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
    except (OSError, TypeError, ValueError):
        return
    if (
        temp_root in path.parents
        and path.name.startswith(_TEMP_PREFIX)
        and path.suffix.lower() == ".xlsx"
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return


__all__ = [
    "LAYOUT_PREVIEW_WARNING",
    "PRODUCT_PREVIEW_WARNING",
    "cleanup_ephemeral_preview_layout",
    "find_latest_preview_layout_candidate",
    "materialize_preview_layout_candidate",
    "resolve_preview_product_candidate",
]
