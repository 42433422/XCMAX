"""Shipment writes and compensations with explicit deduplication outcomes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .fingerprints import FingerprintPorts


class ShipmentWriter(Protocol):
    def create_shipment(
        self,
        *,
        unit_name: str,
        items_data: list[dict[str, Any]],
        contact_person: str,
        external_order_number: str,
        order_date: str,
        source_fingerprint: str,
        source_kind: str,
    ) -> dict[str, Any]: ...

    def cancel_shipment(self, shipment_id: int) -> dict[str, Any]: ...

    def delete_shipment(self, shipment_id: int) -> dict[str, Any]: ...


@dataclass
class WriteOutcome:
    created: int = 0
    failed: int = 0
    shipment_ids: list[Any] = field(default_factory=list)
    created_pairs: list[tuple[Any, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    compensated: list[Any] = field(default_factory=list)
    compensate_errors: list[str] = field(default_factory=list)
    fingerprint_errors: list[str] = field(default_factory=list)
    requires_reconciliation: bool = False

    def safe_to_retry(self, *, idempotent: bool) -> bool:
        if self.requires_reconciliation or self.fingerprint_errors:
            return False
        if not self.created:
            return True
        return not self.failed and idempotent


class ShipmentPersistence:
    def __init__(
        self,
        service: ShipmentWriter,
        fingerprints: FingerprintPorts,
        logger: logging.Logger,
    ) -> None:
        self._service = service
        self._fingerprints = fingerprints
        self._logger = logger

    def _create(
        self,
        note: dict[str, Any],
        outcome: WriteOutcome,
        *,
        tenant: str,
        file_name: str,
        idempotent: bool,
    ) -> bool:
        unit = str(note.get("unit_name") or "").strip()
        items = list(note.get("items") or [])
        if not unit or not items:
            outcome.errors.append(
                f"缺少客户或明细: {note.get('order_number') or note.get('sheet')}"
            )
            return False
        try:
            result = self._service.create_shipment(
                unit_name=unit,
                items_data=items,
                contact_person=str(note.get("contact_person") or ""),
                external_order_number=str(note.get("order_number") or ""),
                order_date=str(note.get("order_date") or ""),
                source_fingerprint=str(note.get("fingerprint") or ""),
                source_kind=str(note.get("source_kind") or ""),
            )
        except RECOVERABLE_ERRORS:
            # The service can lose its connection after committing. Compensate the
            # writes we know, but never claim an unknown outcome is safe to repeat.
            self._logger.warning("shipment creation outcome is unknown", exc_info=True)
            outcome.requires_reconciliation = True
            outcome.errors.append("发货单创建异常，需核对写入结果后重试")
            return False
        if not result.get("success"):
            outcome.errors.append(str(result.get("message") or "create_shipment failed"))
            return False
        outcome.created += 1
        shipment = result.get("shipment") or {}
        shipment_id = shipment.get("id") if isinstance(shipment, dict) else None
        fingerprint = str(note.get("fingerprint") or "")
        if shipment_id is not None:
            outcome.shipment_ids.append(shipment_id)
            outcome.created_pairs.append((shipment_id, fingerprint))
        if idempotent and fingerprint:
            try:
                self._fingerprints.record(
                    tenant,
                    fingerprint,
                    shipment_id=shipment_id,
                    unit_name=unit,
                    order_number=str(note.get("order_number") or ""),
                    file_name=file_name,
                )
            except RECOVERABLE_ERRORS:
                self._logger.warning("failed to persist etl fingerprint immediately", exc_info=True)
                outcome.fingerprint_errors.append(f"去重记录写入失败: {fingerprint}")
        return True

    def _compensate(self, outcome: WriteOutcome, tenant: str) -> None:
        for shipment_id, fingerprint in outcome.created_pairs:
            removed = False
            try:
                cancelled = self._service.cancel_shipment(int(shipment_id))
                removed = bool(cancelled.get("success"))
                if not removed:
                    deleted = self._service.delete_shipment(int(shipment_id))
                    removed = bool(deleted.get("success"))
                    if not removed:
                        outcome.compensate_errors.append(
                            f"补偿失败 shipment_id={shipment_id}: "
                            f"{cancelled.get('message') or deleted.get('message')}"
                        )
            except RECOVERABLE_ERRORS:
                self._logger.warning("shipment compensation failed", exc_info=True)
                outcome.compensate_errors.append("补偿失败")
            if not removed:
                # Retain the key while its shipment may still be active.
                continue
            outcome.compensated.append(shipment_id)
            if fingerprint:
                try:
                    self._fingerprints.remove(tenant, fingerprint)
                except RECOVERABLE_ERRORS:
                    self._logger.warning(
                        "failed to delete etl fingerprint on compensate", exc_info=True
                    )
                    outcome.fingerprint_errors.append(f"补偿后的去重记录清理失败: {fingerprint}")
        outcome.created = max(0, outcome.created - len(outcome.compensated))
        compensated = set(outcome.compensated)
        outcome.shipment_ids = [sid for sid in outcome.shipment_ids if sid not in compensated]

    def execute(
        self,
        notes: list[dict[str, Any]],
        *,
        tenant: str,
        file_name: str,
        idempotent: bool,
        compensate_on_failure: bool,
    ) -> WriteOutcome:
        outcome = WriteOutcome()
        for index, note in enumerate(notes):
            if self._create(
                note, outcome, tenant=tenant, file_name=file_name, idempotent=idempotent
            ):
                continue
            outcome.failed = len(notes) - index
            if outcome.failed > 1:
                outcome.errors.append(f"因失败中止，另有 {outcome.failed - 1} 张未执行")
            break
        if outcome.failed and compensate_on_failure:
            self._compensate(outcome, tenant)
        return outcome
