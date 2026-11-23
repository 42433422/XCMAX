"""Write and read back the knowledge and template assets of one owned ELT import."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.db.models.elt import EltUpload
from app.db.session import get_db
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS

# ELT 目标类型 → 模板库业务范围（与前端 templateScopeRules 的 scope key 一致）。
_TEMPLATE_SCOPE_BY_TARGET = {
    "shipment_records": "shipmentRecords",
    "customer_products": "products",
    "products": "products",
    "customers": "customers",
    "materials": "materials",
}


def _auxiliary_upload(data: dict[str, Any], owner_id: int) -> dict[str, str]:
    """Read the original owned upload, including its bytes, before auxiliary writes."""
    from app.application.elt.service_support import MAX_FILE_BYTES
    from app.application.shipment_excel_elt_security import open_elt_input_file

    tenant = tenant_id_for_write()
    with get_db() as db:
        upload = (
            db.query(EltUpload)
            .filter(
                EltUpload.id == str(data.get("upload_id") or ""),
                EltUpload.owner_user_id == owner_id,
                EltUpload.tenant_id == tenant,
            )
            .first()
        )
        if upload is None or not upload.storage_path:
            raise ValueError("auxiliary_upload_unavailable")
        source = {
            "storage_path": str(upload.storage_path),
            "file_name": str(upload.file_name or "elt-import"),
            "sha256": str(upload.sha256 or ""),
        }
        expected_size = upload.size_bytes
    if not source["sha256"] or source["sha256"] != data.get("file_sha256"):
        raise ValueError("auxiliary_source_changed")
    digest, size = hashlib.sha256(), 0
    with open_elt_input_file(Path(source["storage_path"]), owner_user_id=owner_id) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError("auxiliary_source_changed")
            digest.update(chunk)
    if size != expected_size or digest.hexdigest() != source["sha256"]:
        raise ValueError("auxiliary_source_changed")
    return source


def _knowledge_receipt(data: dict[str, Any], owner_id: int) -> dict[str, Any]:
    """Keep the writer's receipt and bind it to the committed document and chunks."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.dataset_rag.document_lifecycle import (
        _snapshot_document,
        agent_ingest_read_repository,
    )
    from app.application.elt.auto_ingest_service import (
        _extract_text,
        get_auto_ingest_service,
    )

    writer_started = False
    writer_receipt: dict[str, Any] | None = None
    try:
        tenant = tenant_id_for_write()
        source = _auxiliary_upload(data, owner_id)
        text = _extract_text(Path(source["storage_path"]), owned_upload_user_id=owner_id)
        if not text.strip():
            return {"action": "skip", "reason": "empty_document"}
        writer_started = True
        receipt = get_auto_ingest_service()._ingest_knowledge(
            text=text,
            source_key=source["file_name"],
            run_id=str(data.get("id") or ""),
            owner_user_id=owner_id,
            content_hash=source["sha256"],
            note="",
            tenant_id=tenant,
        )
        if not isinstance(receipt, dict) or not receipt:
            return {"action": "unknown", "reason": "knowledge_receipt_unavailable"}
        writer_receipt = receipt
        if receipt.get("action") not in {"new", "update", "skip"}:
            return receipt
        repository = agent_ingest_read_repository()
        snapshot = repository.read_committed_dataset("office-docking")
        if snapshot is None:
            raise ValueError("knowledge_document_unavailable")
        document, chunks = _snapshot_document(snapshot, str(receipt.get("match_ref") or ""))
        return {
            **receipt,
            "evidence": {
                "dataset_id": "office-docking",
                "store_sha256": canonical_hash(str(repository.storage_path)),
                "document_id": document["document_id"],
                "version": document["version"],
                "raw_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text_sha256": hashlib.sha256(text.strip().encode("utf-8")).hexdigest(),
                "source_key": source["file_name"],
                "document_sha256": canonical_hash(document),
                "chunks_sha256": canonical_hash(chunks),
                "chunk_count": len(chunks),
            },
        }
    except RECOVERABLE_ERRORS as exc:
        return {
            "action": "unknown" if writer_started else "error",
            "reason": str(exc)[:200],
            **({"writer_receipt": writer_receipt} if writer_receipt is not None else {}),
        }


def _grid_preview(file_path: str, max_rows: int = 12) -> dict[str, Any]:
    """读取切分后的模板文件前若干行，作为模板库卡片的真实网格预览。"""
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(file_path, read_only=True, data_only=True)
    except RECOVERABLE_ERRORS:
        return {"rows": []}
    try:
        worksheet = workbook.active
        if worksheet is None:
            return {"rows": []}
        rows: list[list[dict[str, Any]]] = []
        for row_number, values in enumerate(
            worksheet.iter_rows(max_row=min(worksheet.max_row or 1, max_rows), values_only=True),
            start=1,
        ):
            cells = [
                {
                    "row": row_number,
                    "col": column,
                    "text": "" if value in (None, "") else str(value).strip(),
                    "rowspan": 1,
                    "colspan": 1,
                }
                for column, value in enumerate(values, start=1)
            ]
            rows.append(cells)
        return {"rows": rows, "sheet_name": str(worksheet.title or "")}
    finally:
        workbook.close()


def _template_name(meta: dict[str, Any], stem: str, target_type: str, *, primary: bool) -> str:
    """按预演切出的区段生成模板名，而不是用整份文件名。"""
    sheet = str(meta.get("sheet") or "").strip() or "送货单"
    customer = str(meta.get("customer_name") or "").strip()
    if target_type == "shipment_records" and primary and customer:
        return f"{customer}-发货单版式"
    title = str(meta.get("title") or "").strip()
    return f"{stem}-{title or sheet}"


def _template_scope(region: dict[str, Any], meta: dict[str, Any], target_type: str) -> str:
    """按区段内容判断业务范围，而不是整次预演的目标类型。"""
    if region.get("status") == "selected" or region.get("headerless"):
        return _TEMPLATE_SCOPE_BY_TARGET.get(target_type, "")
    headers = " ".join(str(item) for item in meta.get("headers") or [])
    text = f"{meta.get('title') or ''} {headers}"
    if "报价" in text or ("单价" in text and "型号" in text):
        return "products"
    return ""


def _safe_file_component(value: str) -> str:
    text = "".join(char if char.isalnum() or char in {" ", "-", "_"} else "-" for char in value)
    return text.strip(" .-")[:80] or "elt-template"


def _template_target_type(data: dict[str, Any]) -> str:
    """模板登记必须用真实注册过的目标类型；auto/abnormal 一律按通用表处理。"""
    target_type = str(data.get("target_type") or "").strip()
    if target_type in {"", "auto", "abnormal"}:
        return "dynamic_table"
    return target_type


def _template_payload(
    name: str, key: str, kind: str, path: str, sheet: str, headers: list, **analysis: Any
) -> dict:
    return {
        "template_name": name,
        "template_key": key,
        "template_type": kind,
        "original_file_path": path,
        "analyzed_data": {
            "category": "excel",
            **analysis,
            "fields": [{"label": header, "value": "", "type": "dynamic"} for header in headers],
            "preview_data": {
                "sample_rows": [],
                "sheet_name": sheet,
                "grid_preview": _grid_preview(path),
            },
        },
    }


def _template_owner_dir(owner_id: int) -> Path:
    from app.utils.path_io.path_utils import get_app_data_dir

    return (
        Path(get_app_data_dir()).resolve()
        / "tenants"
        / str(tenant_id_for_write())
        / "template_library"
        / str(owner_id)
    )


def _template_readback(
    template_id: Any,
    key: str,
    target: dict[str, Any],
    owner_id: int,
    *,
    action: str,
    file_sha256: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Bind one new or reused template to its exact tenant row and owned file."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash
    from app.application.elt.service_support import load_json
    from app.application.template_mutation_receipt import _db_id, _file_sha, _row

    tenant = tenant_id_for_write()
    with get_db() as db:
        row = _row(db, _db_id(template_id), tenant)
        if row is None or not row["is_active"] or row["template_key"] != key:
            raise ValueError("template_record_unavailable")
        snapshot = dict(row)
    path = str(snapshot["original_file_path"] or "")
    if not Path(path).is_relative_to(_template_owner_dir(owner_id)):
        raise ValueError("template_owner_mismatch")
    analysis = load_json(snapshot["analyzed_data"], {})
    if action == "new" and (not run_id or analysis.get("elt_run_id") != run_id):
        raise ValueError("template_run_mismatch")
    if "region_id" in target:
        if analysis.get("elt_source") != {
            "file_sha256": file_sha256,
            "region_id": target["region_id"],
        }:
            raise ValueError("template_source_mismatch")
    else:
        fields = analysis.get("fields")
        if (
            not isinstance(fields, list)
            or [field.get("label") for field in fields if isinstance(field, dict)]
            != target["headers"]
        ):
            raise ValueError("template_headers_mismatch")
    return {
        "template_id": int(snapshot["id"]),
        "template_key": snapshot["template_key"],
        "template_name": snapshot["template_name"],
        "row_sha256": canonical_hash(snapshot),
        "file_sha256": _file_sha(path, str(tenant)),
        "target": target,
        "action": action,
    }


def _template_candidate(templates: list[dict], key: str, owner_id: int) -> dict | None:
    matches = [
        item
        for item in templates
        if item.get("template_key") == key
        and Path(str(item.get("file_path") or item.get("path") or "")).is_relative_to(
            _template_owner_dir(owner_id)
        )
    ]
    if len(matches) > 1:
        raise ValueError("template_key_ambiguous")
    return matches[0] if matches else None


def _template_batch_receipt(items: list[dict], failures: list[dict]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "action": "new" if any(item["action"] == "new" for item in items) else "skip",
        "names": [item["template_name"] for item in items],
        "template_ids": [item["template_id"] for item in items],
        "evidence": {"items": items},
    }
    if failures:
        receipt.update(action="error", reason=failures[0]["reason"], failed_targets=failures)
    elif receipt["action"] == "skip":
        receipt["reason"] = "duplicate_name" if items else "no_region"
    return receipt


def _register_header_template(data: dict[str, Any], owner_id: int) -> dict[str, Any]:
    """Register only dynamic tables actually written by this run, with exact headers."""
    from app.application.elt.service_support import load_json
    from app.application.shipment_excel_elt_security import open_elt_output_file
    from app.application.template_app_service import get_template_app_service
    from app.db.models.elt import EltDynamicRow, EltDynamicTable

    items: list[dict] = []
    failures: list[dict] = []
    try:
        tenant = tenant_id_for_write()
        with get_db() as db:
            tables = (
                db.query(EltDynamicTable)
                .join(EltDynamicRow, EltDynamicRow.table_id == EltDynamicTable.id)
                .filter(
                    EltDynamicTable.tenant_id == tenant,
                    EltDynamicTable.owner_user_id == owner_id,
                    EltDynamicRow.tenant_id == tenant,
                    EltDynamicRow.owner_user_id == owner_id,
                    EltDynamicRow.run_id == str(data.get("id") or ""),
                )
                .distinct()
                .order_by(EltDynamicTable.id.asc())
                .all()
            )
            specs = [
                (table.id, str(table.name or "").strip(), load_json(table.headers_json, []))
                for table in tables
            ]
        if not specs:
            return _template_batch_receipt([], [])
        service = get_template_app_service()
        templates = [
            item
            for item in service.get_templates(tenant_id=tenant).get("templates") or []
            if item.get("source") == "db"
        ]
        existing_names = {str(item.get("name") or "") for item in templates}
        out_dir = _template_owner_dir(owner_id)
        for table_id, name, headers in specs:
            target = {"table_id": table_id, "headers": headers}
            try:
                if (
                    not name
                    or not isinstance(headers, list)
                    or not headers
                    or any(not isinstance(header, str) or not header for header in headers)
                ):
                    raise ValueError("template_headers_unavailable")
                digest = hashlib.sha1("|".join(headers).encode("utf-8")).hexdigest()[:12]
                key = f"ELT_{digest}"
                existing = _template_candidate(templates, key, owner_id)
                if existing is not None:
                    proof = _template_readback(
                        existing.get("db_id") or existing.get("id"),
                        key,
                        target,
                        owner_id,
                        action="skip",
                    )
                else:
                    from openpyxl import Workbook

                    base, suffix = name, 2
                    while name in existing_names:
                        name = f"{base}-{suffix}"
                        suffix += 1
                    out_dir.mkdir(parents=True, exist_ok=True)
                    destination = out_dir / (
                        f"{_safe_file_component(name)}-{digest}-{str(data.get('id') or '')[:8]}.xlsx"
                    )
                    if destination.exists():
                        raise ValueError("template_file_already_exists")
                    workbook = Workbook()
                    try:
                        sheet = workbook.active
                        assert sheet is not None
                        sheet.title = name[:31] or "Sheet1"
                        sheet.append(headers)
                        with open_elt_output_file(destination) as stream:
                            workbook.save(stream)
                    finally:
                        workbook.close()
                    result = service.save_template(
                        _template_payload(
                            name,
                            key,
                            "Excel",
                            str(destination),
                            name,
                            headers,
                            elt_run_id=str(data.get("id") or ""),
                        )
                    )
                    if not result.get("success"):
                        raise ValueError(str(result.get("message") or "save_failed"))
                    proof = _template_readback(
                        result.get("id"),
                        key,
                        target,
                        owner_id,
                        action="new",
                        run_id=str(data.get("id") or ""),
                    )
                    templates.append(
                        {
                            "id": proof["template_id"],
                            "template_key": key,
                            "file_path": str(destination),
                        }
                    )
                    existing_names.add(name)
                items.append(proof)
            except RECOVERABLE_ERRORS as exc:
                failures.append({"target": target, "reason": str(exc)[:200]})
    except RECOVERABLE_ERRORS as exc:
        failures.append({"target": {}, "reason": str(exc)[:200]})
    return _template_batch_receipt(items, failures)


def _template_receipt(data: dict[str, Any], owner_id: int) -> dict[str, Any]:
    """Register every preview region; partial failure never becomes a successful skip."""
    from app.application import template_ai
    from app.application.elt.shipment_template_extractor import extract_region_template
    from app.application.template_app_service import get_template_app_service

    items: list[dict] = []
    failures: list[dict] = []
    try:
        source = _auxiliary_upload(data, owner_id)
        regions = (data.get("source_features") or {}).get("regions") or []
        if not isinstance(regions, list) or any(
            not isinstance(region, dict) or not str(region.get("id") or "").strip()
            for region in regions
        ):
            raise ValueError("template_regions_unavailable")
        if not regions:
            return _register_header_template(data, owner_id)
        if len({str(region["id"]) for region in regions}) != len(regions):
            raise ValueError("template_regions_ambiguous")
        tenant = tenant_id_for_write()
        target_type = str(data.get("target_type") or "")
        service = get_template_app_service()
        templates = [
            item
            for item in service.get_templates(tenant_id=tenant).get("templates") or []
            if item.get("source") == "db"
        ]
        existing_names = {str(item.get("name") or "") for item in templates}
        stem = Path(source["file_name"]).stem.strip() or "ELT 模板"
        out_dir = _template_owner_dir(owner_id)
        for region in regions:
            target = {"region_id": str(region["id"])}
            try:
                key = (
                    "ELT_"
                    + hashlib.sha1(
                        f"{source['sha256']}:{target['region_id']}".encode()
                    ).hexdigest()[:12]
                )
                existing = _template_candidate(templates, key, owner_id)
                if existing is not None:
                    proof = _template_readback(
                        existing.get("db_id") or existing.get("id"),
                        key,
                        target,
                        owner_id,
                        action="skip",
                        file_sha256=source["sha256"],
                    )
                    items.append(proof)
                    continue
                destination = out_dir / (
                    f"{_safe_file_component(stem)}-{key[-12:]}-{str(data.get('id') or '')[:8]}.xlsx"
                )
                if destination.exists():
                    raise ValueError("template_file_already_exists")
                meta = extract_region_template(
                    source["storage_path"],
                    source_features={"regions": regions},
                    destination=destination,
                    source_region_id=target["region_id"],
                    clear_example_rows=target_type == "shipment_records",
                    owned_upload_user_id=owner_id,
                )
                base = ""
                if region.get("status") == "selected":
                    base = template_ai.suggest_template_name(
                        file_name=source["file_name"],
                        sheet_title=str(meta.get("sheet") or ""),
                        region_label=str(region.get("range") or ""),
                        target_type=target_type,
                        headers=meta.get("headers") or [],
                    )
                if not base:
                    base = _template_name(
                        meta,
                        stem,
                        target_type,
                        primary=region.get("status") == "selected",
                    )
                name, suffix = base, 2
                while name in existing_names:
                    name = f"{base}-{suffix}"
                    suffix += 1
                result = service.save_template(
                    _template_payload(
                        name,
                        key,
                        _template_target_type(data),
                        str(meta.get("file_path") or ""),
                        meta.get("sheet") or "",
                        [header for header in meta.get("headers") or [] if header],
                        business_scope=_template_scope(region, meta, target_type),
                        elt_source={"file_sha256": source["sha256"], **target},
                        elt_run_id=str(data.get("id") or ""),
                    )
                )
                if not result.get("success"):
                    raise ValueError(str(result.get("message") or "save_failed"))
                proof = _template_readback(
                    result.get("id"),
                    key,
                    target,
                    owner_id,
                    action="new",
                    file_sha256=source["sha256"],
                    run_id=str(data.get("id") or ""),
                )
                items.append(proof)
                templates.append(
                    {
                        "id": proof["template_id"],
                        "template_key": key,
                        "file_path": str(meta.get("file_path") or ""),
                    }
                )
                existing_names.add(name)
            except RECOVERABLE_ERRORS as exc:
                failures.append({"target": target, "reason": str(exc)[:200]})
    except RECOVERABLE_ERRORS as exc:
        failures.append({"target": {}, "reason": str(exc)[:200]})
    return _template_batch_receipt(items, failures)
