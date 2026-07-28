"""Promote an identified ETL delivery-note region into the print template library."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError
from app.application.etl.service_support import (
    ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
    dump_json,
    load_json,
    new_id,
)
from app.application.etl.shipment_template_extractor import extract_shipment_template
from app.db.models.etl import EtlTemplate, EtlTemplateVersion
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_utils import get_app_data_dir


def _safe_template_name(value: str, fallback: str) -> str:
    text = str(value or fallback).strip()[:120]
    text = re.sub(r"[\\/:*?\"<>|]+", "-", text).strip(" .-")
    return text or "发货单版式"


def _selected_shipment_region(source_features: dict[str, Any]) -> dict[str, Any]:
    """Return the same first selected region the extractor promotes to a layout.

    A workbook can contain more than one delivery-note region. The saved
    document template must be named for the actual region that becomes the
    template, rather than for the arbitrary upload filename. Keep this sort
    order aligned with ``extract_shipment_template``'s region selection.
    """

    selected = [
        region
        for region in source_features.get("regions") or []
        if isinstance(region, dict) and region.get("status") == "selected"
    ]
    if not selected:
        return {}
    return sorted(
        selected,
        key=lambda region: (
            str(region.get("sheet") or ""),
            int(region.get("header_row") or 0),
        ),
    )[0]


def _shipment_template_default_name(source_features: dict[str, Any], file_name: str) -> str:
    """Prefer the selected region's canonical customer name for a layout name."""

    region = _selected_shipment_region(source_features)
    customer_name = str(
        region.get("customer_name")
        or region.get("purchase_unit")
        or region.get("unit_name")
        or ""
    ).strip()
    if customer_name:
        return f"{customer_name}-发货单版式"
    return f"{Path(file_name).stem}-发货单版式"


class ShipmentTemplateServiceMixin:
    def save_run_shipment_template(
        self,
        db: Session,
        *,
        run_id: str,
        owner_user_id: int,
        name: str = "",
    ) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.target_type != "shipment_records":
            raise EtlError(
                "ETL_SHIPMENT_TEMPLATE_TARGET_REQUIRED",
                "只有识别为发货记录的预演才能保存送货单版式",
            )
        if run.status not in {"preview_ready", "completed"}:
            raise EtlError(
                "ETL_SHIPMENT_TEMPLATE_PREVIEW_REQUIRED",
                "请等待送货单预演完成后再保存版式",
                status_code=409,
            )
        details = load_json(run.summary_json, {})
        existing = details.get("shipment_document_template")
        if isinstance(existing, dict) and existing.get("template_id"):
            return dict(existing)

        upload = self._owned_upload(db, run.upload_id, owner_user_id)
        source_features = load_json(run.source_features_json, {})
        base_name = _safe_template_name(
            name,
            _shipment_template_default_name(source_features, upload.file_name),
        )
        tenant_id = tenant_id_for_write()
        template_dir = (
            Path(get_app_data_dir()).resolve()
            / "tenants"
            / str(tenant_id)
            / "document_templates"
            / str(owner_user_id)
        )
        destination = (
            template_dir
            / f"{base_name}-{run.file_sha256[:12]}.xlsx"
        ).resolve()
        if template_dir.resolve() not in destination.parents:
            raise EtlError("ETL_SHIPMENT_TEMPLATE_PATH_INVALID", "发货单版式保存路径无效")

        extracted = extract_shipment_template(
            upload.storage_path,
            source_features=source_features,
            destination=destination,
        )
        selected_region = next(
            (
                region
                for region in source_features.get("regions") or []
                if isinstance(region, dict)
                and region.get("id") == extracted.get("source_region_id")
            ),
            _selected_shipment_region(source_features),
        )
        template_fields = [
            {"label": header, "name": header, "value": header}
            for header in selected_region.get("headers") or []
            if str(header or "").strip()
        ]
        template, version = self._save_private_shipment_document_template(
            db,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            requested_name=base_name,
            file_sha256=run.file_sha256,
            destination=destination,
            source_features=source_features,
            source_region_id=str(extracted.get("source_region_id") or ""),
            template_fields=template_fields,
        )
        result = {
            "template_id": f"etl:{template.id}",
            "name": template.name,
            "file_path": str(destination),
            "source_region_id": extracted.get("source_region_id"),
            "version": version.version,
            "message": "已保存为当前用户私有发货单版式，后续开单会按客户名自动匹配",
        }
        details["shipment_document_template"] = result
        run.summary_json = dump_json(details)
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001 - file must not outlive an unregistered private record
            db.rollback()
            destination.unlink(missing_ok=True)
            raise EtlError(
                "ETL_SHIPMENT_TEMPLATE_SAVE_FAILED",
                "发货单版式保存失败",
                status_code=500,
            ) from exc
        try:
            from app.application.shipment_template_resolve import clear_template_list_cache

            clear_template_list_cache()
        except Exception:  # noqa: BLE001 - cache invalidation must not roll back the template
            pass
        return result

    @staticmethod
    def _save_private_shipment_document_template(
        db: Session,
        *,
        tenant_id: int,
        owner_user_id: int,
        requested_name: str,
        file_sha256: str,
        destination: Path,
        source_features: dict[str, Any],
        source_region_id: str,
        template_fields: list[dict[str, str]],
    ) -> tuple[EtlTemplate, EtlTemplateVersion]:
        """Store a promoted layout in the ETL private-template namespace.

        The generic ``templates`` table intentionally has no owner column.  It
        is therefore not a safe registry for ETL layouts, which are explicitly
        personal.  This method keeps both the metadata and file reference in
        ``etl_templates``/``etl_template_versions`` where tenant + owner are
        mandatory, and creates a new immutable version when the same personal
        layout is saved again.
        """

        same_name = (
            db.query(EtlTemplate)
            .filter(
                EtlTemplate.tenant_id == tenant_id,
                EtlTemplate.owner_user_id == owner_user_id,
                EtlTemplate.name == requested_name,
                EtlTemplate.is_active.is_(True),
            )
            .first()
        )
        current = (
            same_name
            if same_name is not None
            and same_name.target_type == "shipment_records"
            and same_name.description == ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION
            else None
        )
        template_name = requested_name
        if same_name is not None and current is None:
            # A manually saved ETL mapping may legitimately use the same
            # display name. Do not replace it; keep both immutable resources
            # distinguishable while retaining the customer token for matching.
            suffix = str(file_sha256 or new_id()).replace("-", "")[:8]
            template_name = _safe_template_name(f"{requested_name}-{suffix}", requested_name)
        if current is None:
            template = EtlTemplate(
                id=new_id(),
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                name=template_name,
                target_type="shipment_records",
                current_version=1,
                description=ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
            )
            version_number = 1
            db.add(template)
        else:
            template = current
            version_number = int(template.current_version or 0) + 1
            template.current_version = version_number

        version_features = dict(source_features)
        version_features["shipment_document_template"] = {
            "file_path": str(destination),
            "sheet_name": "送货单",
            "selected_sheet_name": "送货单",
            "source_region_id": source_region_id,
            "file_sha256": str(file_sha256 or "")[:64],
            "owner_user_id": int(owner_user_id),
            "tenant_id": int(tenant_id),
        }
        version = EtlTemplateVersion(
            id=new_id(),
            template_id=template.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            version=version_number,
            target_type="shipment_records",
            source_features_json=dump_json(version_features),
            field_mappings_json=dump_json(template_fields),
            validation_rules_json=dump_json([]),
            match_keys_json=dump_json([]),
            allowed_update_fields_json=dump_json([]),
            action_rules_json=dump_json(
                {"kind": "shipment_document_layout", "source": "etl_shipment_template"}
            ),
        )
        db.add(version)
        db.flush()
        return template, version


__all__ = ["ShipmentTemplateServiceMixin"]
