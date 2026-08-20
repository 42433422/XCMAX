# mypy: disable-error-code="arg-type, assignment, attr-defined, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


async def register_mod_employee_packs_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    mod_dir: _facade().Path,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
    status_hook: _facade().Optional[_facade().Callable[[str], _facade().Awaitable[None]]] = None,
    industry: str = "通用",
    wf_attach: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    require_workflow_automation: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """把 manifest.workflow_employees 对应的每条员工登记成 Catalog employee_pack。

    复刻 ``api_register_workflow_employee_catalog`` 的核心：build -> audit -> append_package -> CatalogItem。
    每项结果写入 ``workflow_results[i]["pack_register"]``；失败整体不中断，调用方可在
    「登记员工包」步骤里把失败项作为错误展示，并让用户到 Mod 页面重试。
    """
    from modman.manifest_util import read_manifest
    from modstore_server.catalog_store import append_package
    from modstore_server.employee_pack_export import (
        build_employee_pack_zip_from_workflow,
    )
    from modstore_server.models import CatalogItem
    from modstore_server.pack_registration_guards import (
        audit_failure_error_payload,
        classify_audit_failure,
        registration_metadata_mismatches,
        workflow_automation_block_reason,
    )
    from modstore_server.package_sandbox_audit import run_package_audit_async

    data, err = read_manifest(mod_dir)
    if err or not data:
        return {
            "ok": False,
            "error": err or "manifest 无效",
            "registered": [],
            "errors": [],
        }
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or not rows:
        return {
            "ok": True,
            "registered": [],
            "errors": [],
            "note": "无 workflow_employees，无需登记",
        }
    registered: _facade().List[_facade().Dict[str, _facade().Any]] = []
    errors: _facade().List[_facade().Dict[str, _facade().Any]] = []
    total = len(rows)
    mod_id = str(data.get("id") or mod_dir.name).strip()
    industry_name = (industry or str(data.get("industry") or "通用")).strip() or "通用"
    for idx, entry in enumerate(rows):
        if not isinstance(entry, dict):
            continue
        label = str(
            entry.get("label") or entry.get("panel_title") or entry.get("id") or f"员工 {idx + 1}"
        ).strip()
        catalog_pkg_id = str(entry.get("catalog_pkg_id") or "").strip()
        upstream_block = workflow_automation_block_reason(
            workflow_results,
            workflow_index=idx,
            wf_attach=wf_attach if wf_attach and len(rows) == 1 else None,
            wf_entry=entry,
            require_workflow_automation=require_workflow_automation,
        )
        if upstream_block:
            errors.append(
                {
                    "workflow_index": idx,
                    "pack_id": str(entry.get("id") or "").strip() or None,
                    "stage": "upstream",
                    "error": upstream_block,
                    "rejected_upstream": "workflow-automator",
                }
            )
            continue
        if catalog_pkg_id:
            if status_hook:
                short = label[:24] + "…" if len(label) > 24 else label
                await status_hook(f"第 {idx + 1}/{total} 名员工「{short}」：关联市场员工包…")
            _facade().materialize_employee_pack_if_missing(catalog_pkg_id)
            row = (
                db.query(CatalogItem)
                .filter(
                    CatalogItem.pkg_id == catalog_pkg_id,
                    CatalogItem.artifact == "employee_pack",
                )
                .first()
            )
            if not row:
                errors.append(
                    {
                        "workflow_index": idx,
                        "pack_id": catalog_pkg_id,
                        "stage": "catalog",
                        "error": f"市场员工包未登记: {catalog_pkg_id}",
                    }
                )
                continue
            pack_id = catalog_pkg_id
            registered.append(
                {
                    "workflow_index": idx,
                    "pack_id": pack_id,
                    "employee_id": pack_id,
                    "version": row.version,
                    "name": row.name,
                    "audit_summary": {"source": "catalog_pkg_id"},
                }
            )
            if isinstance(workflow_results, list):
                for wf_item in workflow_results:
                    if (
                        isinstance(wf_item, dict)
                        and int(wf_item.get("workflow_index") or -1) == idx
                    ):
                        wf_item["pack_register"] = {
                            "ok": True,
                            "pack_id": pack_id,
                            "employee_id": pack_id,
                        }
                        break
            continue
        if status_hook:
            short = label[:24] + "…" if len(label) > 24 else label
            await status_hook(f"第 {idx + 1}/{total} 名员工「{short}」：构建员工包…")
        raw, build_err, pack_id = build_employee_pack_zip_from_workflow(
            mod_id, data, entry, workflow_index=idx, mod_dir=mod_dir
        )
        if build_err or not raw or (not pack_id):
            errors.append(
                {
                    "workflow_index": idx,
                    "stage": "build",
                    "error": build_err or "生成员工包失败",
                }
            )
            continue
        if status_hook:
            await status_hook(f"第 {idx + 1}/{total} 名员工「{label[:16]}」：五维审核…")
        try:
            audit = await run_package_audit_async(raw, {"artifact": "employee_pack"})
        except RECOVERABLE_ERRORS as e:
            errors.append(
                {
                    "workflow_index": idx,
                    "pack_id": pack_id,
                    "stage": "audit",
                    "error": str(e)[:500],
                }
            )
            continue
        if not audit.get("ok"):
            errors.append(
                {
                    "workflow_index": idx,
                    "pack_id": pack_id,
                    "stage": "audit",
                    "error": str(audit.get("error") or "审核失败")[:500],
                }
            )
            continue
        summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
        audit_manifest = audit.get("manifest") if isinstance(audit.get("manifest"), dict) else {}
        classification = classify_audit_failure(audit)
        if summary and summary.get("pass") is False:
            errors.append(
                audit_failure_error_payload(
                    pack_id=pack_id,
                    workflow_index=idx,
                    audit=audit,
                    classification=classification,
                )
            )
            continue
        if status_hook:
            await status_hook(f"第 {idx + 1}/{total} 名员工「{label[:16]}」：写入 Catalog…")
        rec: _facade().Dict[str, _facade().Any] = {
            "id": pack_id,
            "name": str((audit.get("manifest") or {}).get("name") or label or pack_id),
            "version": str((audit.get("manifest") or {}).get("version") or "1.0.0"),
            "description": str(
                (audit.get("manifest") or {}).get("description") or entry.get("panel_summary") or ""
            ),
            "artifact": "employee_pack",
            "industry": industry_name,
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "personal", "verify_url": None},
            "probe_mod_id": mod_id,
        }
        meta_diff = registration_metadata_mismatches(
            wf_entry=entry,
            mod_manifest=data,
            audit_manifest=audit_manifest,
            catalog_rec=rec,
        )
        if meta_diff:
            errors.append(
                {
                    "workflow_index": idx,
                    "pack_id": pack_id,
                    "stage": "metadata",
                    "error": "登记元数据与包内容不一致，已阻断 Catalog 写入",
                    "mismatches": meta_diff,
                    "audit_passed": classification.get("audit_passed", True),
                    "catalog_registered": False,
                }
            )
            continue
        tmp_path: _facade().Optional[_facade().Path] = None
        try:
            with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
                tmp.write(raw)
                tmp_path = _facade().Path(tmp.name)
            try:
                saved = append_package(rec, tmp_path)
            finally:
                if tmp_path:
                    tmp_path.unlink(missing_ok=True)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
            if not row:
                row = CatalogItem(pkg_id=pack_id, author_id=user.id)
                db.add(row)
            row.version = saved.get("version") or rec["version"]
            row.name = saved.get("name") or rec["name"]
            row.description = saved.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.industry = saved.get("industry") or rec["industry"]
            row.stored_filename = saved.get("stored_filename") or ""
            row.sha256 = saved.get("sha256") or ""
            db.commit()
        except RECOVERABLE_ERRORS as e:
            db.rollback()
            errors.append(
                {
                    "workflow_index": idx,
                    "pack_id": pack_id,
                    "stage": "catalog",
                    "error": str(e)[:500],
                }
            )
            continue
        item = {
            "workflow_index": idx,
            "pack_id": pack_id,
            "employee_id": pack_id,
            "version": row.version,
            "name": row.name,
            "audit_summary": summary or {},
        }
        registered.append(item)
        if isinstance(workflow_results, list):
            for wf_item in workflow_results:
                if isinstance(wf_item, dict) and int(wf_item.get("workflow_index") or -1) == idx:
                    wf_item["pack_register"] = {
                        "ok": True,
                        "pack_id": pack_id,
                        "employee_id": pack_id,
                    }
                    break
    return {"ok": not errors, "registered": registered, "errors": errors}


def _employee_node_ids_for_workflow_cfg(
    db: _facade().Session, workflow_id: int
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    rows = (
        db.query(_facade().WorkflowNode)
        .filter(
            _facade().WorkflowNode.workflow_id == int(workflow_id),
            _facade().WorkflowNode.node_type == "employee",
        )
        .all()
    )
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for row in rows:
        try:
            cfg = _facade().json.loads(row.config or "{}")
        except _facade().json.JSONDecodeError:
            cfg = {}
        out.append({"node": row, "cfg": cfg if isinstance(cfg, dict) else {}})
    return out


def _ensure_workflow_start_end_skeleton(
    db: _facade().Session, workflow_id: int
) -> _facade().List[str]:
    """
    若画布缺 start/end（常见于 NL 生成异常或手工删改），补最小骨架，便于插入 employee 节点。
    不单独 commit，由调用方提交。
    """
    from modstore_server.models import WorkflowEdge, WorkflowNode

    wf_id = int(workflow_id)
    notes: _facade().List[str] = []

    def _degree_maps(
        node_rows: _facade().List[WorkflowNode], edge_rows: _facade().List[WorkflowEdge]
    ) -> _facade().Tuple[_facade().Dict[int, int], _facade().Dict[int, int], set[int]]:
        ids = {n.id for n in node_rows}
        inn: _facade().Dict[int, int] = _facade().defaultdict(int)
        out: _facade().Dict[int, int] = _facade().defaultdict(int)
        for e in edge_rows:
            if e.source_node_id in ids and e.target_node_id in ids:
                out[e.source_node_id] += 1
                inn[e.target_node_id] += 1
        return (inn, out, ids)

    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf_id).all()
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf_id).all()
    start = next((n for n in nodes if n.node_type == "start"), None)
    end = next((n for n in nodes if n.node_type == "end"), None)
    if start and end:
        return notes
    if not nodes:
        s = WorkflowNode(
            workflow_id=wf_id,
            node_type="start",
            name="开始",
            config="{}",
            position_x=40.0,
            position_y=120.0,
        )
        e = WorkflowNode(
            workflow_id=wf_id,
            node_type="end",
            name="结束",
            config="{}",
            position_x=520.0,
            position_y=120.0,
        )
        db.add(s)
        db.add(e)
        db.flush()
        db.add(
            WorkflowEdge(
                workflow_id=wf_id,
                source_node_id=s.id,
                target_node_id=e.id,
                condition="",
            )
        )
        notes.append("empty_graph_start_end")
        return notes
    inn, out, ids = _degree_maps(nodes, edges)
    if not start:
        s = WorkflowNode(
            workflow_id=wf_id,
            node_type="start",
            name="开始",
            config="{}",
            position_x=40.0,
            position_y=120.0,
        )
        db.add(s)
        db.flush()
        roots = [n for n in nodes if inn.get(n.id, 0) == 0]
        targets = roots if roots else [min(nodes, key=lambda x: int(x.id or 0))]
        for t in targets:
            db.add(
                WorkflowEdge(
                    workflow_id=wf_id,
                    source_node_id=s.id,
                    target_node_id=t.id,
                    condition="",
                )
            )
        notes.append("inserted_start")
        nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == wf_id).all()
        edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == wf_id).all()
        inn, out, ids = _degree_maps(nodes, edges)
    end = next((n for n in nodes if n.node_type == "end"), None)
    if not end:
        end_node = WorkflowNode(
            workflow_id=wf_id,
            node_type="end",
            name="结束",
            config="{}",
            position_x=640.0,
            position_y=120.0,
        )
        db.add(end_node)
        db.flush()
        tails = [n for n in nodes if n.id != end_node.id and out.get(n.id, 0) == 0]
        if not tails:
            others = [n for n in nodes if n.id != end_node.id]
            tails = [max(others, key=lambda x: int(x.id or 0))] if others else []
        for t in tails:
            db.add(
                WorkflowEdge(
                    workflow_id=wf_id,
                    source_node_id=t.id,
                    target_node_id=end_node.id,
                    condition="",
                )
            )
        notes.append("inserted_end")
    return notes
