"""发货单审单应用服务单测。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.application.shipment_audit_app_service import ShipmentAuditAppService
from app.domain.shipment.audit_rules import evaluate_ocr_payload, evaluate_shipment_payload


class TestAuditRules:
    def test_auto_approve_valid_shipment(self):
        result = evaluate_shipment_payload(
            {
                "purchase_unit": "测试公司",
                "items": [{"product_name": "产品A", "quantity_kg": 10, "amount": 100}],
            }
        )
        assert result.decision == "auto_approve"

    def test_manual_missing_unit(self):
        result = evaluate_shipment_payload({"items": [{"product_name": "A", "quantity_kg": 1}]})
        assert result.decision == "manual"

    def test_ocr_failed_no_unit(self):
        result = evaluate_ocr_payload({"purchase_unit": None}, parse_ok=False)
        assert result.decision == "ocr_failed"

    def test_ocr_low_confidence_manual(self):
        result = evaluate_ocr_payload(
            {
                "purchase_unit": "公司",
                "products": [{"name": "A", "quantity": 1, "total_price": 1}],
            },
            ocr_confidence=0.1,
            parse_ok=True,
        )
        assert result.decision == "manual"


class TestShipmentAuditAppService:
    @pytest.fixture
    def repo(self):
        mock = MagicMock()
        mock.insert_event.return_value = {"id": 1, "decision": "auto_approve"}
        return mock

    def test_audit_from_shipment_persists(self, repo):
        svc = ShipmentAuditAppService(repository=repo)
        shipment = MagicMock()
        shipment.to_dict.return_value = {
            "id": 42,
            "purchase_unit": "单位A",
            "items": [{"product_name": "P1", "quantity_kg": 5, "amount": 50}],
        }
        out = svc.audit_from_shipment(shipment)
        assert out["success"] is True
        assert out["decision"] == "auto_approve"
        repo.insert_event.assert_called_once()

    def test_audit_from_ocr_text(self, repo, monkeypatch):
        svc = ShipmentAuditAppService(repository=repo)

        class FakeOcr:
            def extract_structured_data(self, text):
                return {
                    "purchase_unit": "OCR单位",
                    "products": [{"name": "X", "quantity": 2, "total_price": 20}],
                }

        monkeypatch.setattr(
            "app.application.ocr_app_service.get_ocr_application_service",
            lambda: FakeOcr(),
        )
        out = svc.audit_from_ocr_text("购货单位：OCR单位\n产品", ocr_confidence=0.9)
        assert out["success"] is True
        repo.insert_event.assert_called_once()
