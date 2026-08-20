# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.shipment_excel_etl_app_service")


def _notes_to_product_records(
    notes: list[dict[str, _facade().Any]],
) -> list[dict[str, _facade().Any]]:
    records: list[dict[str, _facade().Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for note in notes:
        unit = str(note.get("unit_name") or "").strip()
        for item in note.get("items") or []:
            model = str(item.get("model_number") or "").strip().upper()
            name = str(item.get("product_name") or "").strip()
            key = (unit, model, name)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "unit_name": unit,
                    "product_name": name,
                    "model_number": model,
                    "unit_price": float(item.get("unit_price") or 0),
                }
            )
    return records


def execute_shipment_excel_etl(
    file_path: str | _facade().Path,
    *,
    import_products: bool = True,
    import_shipments: bool = True,
    notes: list[dict[str, _facade().Any]] | None = None,
    idempotent: bool = True,
    include_ledger: bool | str = False,
    confirm_ledger: bool = False,
    dry_run: bool = False,
    compensate_on_failure: bool = True,
    unit_name_hint: str | None = None,
    workspace_root: str | _facade().Path | None = None,
    profile_id: str | None = None,
    profile: _facade().ShipmentEtlProfile | None = None,
    direct: bool = False,
    force_shipment_target: bool = False,
) -> dict[str, _facade().Any]:
    """执行闭环：客户+产品+发货单（可幂等 / dry-run / 失败补偿）。

    生产默认 include_ledger=False；若要导入流水须 confirm_ledger=True。
    任一建单失败且 compensate_on_failure=True 时，取消本批已新建发货单并删除指纹。

    direct=True：无预览直写（需 FHD_EXCEL_ETL_ALLOW_DIRECT=1）。
    force_shipment_target=True：直写时把 preview_only notes 提升为 shipment。
    """
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlPathError,
        direct_execute_allowed,
        resolve_etl_path,
        tenant_key_for_etl,
    )

    if direct and (not dry_run) and (not direct_execute_allowed()):
        return {
            "success": False,
            "message": "无预览直写未开启。请设置 FHD_EXCEL_ETL_ALLOW_DIRECT=1 （或 FHD_SHIPMENT_ETL_ALLOW_DIRECT=1）并确认权限后再执行。",
            "error_code": "direct_execute_denied",
        }
    prof = _facade()._resolve_profile(profile, profile_id)
    path: _facade().Path | None = None
    file_name = "shipment.xlsx"
    if file_path:
        try:
            path = resolve_etl_path(
                file_path, workspace_root=workspace_root, must_exist=notes is None
            )
            file_name = path.name
        except ShipmentEtlPathError:
            return {"success": False, "message": "非法文件路径", "error_code": "unsafe_path"}
    if notes is None:
        if path is None:
            return {"success": False, "message": "缺少 file_path", "error_code": "missing_path"}
        parsed = _facade().parse_delivery_notes(
            path, include_ledger=include_ledger, unit_name_hint=unit_name_hint, profile=prof
        )
        if not parsed.get("success"):
            return parsed
        notes = [_facade()._enrich_note(n) for n in parsed.get("notes") or []]
        file_name = str(parsed.get("file_name") or file_name)
        ledger_available = int(parsed.get("ledger_available_count") or 0)
    else:
        notes = [_facade()._enrich_note(n) for n in notes]
        ledger_available = sum(1 for n in notes if n.get("source_kind") == "shipment_ledger")
    if direct and force_shipment_target:
        for n in notes:
            if str(n.get("profile_target") or "").strip() in {"", "preview_only"}:
                n["profile_target"] = "shipment"
                n["direct_target_promoted"] = True
    ledger_notes = [n for n in notes if n.get("source_kind") == "shipment_ledger"]
    if ledger_notes and (not confirm_ledger):
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
        n
        for n in notes
        if str(n.get("profile_target") or "shipment").strip() not in {"", "shipment"}
    ]
    if non_shipment and import_shipments:
        targets = sorted({str(n.get("profile_target") or "preview_only") for n in non_shipment})
        return {
            "success": False,
            "message": "识别到非发货单模板（target="
            + ",".join(targets)
            + "）。请改用 preview，或为该 YAML 设置 target: shipment。",
            "error_code": "unsupported_profile_target",
            "profile_ids": sorted(
                {str(n.get("profile_id") or "") for n in non_shipment if n.get("profile_id")}
            ),
            "note_count": len(notes),
        }
    tenant_key = tenant_key_for_etl()
    to_import: list[dict[str, _facade().Any]] = []
    skipped_duplicates: list[dict[str, _facade().Any]] = []
    for note in notes:
        fp = str(note.get("fingerprint") or _facade().note_fingerprint(note))
        note["fingerprint"] = fp
        if idempotent and _facade()._is_fingerprint_imported(tenant_key, fp):
            skipped_duplicates.append(
                {
                    "fingerprint": fp,
                    "unit_name": note.get("unit_name"),
                    "order_number": note.get("order_number"),
                }
            )
            continue
        to_import.append(note)
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "direct": bool(direct),
            "message": f"预演：将新建 {len(to_import)} 张，跳过重复 {len(skipped_duplicates)} 张；不会写库",
            "file_name": file_name,
            "note_count": len(notes),
            "would_create": len(to_import),
            "would_skip": len(skipped_duplicates),
            "notes": to_import,
            "skipped_duplicates": skipped_duplicates,
            "ledger_available_count": ledger_available,
            "closed_loop": False,
            "kind": "shipment_delivery_etl",
        }
    product_result: dict[str, _facade().Any] = {"success": True, "skipped": True}
    if import_products and to_import:
        from app.services.tools_workflow_registered import _execute_excel_import_records

        product_result = _execute_excel_import_records(
            _facade()._notes_to_product_records(to_import)
        )
        if not bool(product_result.get("success", True)):
            return {
                "success": False,
                "message": f"客户/产品导入失败，已中止发货单写入：{product_result.get('message') or product_result}",
                "error_code": "product_import_failed",
                "product_result": product_result,
                "note_count": len(notes),
                "closed_loop": False,
            }
    shipment_created = 0
    shipment_failed = 0
    shipment_skipped = len(skipped_duplicates)
    shipment_ids: list[_facade().Any] = []
    created_pairs: list[tuple[_facade().Any, str]] = []
    errors: list[str] = []
    compensated: list[_facade().Any] = []
    compensate_errors: list[str] = []
    if import_shipments and to_import:
        try:
            from app.bootstrap import get_shipment_app_service

            svc = get_shipment_app_service()
        except _facade().RECOVERABLE_ERRORS:
            return {
                "success": False,
                "message": "发货单服务不可用",
                "product_result": product_result,
            }
        for note in to_import:
            unit = str(note.get("unit_name") or "").strip()
            items = list(note.get("items") or [])
            if not unit or not items:
                shipment_failed += 1
                errors.append(f"缺少客户或明细: {note.get('order_number') or note.get('sheet')}")
                break
            result = svc.create_shipment(
                unit_name=unit,
                items_data=items,
                contact_person=str(note.get("contact_person") or ""),
                external_order_number=str(note.get("order_number") or ""),
                order_date=str(note.get("order_date") or ""),
                source_fingerprint=str(note.get("fingerprint") or ""),
                source_kind=str(note.get("source_kind") or ""),
            )
            if result.get("success"):
                shipment_created += 1
                shipment = result.get("shipment") or {}
                sid = shipment.get("id") if isinstance(shipment, dict) else None
                fp = str(note.get("fingerprint") or "")
                if sid is not None:
                    shipment_ids.append(sid)
                    created_pairs.append((sid, fp))
                if idempotent and fp:
                    try:
                        _facade()._record_fingerprint_now(
                            tenant_key,
                            fp,
                            shipment_id=sid,
                            unit_name=unit,
                            order_number=str(note.get("order_number") or ""),
                            file_name=file_name,
                        )
                    except _facade().RECOVERABLE_ERRORS:
                        _facade().logger.warning(
                            "failed to persist etl fingerprint immediately", exc_info=True
                        )
            else:
                shipment_failed += 1
                errors.append(str(result.get("message") or "create_shipment failed"))
                break
        processed = shipment_created + shipment_failed
        if processed < len(to_import) and shipment_failed:
            remaining = len(to_import) - processed
            errors.append(f"因失败中止，另有 {remaining} 张未执行")
            shipment_failed += remaining
        if shipment_failed and created_pairs and compensate_on_failure:
            from app.application.shipment_excel_etl_fingerprint_store import delete_fingerprint

            for sid, fp in created_pairs:
                try:
                    cancel = svc.cancel_shipment(int(sid))
                    if cancel.get("success"):
                        compensated.append(sid)
                    else:
                        deleted = svc.delete_shipment(int(sid))
                        if deleted.get("success"):
                            compensated.append(sid)
                        else:
                            compensate_errors.append(
                                f"补偿失败 shipment_id={sid}: {cancel.get('message') or deleted.get('message')}"
                            )
                except _facade().RECOVERABLE_ERRORS:
                    _facade().logger.warning("shipment compensation failed")
                    compensate_errors.append("补偿失败")
                if fp:
                    try:
                        delete_fingerprint(tenant_key, fp)
                    except _facade().RECOVERABLE_ERRORS:
                        _facade().logger.warning(
                            "failed to delete etl fingerprint on compensate", exc_info=True
                        )
            shipment_created = max(0, shipment_created - len(compensated))
            shipment_ids = [sid for sid in shipment_ids if sid not in set(compensated)]
    ok = shipment_failed == 0 and bool(product_result.get("success", True))
    if not to_import and skipped_duplicates:
        ok = True
    compensated_ok = bool(
        shipment_failed and compensate_on_failure and created_pairs and (not compensate_errors)
    )
    if shipment_failed and compensate_on_failure:
        ok = False
    return {
        "success": ok,
        "partial_success": bool(shipment_failed and shipment_ids and (not compensate_on_failure)),
        "compensated": compensated,
        "compensate_on_failure": compensate_on_failure,
        "compensate_errors": compensate_errors[:8],
        "safe_to_retry": not shipment_ids or compensated_ok or ok,
        "message": f"送货单闭环完成：新建 {shipment_created}，跳过重复 {shipment_skipped}"
        + (f"，失败 {shipment_failed}" if shipment_failed else "")
        + (f"，已补偿撤销 {len(compensated)}" if compensated else "")
        + ("；客户/产品已同步" if import_products and to_import else "")
        + (
            "（部分成功，未启用补偿）"
            if shipment_ids and shipment_failed and (not compensate_on_failure)
            else ""
        ),
        "file_name": file_name,
        "note_count": len(notes),
        "shipment_created": shipment_created,
        "shipment_failed": shipment_failed,
        "shipment_skipped": shipment_skipped,
        "shipment_ids": shipment_ids,
        "skipped_duplicates": skipped_duplicates,
        "product_result": product_result,
        "errors": errors[:20],
        "closed_loop": True,
        "idempotent": idempotent,
        "dry_run": False,
        "direct": bool(direct),
        "kind": "shipment_delivery_etl",
        "audit": {
            "tenant_key": tenant_key,
            "file_name": file_name,
            "created": shipment_created,
            "failed": shipment_failed,
            "skipped": shipment_skipped,
            "compensated": len(compensated),
            "direct": bool(direct),
            "force_shipment_target": bool(force_shipment_target),
        },
    }
