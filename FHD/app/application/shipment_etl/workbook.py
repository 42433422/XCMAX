"""Workbook lifecycle and sheet-selection policy, independent of business writes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.application.shipment_etl_profile import ShipmentEtlProfile
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .notes import _notes_to_product_records


class ParseNotes(Protocol):
    def __call__(
        self,
        file_path: str | Path,
        *,
        min_score: int | None = None,
        include_ledger: bool | str = "auto",
        unit_name_hint: str | None = None,
        profile_id: str | None = None,
        profile: ShipmentEtlProfile | None = None,
        allow_ocr: bool = True,
    ) -> dict[str, Any]: ...


class ClassifySheet(Protocol):
    def __call__(
        self, ws: Any, profile: ShipmentEtlProfile, *, d_score: int, l_score: int
    ) -> str: ...


class DecodeDelivery(Protocol):
    def __call__(
        self, ws: Any, *, fallback_unit: str, profile: ShipmentEtlProfile, allow_llm: bool = True
    ) -> dict[str, Any] | None: ...


class DecodeLedger(Protocol):
    def __call__(
        self, ws: Any, *, fallback_unit: str, profile: ShipmentEtlProfile, allow_llm: bool = True
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class WorkbookPorts:
    profiles: Callable[[ShipmentEtlProfile | None, str | None], list[ShipmentEtlProfile]]
    choose_profile: Callable[
        [Any, list[ShipmentEtlProfile]], tuple[ShipmentEtlProfile, int, int, str]
    ]
    classify: ClassifySheet
    delivery: DecodeDelivery
    ledger: DecodeLedger


@dataclass
class ParsedSheets:
    delivery: list[dict[str, Any]] = field(default_factory=list)
    ledger: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    assists: list[dict[str, Any]] = field(default_factory=list)
    profile_hits: list[dict[str, Any]] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        notes: list[dict[str, Any]],
        profile: ShipmentEtlProfile,
        sheet: str,
        *,
        ledger: bool = False,
        role: str | None = None,
    ) -> None:
        for note in notes:
            note.update(
                profile_id=profile.id,
                profile_kind=profile.kind,
                profile_label=profile.label,
                profile_target=profile.target,
            )
            if role is not None:
                note["sheet_role"] = role
        (self.ledger if ledger else self.delivery).extend(notes)
        assist = notes[0].get("assist")
        if isinstance(assist, dict):
            self.assists.append({"sheet": sheet, "profile_id": profile.id, **assist})

    def select(self, include_ledger: bool | str) -> tuple[list[dict[str, Any]], bool | str]:
        mode = include_ledger
        if isinstance(mode, str):
            value = mode.strip().lower()
            mode = (
                True
                if value in {"1", "true", "yes", "on"}
                else False
                if value in {"0", "false", "no", "off"}
                else "auto"
            )
        if mode is True:
            return self.delivery + self.ledger, mode
        if mode is False or self.delivery:
            for note in self.ledger:
                skipped = {
                    "sheet": note.get("sheet"),
                    "score": note.get("score"),
                    "reason": "ledger_disabled"
                    if mode is False
                    else "ledger_skipped_auto_has_delivery",
                }
                if mode is not False:
                    skipped["ledger_groups"] = 1
                self.skipped.append(skipped)
            return self.delivery, mode
        return self.ledger, mode


class WorkbookReader:
    def __init__(self, ports: WorkbookPorts, logger: logging.Logger) -> None:
        self._ports = ports
        self._logger = logger

    def _delivery(
        self,
        ws: Any,
        profile: ShipmentEtlProfile,
        fallback: str,
        parsed: ParsedSheets,
        *,
        role: str | None = None,
    ) -> bool:
        note = self._ports.delivery(ws, fallback_unit=fallback, profile=profile, allow_llm=True)
        if note:
            parsed.add([note], profile, ws.title, role=role)
            return True
        return False

    def _ledger(
        self, ws: Any, profile: ShipmentEtlProfile, fallback: str, parsed: ParsedSheets
    ) -> bool:
        notes = self._ports.ledger(ws, fallback_unit=fallback, profile=profile, allow_llm=True)
        if notes:
            parsed.add(notes, profile, ws.title, ledger=True)
            return True
        return False

    def _read_sheet(
        self,
        ws: Any,
        profiles: list[ShipmentEtlProfile],
        fallback: str,
        min_score: int | None,
        parsed: ParsedSheets,
    ) -> None:
        profile, delivery_score, ledger_score, prefer = self._ports.choose_profile(ws, profiles)
        role = self._ports.classify(ws, profile, d_score=delivery_score, l_score=ledger_score)
        if role == "ledger":
            prefer = "shipment_ledger"
        elif role == "delivery":
            prefer = "delivery_note"
        score_floor = int(min_score if min_score is not None else profile.delivery_min_score)
        parsed.profile_hits.append(
            {
                "sheet": ws.title,
                "profile_id": profile.id,
                "kind": profile.kind,
                "label": profile.label,
                "delivery_score": delivery_score,
                "ledger_score": ledger_score,
                "prefer": prefer,
                "role": role,
            }
        )
        parsed.roles.append({"sheet": ws.title, "role": role, "prefer": prefer})
        if role == "ignore":
            parsed.skipped.append(
                {
                    "sheet": ws.title,
                    "score": max(delivery_score, ledger_score),
                    "reason": "sheet_ignored_mixed_workbook",
                    "profile_id": profile.id,
                    "role": role,
                }
            )
            return
        delivery_gate = 24 if role in {"delivery", "unknown"} else 40
        if prefer == "delivery_note" and delivery_score >= delivery_gate:
            if self._delivery(ws, profile, fallback, parsed, role=role):
                return
            if delivery_score >= score_floor:
                parsed.skipped.append(
                    {
                        "sheet": ws.title,
                        "score": delivery_score,
                        "reason": "delivery_parse_failed",
                        "profile_id": profile.id,
                        "role": role,
                    }
                )
                return
        if prefer == "shipment_ledger" and profile.has_ledger and ledger_score >= 40:
            if self._ledger(ws, profile, fallback, parsed) or self._delivery(
                ws, profile, fallback, parsed
            ):
                return
            if ledger_score >= 50:
                parsed.skipped.append(
                    {
                        "sheet": ws.title,
                        "score": ledger_score,
                        "reason": "ledger_empty",
                        "profile_id": profile.id,
                    }
                )
                return
        if profile.has_ledger and ledger_score >= 40 and prefer != "shipment_ledger":
            if self._ledger(ws, profile, fallback, parsed):
                return
            if ledger_score >= 50:
                parsed.skipped.append(
                    {
                        "sheet": ws.title,
                        "score": ledger_score,
                        "reason": "ledger_empty",
                        "profile_id": profile.id,
                    }
                )
                return
        elif self._delivery(ws, profile, fallback, parsed):
            return
        parsed.skipped.append(
            {
                "sheet": ws.title,
                "score": max(delivery_score, ledger_score),
                "reason": "not_matched",
                "profile_id": profile.id,
            }
        )

    def parse(
        self,
        file_path: str | Path,
        *,
        min_score: int | None = None,
        include_ledger: bool | str = "auto",
        unit_name_hint: str | None = None,
        profile_id: str | None = None,
        profile: ShipmentEtlProfile | None = None,
        allow_ocr: bool = True,
    ) -> dict[str, Any]:
        from app.application.shipment_excel_etl_security import (
            ShipmentEtlPathError,
            open_etl_input_file,
            resolve_etl_path,
        )

        try:
            path = resolve_etl_path(file_path, must_exist=False)
        except ShipmentEtlPathError:
            return {
                "success": False,
                "message": "非法文件路径",
                "notes": [],
                "error_code": "unsafe_path",
            }
        if allow_ocr:
            try:
                from app.application.shipment_excel_etl_ocr import is_ocr_source, parse_ocr_document

                if is_ocr_source(path):
                    return parse_ocr_document(
                        path,
                        include_ledger=include_ledger,
                        unit_name_hint=unit_name_hint,
                        profile_id=profile_id,
                    )
            except RECOVERABLE_ERRORS:
                self._logger.debug("ocr auto-route skipped", exc_info=True)
        profiles = self._ports.profiles(profile, profile_id)
        try:
            from openpyxl import load_workbook
        except ImportError:
            return {"success": False, "message": "缺少 openpyxl，无法解析 Excel", "notes": []}
        try:
            with open_etl_input_file(path) as source_file:
                workbook = load_workbook(source_file, data_only=True)
                try:
                    fallback = (unit_name_hint or path.stem).strip() or path.stem
                    parsed = ParsedSheets()
                    for sheet in workbook.worksheets:
                        self._read_sheet(sheet, profiles, fallback, min_score, parsed)
                    notes, mode = parsed.select(include_ledger)
                    delivery_count = sum(
                        1 for note in notes if note.get("source_kind") == "delivery_note"
                    )
                    ledger_count = sum(
                        1 for note in notes if note.get("source_kind") == "shipment_ledger"
                    )
                    used_profiles = sorted(
                        {
                            str(note.get("profile_id") or "")
                            for note in notes
                            if note.get("profile_id")
                        }
                    )
                    result_profile = (
                        used_profiles[0]
                        if len(used_profiles) == 1
                        else profiles[0].id
                        if len(profiles) == 1
                        else "auto"
                    )
                    return {
                        "success": True,
                        "file_path": str(path),
                        "file_name": path.name,
                        "profile_id": result_profile,
                        "profile_ids": used_profiles,
                        "profiles_available": [p.id for p in profiles],
                        "profile_hits": parsed.profile_hits,
                        "sheet_roles": parsed.roles,
                        "mixed_workbook": len({r.get("role") for r in parsed.roles}) > 1,
                        "note_count": len(notes),
                        "delivery_note_count": delivery_count,
                        "ledger_note_count": ledger_count,
                        "ledger_available_count": len(parsed.ledger),
                        "include_ledger_mode": mode if mode in (True, False) else "auto",
                        "notes": notes,
                        "skipped_sheets": parsed.skipped,
                        "assist": {
                            "used_llm": any(
                                bool(a.get("used_llm") and a.get("ok")) for a in parsed.assists
                            ),
                            "sheets": parsed.assists,
                        },
                        "message": (
                            f"识别到 {len(notes)} 张单据（主表 {delivery_count} / 流水分组 {ledger_count}）"
                            + (f"；profile={','.join(used_profiles)}" if used_profiles else "")
                        )
                        if notes
                        else "未识别到可匹配的单据模板（可自定义 YAML profile）",
                    }
                finally:
                    workbook.close()
        except FileNotFoundError:
            return {"success": False, "message": "文件不存在", "notes": []}
        except ShipmentEtlPathError:
            return {
                "success": False,
                "message": "非法文件路径",
                "notes": [],
                "error_code": "unsafe_path",
            }
        except RECOVERABLE_ERRORS:
            return {"success": False, "message": "无法读取 Excel 文件", "notes": []}


def preview(
    file_path: str | Path,
    *,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
    workspace_root: str | Path | None = None,
    profile_id: str | None = None,
    profile: ShipmentEtlProfile | None = None,
    parse_notes: ParseNotes,
    contains: Callable[[str, str], bool],
) -> dict[str, Any]:
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlPathError,
        resolve_etl_path,
        tenant_key_for_etl,
    )

    try:
        path = resolve_etl_path(file_path, workspace_root=workspace_root, must_exist=True)
    except ShipmentEtlPathError:
        return {
            "success": False,
            "message": "非法文件路径",
            "error_code": "unsafe_path",
            "notes": [],
        }
    parsed = parse_notes(
        path,
        include_ledger=include_ledger,
        unit_name_hint=unit_name_hint,
        profile_id=profile_id,
        profile=profile,
    )
    if not parsed.get("success"):
        return parsed
    notes = parsed.get("notes") or []
    tenant_key = tenant_key_for_etl()
    for note in notes:
        fingerprint = str(note.get("fingerprint") or "")
        note["already_imported"] = bool(fingerprint and contains(tenant_key, fingerprint))
    ledger_available = int(parsed.get("ledger_available_count") or 0)
    return {
        **parsed,
        "preview": True,
        "product_records": _notes_to_product_records(notes),
        "confirm_required": True,
        "duplicate_note_count": sum(1 for note in notes if note.get("already_imported")),
        "ledger_risk": ledger_available > 0 and int(parsed.get("ledger_note_count") or 0) == 0,
        "ledger_available_count": ledger_available,
        "message": str(parsed.get("message") or "")
        + ("。确认后将写入客户、产品与发货单。" if notes else ""),
    }
