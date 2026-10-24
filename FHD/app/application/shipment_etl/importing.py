"""Import admission and orchestration, separate from workbook parsing and writes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.application import shipment_excel_etl_security as security
from app.application.shipment_etl_profile import ShipmentEtlProfile
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .fingerprints import FingerprintPorts
from .notes import _enrich_note, _notes_to_product_records, note_fingerprint
from .persistence import ShipmentPersistence, ShipmentWriter, WriteOutcome
from .workbook import ParseNotes


@dataclass(frozen=True)
class ImportPorts:
    resolve_profile: Callable[[ShipmentEtlProfile | None, str | None], ShipmentEtlProfile]
    parse_notes: ParseNotes
    import_products: Callable[[list[dict[str, Any]]], dict[str, Any]]
    shipment_service: Callable[[], ShipmentWriter]


def _admit_notes(
    notes: list[dict[str, Any]],
    *,
    confirm_ledger: bool,
    import_shipments: bool,
    direct: bool,
) -> dict[str, Any] | None:
    ledger_notes = [note for note in notes if note.get("source_kind") == "shipment_ledger"]
    if ledger_notes and not confirm_ledger:
        return {
            "success": False,
            "message": f"检测到 {len(ledger_notes)} 张出货流水分组，生产默认禁止直接入库。请传 confirm_ledger=1 并确认客户归属后再执行。",
            "error_code": "ledger_confirm_required",
            "ledger_note_count": len(ledger_notes),
            "note_count": len(notes),
            "direct": bool(direct),
        }
    if not notes:
        return {"success": False, "message": "没有可导入的单据", "error_code": "no_delivery_notes"}
    non_shipment = [
        note
        for note in notes
        if str(note.get("profile_target") or "shipment").strip() not in {"", "shipment"}
    ]
    if non_shipment and import_shipments:
        targets = sorted(
            {str(note.get("profile_target") or "preview_only") for note in non_shipment}
        )
        return {
            "success": False,
            "message": "识别到非发货单模板（target="
            + ",".join(targets)
            + "）。请改用 preview，或为该 YAML 设置 target: shipment。",
            "error_code": "unsupported_profile_target",
            "profile_ids": sorted(
                {
                    str(note.get("profile_id") or "")
                    for note in non_shipment
                    if note.get("profile_id")
                }
            ),
            "note_count": len(notes),
        }
    return None


class ImportCoordinator:
    def __init__(
        self, ports: ImportPorts, fingerprints: FingerprintPorts, logger: logging.Logger
    ) -> None:
        self._ports = ports
        self._fingerprints = fingerprints
        self._logger = logger

    def _deduplicate(
        self,
        notes: list[dict[str, Any]],
        *,
        tenant: str,
        idempotent: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for note in notes:
            fingerprint = str(note.get("fingerprint") or note_fingerprint(note))
            note["fingerprint"] = fingerprint
            if idempotent and (
                fingerprint in seen or self._fingerprints.contains(tenant, fingerprint)
            ):
                skipped.append(
                    {
                        "fingerprint": fingerprint,
                        "unit_name": note.get("unit_name"),
                        "order_number": note.get("order_number"),
                    }
                )
                continue
            seen.add(fingerprint)
            candidates.append(note)
        return candidates, skipped

    def execute(
        self,
        file_path: str | Path,
        *,
        import_products: bool = True,
        import_shipments: bool = True,
        notes: list[dict[str, Any]] | None = None,
        idempotent: bool = True,
        include_ledger: bool | str = False,
        confirm_ledger: bool = False,
        dry_run: bool = False,
        compensate_on_failure: bool = True,
        unit_name_hint: str | None = None,
        workspace_root: str | Path | None = None,
        profile_id: str | None = None,
        profile: ShipmentEtlProfile | None = None,
        direct: bool = False,
        force_shipment_target: bool = False,
    ) -> dict[str, Any]:
        if direct and not dry_run and not security.direct_execute_allowed():
            return {
                "success": False,
                "message": "无预览直写未开启。请设置 FHD_EXCEL_ETL_ALLOW_DIRECT=1 （或 FHD_SHIPMENT_ETL_ALLOW_DIRECT=1）并确认权限后再执行。",
                "error_code": "direct_execute_denied",
            }
        resolved_profile = self._ports.resolve_profile(profile, profile_id)
        path: Path | None = None
        file_name = "shipment.xlsx"
        if file_path:
            try:
                path = security.resolve_etl_path(
                    file_path, workspace_root=workspace_root, must_exist=notes is None
                )
                file_name = path.name
            except security.ShipmentEtlPathError:
                return {"success": False, "message": "非法文件路径", "error_code": "unsafe_path"}
        if notes is None:
            if path is None:
                return {"success": False, "message": "缺少 file_path", "error_code": "missing_path"}
            parsed = self._ports.parse_notes(
                path,
                include_ledger=include_ledger,
                unit_name_hint=unit_name_hint,
                profile=resolved_profile,
            )
            if not parsed.get("success"):
                return parsed
            notes = [_enrich_note(note) for note in parsed.get("notes") or []]
            file_name = str(parsed.get("file_name") or file_name)
            ledger_available = int(parsed.get("ledger_available_count") or 0)
        else:
            notes = [_enrich_note(note) for note in notes]
            ledger_available = sum(
                1 for note in notes if note.get("source_kind") == "shipment_ledger"
            )
        if direct and force_shipment_target:
            for note in notes:
                if str(note.get("profile_target") or "").strip() in {"", "preview_only"}:
                    note.update(profile_target="shipment", direct_target_promoted=True)
        rejected = _admit_notes(
            notes, confirm_ledger=confirm_ledger, import_shipments=import_shipments, direct=direct
        )
        if rejected is not None:
            return rejected
        tenant = security.tenant_key_for_etl()
        candidates, duplicates = self._deduplicate(notes, tenant=tenant, idempotent=idempotent)
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "direct": bool(direct),
                "message": f"预演：将新建 {len(candidates)} 张，跳过重复 {len(duplicates)} 张；不会写库",
                "file_name": file_name,
                "note_count": len(notes),
                "would_create": len(candidates),
                "would_skip": len(duplicates),
                "notes": candidates,
                "skipped_duplicates": duplicates,
                "ledger_available_count": ledger_available,
                "closed_loop": False,
                "kind": "shipment_delivery_etl",
            }
        product_result: dict[str, Any] = {"success": True, "skipped": True}
        if import_products and candidates:
            product_result = self._ports.import_products(_notes_to_product_records(candidates))
            if not bool(product_result.get("success", True)):
                return {
                    "success": False,
                    "message": f"客户/产品导入失败，已中止发货单写入：{product_result.get('message') or product_result}",
                    "error_code": "product_import_failed",
                    "product_result": product_result,
                    "note_count": len(notes),
                    "closed_loop": False,
                }
        outcome = WriteOutcome()
        if import_shipments and candidates:
            try:
                service = self._ports.shipment_service()
            except RECOVERABLE_ERRORS:
                return {
                    "success": False,
                    "message": "发货单服务不可用",
                    "product_result": product_result,
                }
            outcome = ShipmentPersistence(service, self._fingerprints, self._logger).execute(
                candidates,
                tenant=tenant,
                file_name=file_name,
                idempotent=idempotent,
                compensate_on_failure=compensate_on_failure,
            )
        partial = bool(outcome.failed and outcome.shipment_ids and not compensate_on_failure)
        return {
            "success": outcome.failed == 0 and bool(product_result.get("success", True)),
            "partial_success": partial,
            "compensated": outcome.compensated,
            "compensate_on_failure": compensate_on_failure,
            "compensate_errors": outcome.compensate_errors[:8],
            "fingerprint_errors": outcome.fingerprint_errors[:20],
            "requires_reconciliation": outcome.requires_reconciliation,
            "safe_to_retry": outcome.safe_to_retry(idempotent=idempotent),
            "message": f"送货单闭环完成：新建 {outcome.created}，跳过重复 {len(duplicates)}"
            + (f"，失败 {outcome.failed}" if outcome.failed else "")
            + (f"，已补偿撤销 {len(outcome.compensated)}" if outcome.compensated else "")
            + ("；客户/产品已同步" if import_products and candidates else "")
            + ("（部分成功，未启用补偿）" if partial else ""),
            "file_name": file_name,
            "note_count": len(notes),
            "shipment_created": outcome.created,
            "shipment_failed": outcome.failed,
            "shipment_skipped": len(duplicates),
            "shipment_ids": outcome.shipment_ids,
            "skipped_duplicates": duplicates,
            "product_result": product_result,
            "errors": outcome.errors[:20],
            "closed_loop": True,
            "idempotent": idempotent,
            "dry_run": False,
            "direct": bool(direct),
            "kind": "shipment_delivery_etl",
            "audit": {
                "tenant_key": tenant,
                "file_name": file_name,
                "created": outcome.created,
                "failed": outcome.failed,
                "skipped": len(duplicates),
                "compensated": len(outcome.compensated),
                "direct": bool(direct),
                "force_shipment_target": bool(force_shipment_target),
            },
        }
