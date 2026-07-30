"""Purchase order and shipment ETL target adapters."""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import or_

from app.application.etl.errors import EtlError
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.etl.targets.helpers import (
    assert_snapshot_unchanged,
    decimal_or_zero,
    issue,
    optional_text,
    parse_date,
)
from app.db.models.product import Product
from app.db.models.purchase import PurchaseOrder, PurchaseOrderItem, Supplier
from app.db.models.shipment import ShipmentRecord
from app.infrastructure.tenant_scope import tenant_id_for_write


def _ranked_names(value: Any, candidates: list[str]) -> list[str]:
    incoming = str(value or "").strip().casefold()
    if not incoming:
        return []
    ranked = sorted(
        (
            (SequenceMatcher(None, incoming, candidate.casefold()).ratio(), candidate)
            for candidate in candidates
            if candidate
        ),
        reverse=True,
    )
    return [candidate for score, candidate in ranked[:3] if score >= 0.45]


def _cached_master_names(db: Any, context: dict[str, Any], model: Any, key: str) -> list[str]:
    cache = context.get("_preview_cache")
    cache_key = f"purchase_order_master_names:{key}"
    if isinstance(cache, dict) and cache_key in cache:
        return list(cache[cache_key])
    names = [
        str(row[0] or "").strip()
        for row in db.query(model.name).filter(model.name.isnot(None)).limit(500).all()
        if str(row[0] or "").strip()
    ]
    if isinstance(cache, dict):
        cache[cache_key] = names
    return names


def _candidate_message(label: str, candidates: list[str]) -> str:
    if not candidates:
        return f"{label}不存在"
    return f"{label}没有唯一匹配；候选：{'、'.join(candidates)}。请确认或先补全主数据"


class ShipmentAdapter(TargetAdapter):
    type = "shipment_records"
    label = "发货记录"
    reversible = True
    fields = (
        TargetField(
            "purchase_unit", "购买单位", required=True, aliases=("购货单位", "客户", "单位")
        ),
        TargetField("external_order_no", "外部单号", aliases=("单号", "订单号")),
        TargetField("source_fingerprint", "源单据指纹", aliases=("源指纹",)),
        TargetField("legacy_note_fingerprint", "兼容单据指纹", aliases=("兼容指纹",)),
        TargetField("product_name", "产品名称", required=True, aliases=("品名", "产品")),
        TargetField("model_number", "型号", aliases=("型号",)),
        TargetField("quantity_kg", "公斤数", type="number", aliases=("重量", "公斤", "kg")),
        TargetField("quantity_tins", "桶数", type="integer", aliases=("桶数", "数量")),
        TargetField("tin_spec", "桶规格", type="number", aliases=("桶规格",)),
        TargetField("unit_price", "单价", type="number", aliases=("单价",)),
        TargetField("amount", "金额", type="number", aliases=("金额", "合计")),
    )
    default_match_keys = ("source_fingerprint", "external_order_no")

    def _fingerprint(self, data: dict[str, Any], context: dict[str, Any]) -> str:
        supplied = str(data.get("source_fingerprint") or "").strip()
        if supplied:
            return supplied
        payload = {
            "file": context.get("file_sha256"),
            "order": data.get("external_order_no"),
            "unit": data.get("purchase_unit"),
            "product": data.get("product_name"),
            "model": data.get("model_number"),
            "kg": data.get("quantity_kg"),
            "tins": data.get("quantity_tins"),
            "row": context.get("source_row"),
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _belongs_to_current_run(record: ShipmentRecord, run_id: Any) -> bool:
        """Allow distinct delivery lines of one external order in one ETL run."""

        expected = str(run_id or "").strip()
        if not expected:
            return False
        try:
            parsed = json.loads(str(record.parsed_data or "{}"))
        except (TypeError, ValueError):
            return False
        return isinstance(parsed, dict) and str(parsed.get("etl_run_id") or "") == expected

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        if data.get("quantity_kg") in (None, "") and data.get("quantity_tins") in (None, ""):
            issues.append(issue("ETL_QUANTITY_REQUIRED", "quantity_kg", "公斤数或桶数至少填写一项"))
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        fingerprint = self._fingerprint(data, context)
        from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

        tenant_key = f"tenant:{tenant_id_for_write()}"
        existing_fp = (
            db.query(ShipmentEtlImportFingerprint)
            .filter(
                ShipmentEtlImportFingerprint.tenant_key == tenant_key,
                ShipmentEtlImportFingerprint.fingerprint == fingerprint,
            )
            .first()
        )
        if existing_fp:
            return PreviewDecision(
                "skip",
                match_ref=str(existing_fp.shipment_id or ""),
                reason="legacy_fingerprint_duplicate",
            )
        legacy_note_fingerprint = str(data.get("legacy_note_fingerprint") or "").strip()
        if legacy_note_fingerprint:
            legacy_note_match = (
                db.query(ShipmentEtlImportFingerprint)
                .filter(
                    ShipmentEtlImportFingerprint.tenant_key == tenant_key,
                    ShipmentEtlImportFingerprint.fingerprint == legacy_note_fingerprint,
                    or_(
                        ShipmentEtlImportFingerprint.source_kind.is_(None),
                        ShipmentEtlImportFingerprint.source_kind != "general_etl_legacy_note",
                    ),
                )
                .first()
            )
            if legacy_note_match:
                return PreviewDecision(
                    "skip",
                    match_ref=str(legacy_note_match.shipment_id or ""),
                    reason="legacy_note_fingerprint_duplicate",
                )
        order_no = str(data.get("external_order_no") or "").strip()
        legacy_query = db.query(ShipmentEtlImportFingerprint).filter(
            ShipmentEtlImportFingerprint.tenant_key == tenant_key,
            or_(
                ShipmentEtlImportFingerprint.source_kind.is_(None),
                ShipmentEtlImportFingerprint.source_kind != "general_etl",
            ),
        )
        if order_no:
            legacy_query = legacy_query.filter(
                ShipmentEtlImportFingerprint.order_number == order_no
            )
        else:
            legacy_query = legacy_query.filter(
                ShipmentEtlImportFingerprint.file_name == str(context.get("file_name") or ""),
                ShipmentEtlImportFingerprint.unit_name == str(data.get("purchase_unit") or ""),
            )
        legacy_match = legacy_query.first()
        if legacy_match:
            return PreviewDecision(
                "skip",
                match_ref=str(legacy_match.shipment_id or ""),
                reason="legacy_source_duplicate",
            )
        if order_no:
            existing_records = (
                db.query(ShipmentRecord)
                .filter(
                    or_(
                        ShipmentRecord.parsed_data.contains(
                            f'"external_order_no": "{order_no}"',
                            autoescape=True,
                        ),
                        ShipmentRecord.raw_text.contains(
                            f"external_order_number={order_no}",
                            autoescape=True,
                        ),
                    )
                )
                .all()
            )
            # One delivery note commonly contains multiple product lines with
            # one external order number. The source fingerprint makes each
            # line idempotent; only records from another run make this order a
            # duplicate. Without this exemption the second line would fail
            # during execution after the first was inserted.
            if any(
                not self._belongs_to_current_run(record, context.get("run_id"))
                for record in existing_records
            ):
                return PreviewDecision(
                    "skip",
                    match_ref=str(existing_records[0].id),
                    reason="external_order_duplicate",
                )
        return PreviewDecision(
            "new",
            after={**json_safe(data), "_fingerprint": fingerprint},
            reason="new_shipment",
        )

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        fingerprint = self._fingerprint(data, context)
        current = self.preview(
            db,
            data,
            allowed_update_fields=allowed_update_fields,
            context=context,
        )
        if current.action != "new":
            raise EtlError(
                "ETL_MATCH_CHANGED",
                "发货记录在预演后已存在，请重新预演",
                status_code=409,
            )
        parsed = {
            "external_order_no": data.get("external_order_no"),
            "etl_run_id": context.get("run_id"),
            "etl_fingerprint": fingerprint,
        }
        quantity_kg = float(decimal_or_zero(data.get("quantity_kg")))
        quantity_tins = int(decimal_or_zero(data.get("quantity_tins")))
        obj = ShipmentRecord(
            tenant_id=tenant_id_for_write(),
            purchase_unit=str(data["purchase_unit"]),
            product_name=str(data["product_name"]),
            model_number=optional_text(data.get("model_number")),
            quantity_kg=quantity_kg,
            quantity_tins=quantity_tins,
            tin_spec=float(decimal_or_zero(data.get("tin_spec"))) or None,
            unit_price=decimal_or_zero(data.get("unit_price")),
            amount=decimal_or_zero(data.get("amount")),
            status="pending",
            raw_text=json.dumps(json_safe(data), ensure_ascii=False),
            parsed_data=json.dumps(parsed, ensure_ascii=False),
        )
        db.add(obj)
        db.flush()
        from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

        db.add(
            ShipmentEtlImportFingerprint(
                tenant_key=f"tenant:{tenant_id_for_write()}",
                fingerprint=fingerprint,
                shipment_id=obj.id,
                unit_name=obj.purchase_unit,
                order_number=optional_text(data.get("external_order_no")),
                file_name=str(context.get("file_name") or ""),
                source_kind="general_etl",
                meta_json=json.dumps({"run_id": context.get("run_id")}),
            )
        )
        # ``legacy_note_fingerprint`` is read only: it detects records created
        # by the old shipment ETL. Do not write it for every line of a new
        # multi-line note, otherwise line two would see line one as a duplicate.
        return {"match_ref": str(obj.id), "after": obj.to_dict()}

    def rollback_row(self, db, *, match_ref, before, after, context):
        if not match_ref:
            return
        obj = db.get(ShipmentRecord, int(match_ref))
        if obj:
            assert_snapshot_unchanged(obj, after, "发货记录")
            db.delete(obj)
        from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint

        db.query(ShipmentEtlImportFingerprint).filter(
            ShipmentEtlImportFingerprint.shipment_id == int(match_ref)
        ).delete(synchronize_session=False)


__all__ = ["ShipmentAdapter"]
