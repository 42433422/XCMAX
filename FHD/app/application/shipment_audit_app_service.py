"""发货单自动审单应用服务。"""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import logging
from typing import Any

from app.domain.shipment.audit_rules import evaluate_ocr_payload, evaluate_shipment_payload
from app.infrastructure.persistence.shipment_audit_repository import (
    ShipmentAuditRepository,
    get_shipment_audit_repository,
)

logger = logging.getLogger(__name__)


class ShipmentAuditAppService:
    def __init__(self, repository: ShipmentAuditRepository | None = None) -> None:
        self._repository = repository or get_shipment_audit_repository()

    def _persist_decision(
        self,
        decision: str,
        reason: str,
        *,
        shipment_id: int | None = None,
        ocr_confidence: float | None = None,
        source: str = "shipment",
    ) -> dict[str, Any]:
        event = self._repository.insert_event(
            decision=decision,
            reason=reason,
            shipment_id=shipment_id,
            ocr_confidence=ocr_confidence,
            source=source,
        )
        return {"success": True, "event": event, "decision": decision, "reason": reason}

    def audit_from_shipment(self, shipment: Any) -> dict[str, Any]:
        """发货单创建后规则审单。"""
        try:
            payload = shipment.to_dict() if hasattr(shipment, "to_dict") else dict(shipment or {})
            shipment_id = payload.get("id")
            result = evaluate_shipment_payload(
                {
                    "purchase_unit": payload.get("purchase_unit"),
                    "unit_name": payload.get("purchase_unit"),
                    "items": payload.get("items") or [],
                }
            )
            return self._persist_decision(
                result.decision,
                result.reason,
                shipment_id=int(shipment_id) if shipment_id else None,
                source="shipment",
            )
        except OPERATIONAL_ERRORS as exc:
            logger.exception("audit_from_shipment failed")
            return self._persist_decision("manual", f"审单异常: {exc}", source="shipment")

    def audit_from_ocr(
        self,
        *,
        structured: dict[str, Any],
        ocr_confidence: float | None = None,
        parse_ok: bool = True,
        shipment_id: int | None = None,
    ) -> dict[str, Any]:
        """OCR 结构化结果审单。"""
        result = evaluate_ocr_payload(
            structured,
            ocr_confidence=ocr_confidence,
            parse_ok=parse_ok,
        )
        return self._persist_decision(
            result.decision,
            result.reason,
            shipment_id=shipment_id,
            ocr_confidence=ocr_confidence,
            source="ocr",
        )

    def audit_from_ocr_text(
        self,
        text: str,
        *,
        ocr_confidence: float | None = None,
        shipment_id: int | None = None,
    ) -> dict[str, Any]:
        """从 OCR 原文提取结构化字段并审单。"""
        from app.application.ocr_app_service import get_ocr_application_service

        if not (text or "").strip():
            return self.audit_from_ocr(structured={}, parse_ok=False, shipment_id=shipment_id)

        structured = get_ocr_application_service().extract_structured_data(text)
        parse_ok = bool(structured.get("purchase_unit"))
        return self.audit_from_ocr(
            structured=structured,
            ocr_confidence=ocr_confidence,
            parse_ok=parse_ok,
            shipment_id=shipment_id,
        )

    def run_manual_audit(
        self,
        *,
        unit_name: str,
        items: list[dict[str, Any]],
        shipment_id: int | None = None,
    ) -> dict[str, Any]:
        """运营线 API：手动触发审单。"""
        result = evaluate_shipment_payload(
            {"purchase_unit": unit_name, "unit_name": unit_name, "items": items}
        )
        return self._persist_decision(
            result.decision,
            result.reason,
            shipment_id=shipment_id,
            source="api",
        )

    def monthly_counts(self, *, month: str | None = None) -> dict[str, Any]:
        return {"success": True, "counts": self._repository.count_by_decision(month=month)}


_shipment_audit_app_service: ShipmentAuditAppService | None = None


def get_shipment_audit_app_service() -> ShipmentAuditAppService:
    global _shipment_audit_app_service
    if _shipment_audit_app_service is None:
        _shipment_audit_app_service = ShipmentAuditAppService()
    return _shipment_audit_app_service
