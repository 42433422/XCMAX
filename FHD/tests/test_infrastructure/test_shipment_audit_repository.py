"""Branch coverage for app.infrastructure.persistence.shipment_audit_repository.

Covers insert_event branches + count_by_decision month filter (0/8 branches).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _mock_db_ctx(mock_db):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _make_row(**overrides):
    m = MagicMock()
    defaults = {
        "id": 42,
        "created_at": datetime(2026, 6, 1),
        "shipment_id": None,
        "decision": "manual",
        "reason": None,
        "ocr_confidence": None,
        "source": "shipment",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


class TestInsertEvent:
    def _patch_model(self, row):
        return patch(
            "app.infrastructure.persistence.shipment_audit_repository.ShipmentAuditEvent",
            return_value=row,
        )

    def test_insert_with_explicit_created_at(self):
        mock_db = MagicMock()
        row = _make_row(
            id=42,
            created_at=datetime(2026, 6, 1),
            shipment_id=5,
            decision="auto_approve",
            reason="ok",
            ocr_confidence=0.9,
            source="shipment",
        )
        with (
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            self._patch_model(row),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            result = repo.insert_event(
                decision="auto_approve",
                reason="ok",
                shipment_id=5,
                ocr_confidence=0.9,
                source="shipment",
                created_at=datetime(2026, 6, 1),
            )
        assert result["id"] == 42
        assert result["decision"] == "auto_approve"
        assert result["shipment_id"] == 5
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_insert_with_default_created_at(self):
        mock_db = MagicMock()
        row = _make_row(id=1, created_at=datetime(2026, 6, 1), shipment_id=None)
        with (
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            self._patch_model(row),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            result = repo.insert_event(decision="manual")
        assert result["id"] == 1
        assert result["shipment_id"] is None
        assert result["ocr_confidence"] is None

    def test_insert_truncates_long_reason(self):
        mock_db = MagicMock()
        long_reason = "x" * 1000
        captured = {}

        def _make_event(**kwargs):
            captured.update(kwargs)
            return _make_row(reason=kwargs.get("reason"))

        with (
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.ShipmentAuditEvent",
                side_effect=_make_event,
            ),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            repo.insert_event(decision="manual", reason=long_reason)
        # reason is truncated to 512 chars then `or None`
        assert captured["reason"] is not None
        assert len(captured["reason"]) <= 512

    def test_insert_empty_reason_becomes_none(self):
        mock_db = MagicMock()
        captured = {}

        def _make_event(**kwargs):
            captured.update(kwargs)
            return _make_row(reason=kwargs.get("reason"))

        with (
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.ShipmentAuditEvent",
                side_effect=_make_event,
            ),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            repo.insert_event(decision="manual", reason="")
        assert captured["reason"] is None

    def test_insert_none_reason_becomes_none(self):
        mock_db = MagicMock()
        captured = {}

        def _make_event(**kwargs):
            captured.update(kwargs)
            return _make_row(reason=kwargs.get("reason"))

        with (
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.ShipmentAuditEvent",
                side_effect=_make_event,
            ),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            repo.insert_event(decision="manual", reason=None)
        assert captured["reason"] is None

    def test_insert_none_created_at_in_result(self):
        mock_db = MagicMock()
        row = _make_row(created_at=None)
        with (
            patch(
                "app.infrastructure.persistence.shipment_audit_repository.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            self._patch_model(row),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            result = repo.insert_event(decision="manual")
        assert result["created_at"] is None


class TestCountByDecision:
    def test_count_all_decisions(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.all.return_value = [
            ("auto_approve",),
            ("auto_approve",),
            ("manual",),
            ("ocr_failed",),
            ("unknown_decision",),  # not in counts dict but counts toward total
            (None,),
        ]
        with patch(
            "app.infrastructure.persistence.shipment_audit_repository.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            result = repo.count_by_decision()
        assert result["auto_approve"] == 2
        assert result["manual"] == 1
        assert result["ocr_failed"] == 1
        assert result["total"] == 6

    def test_count_with_month_filter(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [("auto_approve",)]
        with patch(
            "app.infrastructure.persistence.shipment_audit_repository.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            result = repo.count_by_decision(month="2026-06")
        assert result["auto_approve"] == 1
        assert result["total"] == 1
        mock_q.filter.assert_called_once()

    def test_count_empty(self):
        mock_db = MagicMock()
        mock_q = MagicMock()
        mock_db.query.return_value = mock_q
        mock_q.all.return_value = []
        with patch(
            "app.infrastructure.persistence.shipment_audit_repository.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            from app.infrastructure.persistence.shipment_audit_repository import (
                ShipmentAuditRepository,
            )

            repo = ShipmentAuditRepository()
            result = repo.count_by_decision()
        assert result["total"] == 0
        assert result["auto_approve"] == 0


class TestSingleton:
    def test_get_shipment_audit_repository_singleton(self):
        import app.infrastructure.persistence.shipment_audit_repository as mod

        mod._shipment_audit_repository = None
        from app.infrastructure.persistence.shipment_audit_repository import (
            get_shipment_audit_repository,
        )

        r1 = get_shipment_audit_repository()
        r2 = get_shipment_audit_repository()
        assert r1 is r2
