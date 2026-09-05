# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


def _parse_positive_int(value: _facade().Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _employee_node_ids_for_workflow(db: _facade().Session, workflow_id: int) -> _facade().List[str]:
    rows = (
        db.query(_facade().WorkflowNode)
        .filter(
            _facade().WorkflowNode.workflow_id == int(workflow_id),
            _facade().WorkflowNode.node_type == "employee",
        )
        .all()
    )
    out: _facade().List[str] = []
    for row in rows:
        try:
            cfg = _facade().json.loads(row.config or "{}")
        except _facade().json.JSONDecodeError:
            continue
        eid = str((cfg or {}).get("employee_id") or "").strip()
        if eid:
            out.append(eid)
    return out


def _ensure_minimal_employee_workflow_graph(
    db: _facade().Session,
    workflow_id: int,
    *,
    employee_id: str,
    employee_label: str,
    task: str,
) -> _facade().Dict[str, _facade().Any]:
    """Ensure a workflow has at least start → employee → end nodes.

    The NL graph generator can fail or return zero usable nodes, while the
    workbench has already created the Workflow row and then opens the canvas.
    Without a fallback graph the user sees an empty Vue Flow canvas.  This
    helper creates the smallest executable skeleton and is idempotent: if any
    nodes already exist for the workflow it does nothing.
    """
    wid = int(workflow_id or 0)
    eid = (employee_id or "").strip()
    if not wid or not eid:
        return {"created": False, "reason": "workflow_id/employee_id missing"}
    existing = (
        db.query(_facade().WorkflowNode).filter(_facade().WorkflowNode.workflow_id == wid).count()
    )
    if existing:
        return {
            "created": False,
            "reason": "workflow already has nodes",
            "existing_nodes": int(existing),
        }
    label = (employee_label or "执行员工").strip() or "执行员工"
    task_text = (task or "根据工作流输入完成员工任务").strip()[:400] or "根据工作流输入完成员工任务"
    start = _facade().WorkflowNode(
        workflow_id=wid,
        node_type="start",
        name="开始",
        config=_facade().json.dumps({}, ensure_ascii=False),
        position_x=80,
        position_y=140,
    )
    employee = _facade().WorkflowNode(
        workflow_id=wid,
        node_type="employee",
        name=label[:120],
        config=_facade().json.dumps({"employee_id": eid, "task": task_text}, ensure_ascii=False),
        position_x=340,
        position_y=140,
    )
    end_node = _facade().WorkflowNode(
        workflow_id=wid,
        node_type="end",
        name="结束",
        config=_facade().json.dumps({}, ensure_ascii=False),
        position_x=620,
        position_y=140,
    )
    db.add_all([start, employee, end_node])
    db.flush()
    db.add_all(
        [
            _facade().WorkflowEdge(
                workflow_id=wid,
                source_node_id=start.id,
                target_node_id=employee.id,
                condition="",
            ),
            _facade().WorkflowEdge(
                workflow_id=wid,
                source_node_id=employee.id,
                target_node_id=end_node.id,
                condition="",
            ),
        ]
    )
    db.commit()
    return {"created": True, "nodes_created": 3, "edges_created": 2}


def _resolve_workflow_entry_pack_id(
    mod_dir: _facade().Path,
    mod_manifest: _facade().Dict[str, _facade().Any],
    entry: _facade().Dict[str, _facade().Any],
    workflow_index: int,
) -> tuple[str, str, _facade().Optional[_facade().Dict[str, _facade().Any]]]:
    """返回 (expected_pack_id, error_message, pack_manifest_or_none)。"""
    from modstore_server.employee_pack_export import (
        build_employee_pack_manifest_from_workflow,
    )

    catalog_pkg_id = str(entry.get("catalog_pkg_id") or "").strip()
    if catalog_pkg_id:
        return (catalog_pkg_id, "", None)
    pack_manifest, pack_err = build_employee_pack_manifest_from_workflow(
        mod_dir.name, mod_manifest, entry, workflow_index=workflow_index
    )
    expected = str((pack_manifest or {}).get("id") or "").strip()
    err_msg = (pack_err or "").strip()
    if not expected and (not err_msg):
        err_msg = "无法从该名片推导 employee_pack id"
    return (expected, err_msg, pack_manifest)


def analyze_mod_employee_readiness(
    db: _facade().Session, user: _facade().User, mod_dir: _facade().Path
) -> _facade().Dict[str, _facade().Any]:
    """检查 Mod 员工是否已经从名片走到可执行员工包与工作流绑定。"""
    from modstore_server.catalog_store import list_versions
    from modstore_server.models import CatalogItem

    data, err = _facade().read_manifest(mod_dir)
    if err or not data:
        return {
            "ok": False,
            "error": err or "manifest 无效",
            "employees": [],
            "gaps": [err or "manifest 无效"],
        }
    raw_rows = data.get("workflow_employees")
    if not isinstance(raw_rows, list):
        return {
            "ok": False,
            "employees": [],
            "gaps": ["manifest.workflow_employees 不是数组或尚未声明员工"],
            "summary": {"total": 0, "ready": 0, "blocked": 0},
        }
    rows: _facade().List[_facade().Dict[str, _facade().Any]] = []
    all_gaps: _facade().List[str] = []
    ready_count = 0
    for idx, item in enumerate(raw_rows):
        entry = item if isinstance(item, dict) else {}
        label = str(
            entry.get("label") or entry.get("panel_title") or entry.get("id") or f"员工 {idx + 1}"
        ).strip()
        catalog_pkg_id = str(entry.get("catalog_pkg_id") or "").strip()
        expected_pack_id, pack_err, pack_manifest = _facade()._resolve_workflow_entry_pack_id(
            mod_dir, data, entry, idx
        )
        manifest_employee_id = expected_pack_id
        if catalog_pkg_id:
            _facade().materialize_employee_pack_if_missing(catalog_pkg_id)
        workflow_id = _facade()._parse_positive_int(
            entry.get("workflow_id") or entry.get("workflowId")
        )
        db_pack = None
        if expected_pack_id:
            db_pack = (
                db.query(CatalogItem)
                .filter(
                    CatalogItem.pkg_id == expected_pack_id,
                    CatalogItem.artifact == "employee_pack",
                )
                .first()
            )
        catalog_versions = list_versions(expected_pack_id) if expected_pack_id else []
        workflow_exists = False
        workflow_owner_ok = False
        workflow_employee_ids: _facade().List[str] = []
        workflow_employee_match = False
        if workflow_id > 0:
            wf = db.query(_facade().Workflow).filter(_facade().Workflow.id == workflow_id).first()
            workflow_exists = wf is not None
            workflow_owner_ok = bool(
                wf and (getattr(user, "is_admin", False) or int(wf.user_id) == int(user.id))
            )
            if workflow_exists and workflow_owner_ok:
                workflow_employee_ids = _facade()._employee_node_ids_for_workflow(db, workflow_id)
                workflow_employee_match = (
                    expected_pack_id in workflow_employee_ids if expected_pack_id else False
                )
        gaps: _facade().List[str] = []
        if pack_err or not expected_pack_id:
            gaps.append(pack_err or "无法从该名片推导 employee_pack id")
        if not db_pack:
            gaps.append(f"未登记可执行员工包: {expected_pack_id or 'unknown'}")
        if not workflow_id:
            gaps.append("未写入 workflow_id")
        elif not workflow_exists:
            gaps.append(f"workflow_id={workflow_id} 不存在")
        elif not workflow_owner_ok:
            gaps.append(f"当前用户无权访问 workflow_id={workflow_id}")
        elif not workflow_employee_match:
            if workflow_employee_ids:
                gaps.append(
                    f"工作流 employee 节点未使用可执行包 id {expected_pack_id}（当前: {', '.join(workflow_employee_ids[:6])}）"
                )
            else:
                gaps.append(
                    "工作流中没有可用的 employee 节点（缺少类型为 employee 的节点，或节点未配置 employee_id）。可在自动化任务画布添加「员工」节点并指向已登记包 id；或在 Mod 制作页点「重试图布对齐」由服务端自动插入/修正。"
                )
        real_status = "not_run"
        real_message = "尚未触发非 Mock 真实执行"
        if not db_pack:
            real_status = "blocked"
            real_message = "员工包未登记，生产执行会报“员工包不存在”"
        elif (
            workflow_id and workflow_exists and workflow_owner_ok and (not workflow_employee_match)
        ):
            real_status = "blocked"
            real_message = "工作流节点 employee_id 未指向已登记员工包"
        elif not workflow_id:
            real_status = "blocked"
            real_message = "缺少 workflow_id，无法从 Mod 名片进入工作流验证"
        ready = not gaps
        if ready:
            ready_count += 1
        for gap in gaps:
            all_gaps.append(f"{label}: {gap}")
        rows.append(
            {
                "index": idx,
                "label": label,
                "manifest_employee_id": manifest_employee_id,
                "expected_pack_id": expected_pack_id,
                "catalog_registered": bool(db_pack),
                "catalog_versions": [
                    {
                        "version": str(v.get("version") or ""),
                        "release_channel": str(v.get("release_channel") or ""),
                    }
                    for v in catalog_versions
                    if isinstance(v, dict)
                ],
                "workflow_id": workflow_id,
                "workflow_exists": workflow_exists,
                "workflow_employee_ids": workflow_employee_ids,
                "workflow_employee_match": workflow_employee_match,
                "mock_sandbox": {
                    "status": "linked" if workflow_id else "missing",
                    "message": "结构沙盒只证明图可达，不代表真实员工执行成功",
                },
                "real_execution": {"status": real_status, "message": real_message},
                "ready": ready,
                "gaps": gaps,
            }
        )
    blocked = len(rows) - ready_count
    return {
        "ok": blocked == 0,
        "employees": rows,
        "gaps": all_gaps,
        "summary": {"total": len(rows), "ready": ready_count, "blocked": blocked},
    }


def modstore_library_path() -> _facade().Path:
    from modstore_server.customer_delivery_sources import active_private_library

    private = active_private_library()
    if private is not None:
        return private
    p = _facade().resolved_library(_facade().load_config())
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pick_employee_pack_catalog_record(
    pkg_id: str,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """最新一条登记在 catalog（JSON 或 DB）的 employee_pack，含 ``stored_filename``。"""
    from modstore_server import catalog_store as cs

    pid = (pkg_id or "").strip()
    if not pid:
        return None
    rows = [r for r in cs.list_versions(pid) if str(r.get("artifact") or "") == "employee_pack"]
    if rows:
        top = rows[0]
        if str(top.get("stored_filename") or "").strip():
            return dict(top)
    norm = cs.norm_pkg_id(pid)
    sf = _facade().get_session_factory()
    with sf() as db:
        q = (
            db.query(_facade().CatalogItem)
            .filter(_facade().CatalogItem.artifact == "employee_pack")
            .order_by(_facade().CatalogItem.created_at.desc())
        )
        for row in q.all():
            if cs.norm_pkg_id(row.pkg_id) != norm:
                continue
            fn = str(row.stored_filename or "").strip()
            if not fn:
                continue
            return {
                "id": row.pkg_id,
                "version": row.version or "",
                "artifact": row.artifact or "employee_pack",
                "stored_filename": fn,
            }
    return None


def materialize_employee_pack_if_missing(employee_id: str) -> bool:
    """若 ``<library>/<employee_id>/manifest.json`` 缺失，从 catalog 解压 .xcemp/.xcmod 到该目录。

    解压布局与 ``workbench_api.employee_save`` 一致（丢弃 zip 顶层目录段）。
    用于「目录里已有包登记，但本地 library 尚未落盘」的场景（如同步测试读取员工）。
    """
    from modstore_server import catalog_store as cs

    eid = (employee_id or "").strip()
    if not eid:
        return False
    lib = _facade().modstore_library_path()
    pack_dir = lib / eid
    if (pack_dir / "manifest.json").is_file():
        return True
    rec = _facade()._pick_employee_pack_catalog_record(eid)
    if not rec:
        return False
    fn = str(rec.get("stored_filename") or "").strip()
    if not fn:
        return False
    zip_path = cs.files_dir() / fn
    if not zip_path.is_file():
        return False
    pack_dir.mkdir(parents=True, exist_ok=True)
    tmp_path: _facade().Optional[_facade().Path] = None
    try:
        with _facade().tempfile.NamedTemporaryFile(
            delete=False, suffix=zip_path.suffix or ".zip"
        ) as tmp:
            tmp.write(zip_path.read_bytes())
            tmp_path = _facade().Path(tmp.name)
        with _facade().zipfile.ZipFile(tmp_path, "r") as zf:
            for member in zf.namelist():
                parts = member.split("/", 1)
                if len(parts) == 2 and parts[1]:
                    dest = pack_dir / _facade().Path(parts[1])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not member.endswith("/"):
                        dest.write_bytes(zf.read(member))
    except (OSError, _facade().zipfile.BadZipFile):
        return (pack_dir / "manifest.json").is_file()
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    if not (pack_dir / "manifest.json").is_file():
        return False
    try:
        from modstore_server.employee_pack_workflow_bundle import (
            rehydrate_workflow_bundles,
        )
        from modstore_server.models import get_session_factory

        mf_path = pack_dir / "manifest.json"
        raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
        if raw.get("workflow_bundles") or raw.get("script_workflow_bundles"):
            sf = get_session_factory()
            with sf() as _db:
                from modstore_server.models import User as _User

                author_id_raw = raw.get("author_id") or raw.get("employee_author_id")
                _user_row = None
                if author_id_raw:
                    try:
                        _user_row = _db.query(_User).filter(_User.id == int(author_id_raw)).first()
                    except RECOVERABLE_ERRORS:
                        pass
                if _user_row is None:
                    _user_row = _db.query(_User).order_by(_User.id).first()
                if _user_row is not None:
                    raw = rehydrate_workflow_bundles(_db, _user_row, raw, commit=True)
                    mf_path.write_text(
                        _facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
    except RECOVERABLE_ERRORS:
        import logging as _logging

        _logging.getLogger(__name__).warning("materialize_employee_pack: rehydrate bundles failed")
    return (pack_dir / "manifest.json").is_file()
