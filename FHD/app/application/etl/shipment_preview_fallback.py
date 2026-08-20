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

import os
import tempfile
from datetime import UTC
from pathlib import Path
from typing import Any

from app.application.etl.service_support import load_json, utcnow
from app.application.etl.shipment_preview_products import (
    PRODUCT_PREVIEW_WARNING,
    resolve_product_candidate_outcome,
    valid_owner_and_tenant,
)
from app.application.etl.shipment_preview_products import (
    candidate_customer_name as _candidate_customer_name,
)
from app.application.etl.shipment_preview_products import (
    candidate_price as _candidate_price,
)
from app.application.etl.shipment_preview_products import (
    candidate_product_name as _candidate_product_name,
)
from app.application.etl.shipment_preview_products import (
    candidate_source_date as _candidate_source_date,
)
from app.application.etl.shipment_preview_products import (
    candidate_specification as _candidate_specification,
)
from app.application.etl.shipment_preview_products import (
    normalize_customer_name as _normalize_customer_name,
)
from app.application.etl.shipment_preview_products import (
    normalize_product_name as _normalize_product_name,
)
from app.application.etl.shipment_preview_products import (
    preview_runs as _preview_runs,
)
from app.application.etl.shipment_preview_products import (
    row_is_valid_candidate as _row_is_valid_candidate,
)
from app.application.etl.shipment_template_extractor import extract_shipment_template
from app.db.models.etl import EtlRun, EtlUpload
from app.db.session import get_db
from app.infrastructure.tenant_scope import current_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

_PREVIEW_READY = "preview_ready"
_LAYOUT_SUFFIXES = frozenset({".xlsx", ".xlsm"})
_TEMP_PREFIX = "fhd-etl-preview-layout-"

LAYOUT_PREVIEW_WARNING = (
    "发货单版式来自尚未保存的 ETL 预演候选，仅用于本次已确认的发货单；未写入模板库。"
)


def _valid_owner_and_tenant(owner_user_id: int | None) -> tuple[int, int] | None:
    return valid_owner_and_tenant(owner_user_id, current_tenant_id())


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

    return resolve_product_candidate_outcome(
        owner_user_id=owner_user_id,
        unit_name=unit_name,
        product_name=product_name,
        get_database=get_db,
        valid_scope=_valid_owner_and_tenant,
        get_preview_runs=_preview_runs,
        validate_row=_row_is_valid_candidate,
    )


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
    candidates_raw = source_features.get("shipment_template_candidates")
    candidates = (
        [candidate for candidate in candidates_raw if isinstance(candidate, dict)]
        if isinstance(candidates_raw, list)
        else []
    )
    if not candidates:
        candidate = source_features.get("shipment_template_candidate")
        if isinstance(candidate, dict):
            candidates = [candidate]
    if not candidates:
        # Runs produced before the visible-candidate UI shipped still carry the
        # same selected region evidence.  Build the metadata only; do not save
        # a template record.
        from app.application.etl.service_shipment_templates import shipment_template_candidates

        candidates = shipment_template_candidates(source_features, "发货单.xlsx")
    candidate = next(
        (
            item
            for item in candidates
            if str(item.get("status") or "") == "detected"
            and _normalize_customer_name(str(item.get("customer_name") or ""))
            == _normalize_customer_name(unit_name)
        ),
        None,
    )
    if not isinstance(candidate, dict):
        return None
    source_region_id = str(candidate.get("source_region_id") or "").strip()
    region = _selected_region(source_features, source_region_id)
    if not source_region_id or region is None:
        return None
    customer_name = str(region.get("customer_name") or candidate.get("customer_name") or "").strip()
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
            source_region_id=str(record.get("source_region_id") or ""),
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
    "_candidate_customer_name",
    "_candidate_price",
    "_candidate_product_name",
    "_candidate_source_date",
    "_candidate_specification",
    "_normalize_customer_name",
    "_normalize_product_name",
    "cleanup_ephemeral_preview_layout",
    "find_latest_preview_layout_candidate",
    "materialize_preview_layout_candidate",
    "resolve_preview_product_candidate",
    "resolve_preview_product_candidate_outcome",
]
