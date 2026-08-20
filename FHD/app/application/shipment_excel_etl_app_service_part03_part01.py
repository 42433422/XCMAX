# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.shipment_excel_etl_app_service")


def parse_delivery_notes(
    file_path: str | _facade().Path,
    *,
    min_score: int | None = None,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
    profile_id: str | None = None,
    profile: _facade().ShipmentEtlProfile | None = None,
    allow_ocr: bool = True,
) -> dict[str, _facade().Any]:
    """解析工作簿：多 profile 竞分识别（通用表/流水/自定义 YAML）。

    include_ledger:
    - True: 主表 + 流水都收
    - False: 只收主表
    - "auto": 有主表时忽略同簿流水；无主表时再解析流水

    若路径是图片/PDF 且 allow_ocr=True，先走 OCR 桥接再解析。
    """
    from app.application.shipment_excel_etl_security import ShipmentEtlPathError, resolve_etl_path

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

            if path.is_file() and is_ocr_source(path):
                return parse_ocr_document(
                    path,
                    include_ledger=include_ledger,
                    unit_name_hint=unit_name_hint,
                    profile_id=profile_id,
                )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("ocr auto-route skipped", exc_info=True)
    profiles = _facade()._profiles_for_parse(profile, profile_id)
    if not path.is_file():
        return {"success": False, "message": "文件不存在", "notes": []}
    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"success": False, "message": "缺少 openpyxl，无法解析 Excel", "notes": []}
    try:
        wb = load_workbook(str(path), data_only=True)
    except _facade().RECOVERABLE_ERRORS:
        return {"success": False, "message": "无法读取 Excel 文件", "notes": []}
    fallback_unit = (unit_name_hint or path.stem).strip() or path.stem
    delivery_notes: list[dict[str, _facade().Any]] = []
    ledger_notes: list[dict[str, _facade().Any]] = []
    skipped: list[dict[str, _facade().Any]] = []
    assist_summaries: list[dict[str, _facade().Any]] = []
    profile_hits: list[dict[str, _facade().Any]] = []
    sheet_roles: list[dict[str, _facade().Any]] = []
    try:
        for ws in wb.worksheets:
            prof, d_score, l_score, prefer = _facade()._pick_best_profile_for_sheet(ws, profiles)
            role = _facade()._classify_sheet_role(ws, prof, d_score=d_score, l_score=l_score)
            if role == "ledger":
                prefer = "shipment_ledger"
            elif role == "delivery":
                prefer = "delivery_note"
            score_floor = int(min_score if min_score is not None else prof.delivery_min_score)
            hit = {
                "sheet": ws.title,
                "profile_id": prof.id,
                "kind": prof.kind,
                "label": prof.label,
                "delivery_score": d_score,
                "ledger_score": l_score,
                "prefer": prefer,
                "role": role,
            }
            profile_hits.append(hit)
            sheet_roles.append({"sheet": ws.title, "role": role, "prefer": prefer})
            if role == "ignore":
                skipped.append(
                    {
                        "sheet": ws.title,
                        "score": max(d_score, l_score),
                        "reason": "sheet_ignored_mixed_workbook",
                        "profile_id": prof.id,
                        "role": role,
                    }
                )
                continue
            delivery_gate = 24 if role in {"delivery", "unknown"} else 40
            if prefer == "delivery_note" and d_score >= delivery_gate:
                note = _facade()._parse_delivery_sheet(
                    ws, fallback_unit=fallback_unit, profile=prof, allow_llm=True
                )
                if note:
                    note["profile_id"] = prof.id
                    note["profile_kind"] = prof.kind
                    note["profile_label"] = prof.label
                    note["profile_target"] = prof.target
                    note["sheet_role"] = role
                    delivery_notes.append(note)
                    if isinstance(note.get("assist"), dict):
                        assist_summaries.append(
                            {
                                "sheet": ws.title,
                                "profile_id": prof.id,
                                **dict(note.get("assist") or {}),
                            }
                        )
                    continue
                if d_score >= score_floor:
                    skipped.append(
                        {
                            "sheet": ws.title,
                            "score": d_score,
                            "reason": "delivery_parse_failed",
                            "profile_id": prof.id,
                            "role": role,
                        }
                    )
                    continue
            if prefer == "shipment_ledger" and prof.has_ledger and (l_score >= 40):
                parsed_ledger = _facade()._parse_ledger_sheet(
                    ws, fallback_unit=fallback_unit, profile=prof, allow_llm=True
                )
                if parsed_ledger:
                    for n in parsed_ledger:
                        n["profile_id"] = prof.id
                        n["profile_kind"] = prof.kind
                        n["profile_label"] = prof.label
                        n["profile_target"] = prof.target
                    ledger_notes.extend(parsed_ledger)
                    assist = (parsed_ledger[0] or {}).get("assist")
                    if isinstance(assist, dict):
                        assist_summaries.append(
                            {"sheet": ws.title, "profile_id": prof.id, **assist}
                        )
                    continue
                note = _facade()._parse_delivery_sheet(
                    ws, fallback_unit=fallback_unit, profile=prof, allow_llm=True
                )
                if note:
                    note["profile_id"] = prof.id
                    note["profile_kind"] = prof.kind
                    note["profile_label"] = prof.label
                    note["profile_target"] = prof.target
                    delivery_notes.append(note)
                    if isinstance(note.get("assist"), dict):
                        assist_summaries.append(
                            {
                                "sheet": ws.title,
                                "profile_id": prof.id,
                                **dict(note.get("assist") or {}),
                            }
                        )
                    continue
                if l_score >= 50:
                    skipped.append(
                        {
                            "sheet": ws.title,
                            "score": l_score,
                            "reason": "ledger_empty",
                            "profile_id": prof.id,
                        }
                    )
                    continue
            if prof.has_ledger and l_score >= 40 and (prefer != "shipment_ledger"):
                parsed_ledger = _facade()._parse_ledger_sheet(
                    ws, fallback_unit=fallback_unit, profile=prof, allow_llm=True
                )
                if parsed_ledger:
                    for n in parsed_ledger:
                        n["profile_id"] = prof.id
                        n["profile_kind"] = prof.kind
                        n["profile_label"] = prof.label
                        n["profile_target"] = prof.target
                    ledger_notes.extend(parsed_ledger)
                    assist = (parsed_ledger[0] or {}).get("assist")
                    if isinstance(assist, dict):
                        assist_summaries.append(
                            {"sheet": ws.title, "profile_id": prof.id, **assist}
                        )
                elif l_score >= 50:
                    skipped.append(
                        {
                            "sheet": ws.title,
                            "score": l_score,
                            "reason": "ledger_empty",
                            "profile_id": prof.id,
                        }
                    )
                else:
                    skipped.append(
                        {
                            "sheet": ws.title,
                            "score": max(d_score, l_score),
                            "reason": "not_matched",
                            "profile_id": prof.id,
                        }
                    )
            else:
                note = _facade()._parse_delivery_sheet(
                    ws, fallback_unit=fallback_unit, profile=prof, allow_llm=True
                )
                if note:
                    note["profile_id"] = prof.id
                    note["profile_kind"] = prof.kind
                    note["profile_label"] = prof.label
                    note["profile_target"] = prof.target
                    delivery_notes.append(note)
                    if isinstance(note.get("assist"), dict):
                        assist_summaries.append(
                            {
                                "sheet": ws.title,
                                "profile_id": prof.id,
                                **dict(note.get("assist") or {}),
                            }
                        )
                else:
                    skipped.append(
                        {
                            "sheet": ws.title,
                            "score": max(d_score, l_score),
                            "reason": "not_matched",
                            "profile_id": prof.id,
                        }
                    )
    finally:
        wb.close()
    mode = include_ledger
    if isinstance(mode, str):
        mode_l = mode.strip().lower()
        if mode_l in {"1", "true", "yes", "on"}:
            mode = True
        elif mode_l in {"0", "false", "no", "off"}:
            mode = False
        else:
            mode = "auto"
    if mode is True:
        notes = delivery_notes + ledger_notes
    elif mode is False:
        notes = delivery_notes
        for n in ledger_notes:
            skipped.append(
                {"sheet": n.get("sheet"), "score": n.get("score"), "reason": "ledger_disabled"}
            )
    elif delivery_notes:
        notes = delivery_notes
        for n in ledger_notes:
            skipped.append(
                {
                    "sheet": n.get("sheet"),
                    "score": n.get("score"),
                    "reason": "ledger_skipped_auto_has_delivery",
                    "ledger_groups": 1,
                }
            )
    else:
        notes = ledger_notes
    delivery_count = sum(1 for n in notes if n.get("source_kind") == "delivery_note")
    ledger_count = sum(1 for n in notes if n.get("source_kind") == "shipment_ledger")
    used_llm = any(bool(a.get("used_llm") and a.get("ok")) for a in assist_summaries)
    used_profile_ids = sorted(
        {str(n.get("profile_id") or "") for n in notes if n.get("profile_id")}
    )
    if len(used_profile_ids) == 1:
        result_profile_id = used_profile_ids[0]
    elif len(profiles) == 1:
        result_profile_id = profiles[0].id
    else:
        result_profile_id = "auto"
    return {
        "success": True,
        "file_path": str(path),
        "file_name": path.name,
        "profile_id": result_profile_id,
        "profile_ids": used_profile_ids,
        "profiles_available": [p.id for p in profiles],
        "profile_hits": profile_hits,
        "sheet_roles": sheet_roles,
        "mixed_workbook": len({r.get("role") for r in sheet_roles}) > 1,
        "note_count": len(notes),
        "delivery_note_count": delivery_count,
        "ledger_note_count": ledger_count,
        "ledger_available_count": len(ledger_notes),
        "include_ledger_mode": mode if mode in (True, False) else "auto",
        "notes": notes,
        "skipped_sheets": skipped,
        "assist": {"used_llm": used_llm, "sheets": assist_summaries},
        "message": f"识别到 {len(notes)} 张单据（主表 {delivery_count} / 流水分组 {ledger_count}）"
        + (f"；profile={','.join(used_profile_ids)}" if used_profile_ids else "")
        if notes
        else "未识别到可匹配的单据模板（可自定义 YAML profile）",
    }


def preview_shipment_excel_etl(
    file_path: str | _facade().Path,
    *,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
    workspace_root: str | _facade().Path | None = None,
    profile_id: str | None = None,
    profile: _facade().ShipmentEtlProfile | None = None,
) -> dict[str, _facade().Any]:
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
    parsed = _facade().parse_delivery_notes(
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
        fp = str(note.get("fingerprint") or "")
        note["already_imported"] = bool(fp and _facade()._is_fingerprint_imported(tenant_key, fp))
    ledger_available = int(parsed.get("ledger_available_count") or 0)
    return {
        **parsed,
        "preview": True,
        "product_records": _facade()._notes_to_product_records(notes),
        "confirm_required": True,
        "duplicate_note_count": sum(1 for n in notes if n.get("already_imported")),
        "ledger_risk": ledger_available > 0 and int(parsed.get("ledger_note_count") or 0) == 0,
        "ledger_available_count": ledger_available,
        "message": str(parsed.get("message") or "")
        + ("。确认后将写入客户、产品与发货单。" if notes else ""),
    }
