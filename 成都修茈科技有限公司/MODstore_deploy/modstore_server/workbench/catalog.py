"""Catalog for workbench delivery."""

from __future__ import annotations

import json
import logging
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Protocol, cast

from sqlalchemy.orm import Session

from modstore_server.employee_ai_scaffold import (
    build_employee_pack_zip,
    normalize_editor_manifest_for_registry,
)
from modstore_server.models import CatalogItem, ScriptWorkflow, User, Workflow
from modstore_server.operational_errors import RECOVERABLE_ERRORS

_LOG = logging.getLogger("modstore_server.workbench_api")


class CatalogRow(Protocol):
    version: str
    name: str
    description: str
    price: float | Decimal
    artifact: str
    industry: str
    stored_filename: str
    sha256: str


def store_catalog_row(
    db: Session,
    *,
    pack_id: str,
    author_id: int,
    saved: dict[str, Any],
    metadata: dict[str, Any],
    price: float,
    artifact: str = "employee_pack",
) -> CatalogRow:
    record = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
    if record is None:
        record = CatalogItem(pkg_id=pack_id, author_id=author_id)
        db.add(record)
    row = cast(CatalogRow, record)
    row.version = str(saved.get("version") or metadata.get("version") or "")
    row.name = str(saved.get("name") or metadata.get("name") or "")
    row.description = str(saved.get("description") or metadata.get("description") or "")
    row.price = price
    row.artifact = artifact
    row.industry = str(saved.get("industry") or metadata.get("industry") or "")
    row.stored_filename = str(saved.get("stored_filename") or "")
    row.sha256 = str(saved.get("sha256") or "")
    return row


def _load_registry_aligned_employee_manifest(pack_dir: Path, pack_id: str) -> Dict[str, Any]:
    mf = pack_dir / "manifest.json"
    raw = json.loads(mf.read_text(encoding="utf-8"))
    aligned, errs = normalize_editor_manifest_for_registry(raw, pack_id)
    if errs:
        from modman.artifact_constants import normalize_artifact

        if normalize_artifact(aligned) != "employee_pack":
            raise ValueError("manifest 规范化失败: " + "; ".join(errs))
    return dict(aligned)


def _refresh_employee_pack_catalog_zip(db: Session, user: User, pack_dir: Path) -> Dict[str, Any]:
    """Rebuild stored .xcemp after in-place manifest edits.

    ``run_employee_ai_scaffold_async`` first imports/saves the package, then the
    employee pipeline may mutate ``library/<pack>/manifest.json`` (for example
    writing workflow_id into employee_config_v2).  The catalog runtime reads the
    stored .xcemp, not the library folder, so rebuild and re-register that file.
    """
    from modstore_server.catalog_store import (
        append_package,
        package_manifest_alignment_errors,
    )
    from modstore_server.employee_asset_pipeline import reconcile_employee_pack_manifest

    raw = _load_registry_aligned_employee_manifest(pack_dir, pack_dir.name)
    pack_id = str(raw.get("id") or pack_dir.name).strip() or pack_dir.name
    mf_path = pack_dir / "manifest.json"
    mf_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        reconcile_employee_pack_manifest(pack_dir, brief="")
        raw = json.loads(mf_path.read_text(encoding="utf-8"))
        pack_id = str(raw.get("id") or pack_dir.name).strip() or pack_dir.name
    except RECOVERABLE_ERRORS:
        pass
    try:
        from modstore_server.employee_asset_pipeline import (
            build_employee_pack_zip_for_library,
        )

        raw_zip = build_employee_pack_zip_for_library(pack_id, raw, pack_dir=pack_dir)
    except RECOVERABLE_ERRORS:
        raw_zip = build_employee_pack_zip(pack_id, raw)
    with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = Path(tmp.name)
    try:
        rec = {
            "id": pack_id,
            "name": str(raw.get("name") or pack_id),
            "version": str(raw.get("version") or "1.0.0"),
            "description": str(raw.get("description") or ""),
            "artifact": "employee_pack",
            "industry": str(raw.get("industry") or "通用"),
            "release_channel": "stable",
            "commerce": raw.get("commerce") or {"mode": "free", "price": 0},
            "license": {"type": "personal", "verify_url": None},
        }
        align_errs = package_manifest_alignment_errors(rec, tmp_path)
        if align_errs:
            raise ValueError("员工包 metadata 与包内 manifest 不一致: " + "; ".join(align_errs))
        saved = append_package(rec, tmp_path)
        row = store_catalog_row(
            db,
            pack_id=pack_id,
            author_id=cast(int, user.id),
            saved=saved,
            metadata=rec,
            price=0.0,
            artifact="employee_pack",
        )
        db.commit()
        try:
            from modstore_server.api.catalog_public_routes import (
                _invalidate_catalog_list_caches,
            )

            _invalidate_catalog_list_caches(pack_id, row.version)
        except RECOVERABLE_ERRORS:
            pass
        try:
            from modstore_server.employee_asset_pipeline import (
                mirror_catalog_file_to_market_files,
            )

            mirror_catalog_file_to_market_files(row.stored_filename)
        except RECOVERABLE_ERRORS:
            pass
        return saved
    finally:
        tmp_path.unlink(missing_ok=True)


def _assert_employee_catalog_registered(db: Session, pack_id: str) -> bool:
    """Return True when pack_id is visible to employee_executor (DB or packages.json)."""
    pid = str(pack_id or "").strip()
    if not pid:
        return False
    row = (
        db.query(CatalogItem)
        .filter(CatalogItem.pkg_id == pid, CatalogItem.artifact == "employee_pack")
        .first()
    )
    if row:
        return True
    try:
        from modstore_server.catalog_store import employee_pack_records_from_store

        rec = employee_pack_records_from_store().get(pid)
        return isinstance(rec, dict)
    except RECOVERABLE_ERRORS:
        return False


def _employee_pack_workflow_reference_report(
    db: Session, user: User, manifest: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate workflow/script_workflow ID references against the current DB.

    Employee packs currently package manifest/runtime files only; workflow and
    ScriptWorkflow definitions are not migrated inside the .xcemp.  A manifest
    that references IDs not present in the target DB will install successfully
    but fail at runtime, so export/save records an explicit report.
    """
    workflow_ids: List[int] = []
    script_workflow_ids: List[int] = []
    rows = manifest.get("workflow_employees")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                wid = int(row.get("workflow_id") or row.get("workflowId") or 0)
            except (TypeError, ValueError):
                wid = 0
            if wid > 0 and wid not in workflow_ids:
                workflow_ids.append(wid)
    v2 = (
        cast(dict[str, Any], manifest.get("employee_config_v2"))
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    collab = (
        cast(dict[str, Any], v2.get("collaboration"))
        if isinstance(v2.get("collaboration"), dict)
        else {}
    )
    wf = (
        cast(dict[str, Any], collab.get("workflow"))
        if isinstance(collab.get("workflow"), dict)
        else {}
    )
    try:
        wid = int(wf.get("workflow_id") or wf.get("workflowId") or 0)
    except (TypeError, ValueError):
        wid = 0
    if wid > 0 and wid not in workflow_ids:
        workflow_ids.append(wid)
    scripts = collab.get("script_workflows")
    if isinstance(scripts, list):
        for item in scripts:
            if not isinstance(item, dict):
                continue
            try:
                sid = int(item.get("script_workflow_id") or item.get("workflow_id") or 0)
            except (TypeError, ValueError):
                sid = 0
            if sid > 0 and sid not in script_workflow_ids:
                script_workflow_ids.append(sid)
    swa = manifest.get("script_workflow_attachment")
    if isinstance(swa, dict):
        try:
            sid = int(swa.get("script_workflow_id") or swa.get("workflow_id") or 0)
        except (TypeError, ValueError):
            sid = 0
        if sid > 0 and sid not in script_workflow_ids:
            script_workflow_ids.append(sid)
    workflow_found: List[int] = []
    for wid in workflow_ids:
        row = (
            db.query(Workflow)
            .filter(Workflow.id == wid, Workflow.user_id == cast(int, user.id))
            .first()
        )
        if row:
            workflow_found.append(wid)
    script_found: List[int] = []
    for sid in script_workflow_ids:
        row = (
            db.query(ScriptWorkflow)
            .filter(ScriptWorkflow.id == sid, ScriptWorkflow.user_id == cast(int, user.id))
            .first()
        )
        if row:
            script_found.append(sid)
    missing_workflows = [wid for wid in workflow_ids if wid not in workflow_found]
    missing_scripts = [sid for sid in script_workflow_ids if sid not in script_found]
    warnings: List[str] = []
    if missing_workflows:
        warnings.append(f"workflow_id 不存在或不属于当前用户: {missing_workflows}")
    if missing_scripts:
        warnings.append(f"script_workflow_id 不存在或不属于当前用户: {missing_scripts}")
    if workflow_ids or script_workflow_ids:
        warnings.append(
            "employee_pack 不会内嵌 workflow/script_workflow 定义；跨环境上线前必须在目标库重建或重新绑定。"
        )
    return {
        "packaging": "manifest_runtime_only",
        "workflow_ids": workflow_ids,
        "script_workflow_ids": script_workflow_ids,
        "missing_workflow_ids": missing_workflows,
        "missing_script_workflow_ids": missing_scripts,
        "ok": not missing_workflows and (not missing_scripts),
        "warnings": warnings,
    }


def _write_workflow_reference_report(
    db: Session, user: User, manifest: Dict[str, Any]
) -> List[str]:
    report = _employee_pack_workflow_reference_report(db, user, manifest)
    v2 = (
        cast(dict[str, Any], manifest.get("employee_config_v2"))
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    meta = cast(dict[str, Any], v2.get("metadata")) if isinstance(v2.get("metadata"), dict) else {}
    meta["workflow_reference_report"] = report
    meta["workflow_runtime_check"] = (
        "employee_pack 不内嵌 workflow/script_workflow；上线前须确认目标库存在这些 ID 或重新绑定。"
    )
    v2["metadata"] = meta
    manifest["employee_config_v2"] = v2
    return list(report.get("warnings") or [])
