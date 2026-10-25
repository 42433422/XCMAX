"""Auto-merged part* modules (debt24)."""

# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS

# --- from mod_scaffold_runner_part01_part01_part01.py ---
"""Implementation extracted from the public facade module."""


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
    from modstore_server.employee_pack_export import build_employee_pack_manifest_from_workflow

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
        from modstore_server.employee_pack_workflow_bundle import rehydrate_workflow_bundles
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


# --- from mod_scaffold_runner_part01_part01_part02.py ---
"""Implementation extracted from the public facade module."""


def rehydrate_employee_pack_bundles(
    employee_id: str, *, db: _facade().Session, user: _facade().User
) -> bool:
    """Rehydrate bundled workflow definitions for an already-materialized pack.

    Call this after ``materialize_employee_pack_if_missing`` when you have the
    target ``db`` session and ``user`` objects available (e.g. in request
    context).  Safe to call multiple times — bundles track their own
    ``rehydrated_*_id`` markers to avoid creating duplicate rows.

    Returns ``True`` if the pack directory and manifest exist (regardless of
    whether there were any bundles to rehydrate).
    """
    lib = _facade().modstore_library_path()
    pack_dir = lib / (employee_id or "").strip()
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return False
    try:
        from modstore_server.employee_pack_workflow_bundle import rehydrate_workflow_bundles

        raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
        if raw.get("workflow_bundles") or raw.get("script_workflow_bundles"):
            raw = rehydrate_workflow_bundles(db, user, raw, commit=True)
            mf_path.write_text(
                _facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except RECOVERABLE_ERRORS:
        import logging as _logging

        _logging.getLogger(__name__).warning("rehydrate_employee_pack_bundles failed")
    return mf_path.is_file()


def mod_compileall_warnings(mod_dir: _facade().Path) -> _facade().List[str]:
    """对 Mod 下 backend 内 .py 做语法编译检查；失败仅作警告列表，不删 Mod。"""
    backend = mod_dir / "backend"
    if not backend.is_dir():
        return []
    out: _facade().List[str] = []
    for p in sorted(backend.rglob("*.py")):
        try:
            _facade().py_compile.compile(str(p), doraise=True)
        except _facade().py_compile.PyCompileError as e:
            rel = p.relative_to(mod_dir).as_posix()
            out.append(f"{rel}: {e.msg}")
        except OSError as e:
            rel = p.relative_to(mod_dir).as_posix()
            out.append(f"{rel}: {e}")
    return out


def employee_pack_consistency_warnings(mod_dir: _facade().Path) -> _facade().List[str]:
    """员工包静态一致性校验（Phase 1 修复对应的验收规则）：

    1. ``manifest.employee_config_v2.cognition.agent.model.max_tokens`` 与
       ``backend/employees/*.py`` 中 ``call_llm(...)`` 的 ``max_tokens=...`` 一致。
    2. ``actions.handlers`` 声明的每个 handler 在员工 .py 里都能找到对应分支
       （形如 ``'echo'`` / ``'llm_md'`` / ``'webhook'`` 字符串字面量出现）。
    3. 每个 ``await call_llm(`` 调用都被 ``try:`` 包裹（行级启发式：向上 6 行内出现 ``try:``）。
    4. 员工 ``run`` 返回结构包含统一字段（出现 ``'ok'``/``'summary'``/``'error'`` 字面量）。

    仅做静态启发式检查，目的是防止再出现「manifest 与代码脱节 / handlers 形同虚设
    / call_llm 裸 await / 返回字段三套」这类回归。返回的字符串将作为 mod_sandbox
    的 warnings 显示在「包体与 Python 校验」步骤；非阻塞。
    """
    backend = mod_dir / "backend"
    manifest_path = mod_dir / "manifest.json"
    if not backend.is_dir() or not manifest_path.is_file():
        return []
    try:
        manifest = _facade().json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError):
        return []
    if not isinstance(manifest, dict) or manifest.get("artifact") != "employee_pack":
        return []
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
    agent = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
    model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    declared_handlers = [
        str(h).strip()
        for h in (actions.get("handlers") if isinstance(actions.get("handlers"), list) else [])
        if isinstance(h, str) and str(h).strip()
    ]
    manifest_max_tokens = model.get("max_tokens")
    emp_dir = backend / "employees"
    if not emp_dir.is_dir():
        return []
    emp_files = [p for p in sorted(emp_dir.glob("*.py")) if p.name != "__init__.py"]
    if not emp_files:
        return []
    warnings: _facade().List[str] = []
    for emp_py in emp_files:
        try:
            src = emp_py.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = emp_py.relative_to(mod_dir).as_posix()
        lines = src.splitlines()
        for idx, ln in enumerate(lines):
            if "await call_llm(" in ln or ("call_llm(messages" in ln and "await" in ln):
                window = "\n".join(lines[max(0, idx - 6) : idx])
                if "try:" not in window and "asyncio.wait_for" not in ln:
                    warnings.append(
                        f"{rel}:L{idx + 1}: call_llm 调用未被 try/except 或 asyncio.wait_for 包裹（建议统一异常返回）"
                    )
        missing_keys = [
            repr(k)
            for k in ("ok", "summary", "error")
            if f"'{k}'" not in src and f'"{k}"' not in src
        ]
        if missing_keys:
            warnings.append(
                f"{rel}: run 返回结构未见统一字段 {missing_keys}，建议返回 {{ok, summary, items, warnings, error, meta}}"
            )
        if isinstance(manifest_max_tokens, int) and manifest_max_tokens > 0:
            if (
                f"max_tokens={manifest_max_tokens}" not in src
                and f"max_tokens = {manifest_max_tokens}" not in src
            ):
                if _facade().re.search("max_tokens\\s*=\\s*\\d+", src):
                    warnings.append(
                        f"{rel}: call_llm 的 max_tokens 与 manifest({manifest_max_tokens}) 不一致；建议从 manifest 动态读取，避免与 employee_config_v2.cognition.agent.model.max_tokens 漂移"
                    )
        for h in declared_handlers:
            if h in {"vibe_edit", "vibe_heal", "vibe_code"}:
                continue
            if f"'{h}'" not in src and f'"{h}"' not in src:
                warnings.append(
                    f"{rel}: manifest.actions.handlers 声明 '{h}'，但员工实现中未见对应分支字面量"
                )
    return warnings


# --- from mod_scaffold_runner_part02_part01_part01.py ---
"""Implementation extracted from the public facade module."""


def global_registered_employee_ids(*, db: _facade().Optional[_facade().Session] = None) -> set[str]:
    """全局员工注册表：编制 duty_roster + catalog_store + DB catalog + 磁盘 _employees + yuangon。"""
    from modstore_server.duty_roster import all_planned_employee_ids

    ids: set[str] = set(all_planned_employee_ids())
    try:
        from modstore_server.catalog_store import employee_pack_records_from_store

        ids.update(employee_pack_records_from_store().keys())
    except RECOVERABLE_ERRORS:
        _facade()._logger.debug(
            "global_registered_employee_ids: catalog_store skipped", exc_info=True
        )
    if db is not None:
        try:
            from modstore_server.incident_bus import _catalog_employee_ids

            ids.update(_catalog_employee_ids(db))
        except RECOVERABLE_ERRORS:
            _facade()._logger.debug(
                "global_registered_employee_ids: db catalog skipped", exc_info=True
            )
    try:
        cfg = _facade().load_config()
        lib = _facade().resolved_library(cfg)
        emp_root = _facade().Path(lib) / "_employees"
        if emp_root.is_dir():
            for child in emp_root.iterdir():
                if child.is_dir() and (child / "manifest.json").is_file():
                    ids.add(child.name)
    except RECOVERABLE_ERRORS:
        pass
    try:
        from modstore_server.daily_employee_briefs import _workspace_repo_root

        yroot = _workspace_repo_root() / "yuangon"
        if yroot.is_dir():
            for yaml_path in yroot.glob("**/employee.yaml"):
                try:
                    import yaml

                    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                except RECOVERABLE_ERRORS:
                    continue
                if isinstance(data, dict):
                    eid = str(data.get("id") or yaml_path.parent.name).strip()
                    if eid:
                        ids.add(eid)
    except RECOVERABLE_ERRORS:
        pass
    return ids


def employee_pack_compileall_errors(
    mod_dir: _facade().Path,
) -> _facade().Tuple[_facade().List[str], _facade().List[str]]:
    """对包内全部 .py 做语法编译；返回 (errors, warnings)。"""
    errors: _facade().List[str] = []
    warnings: _facade().List[str] = []
    if not mod_dir.is_dir():
        return (errors, warnings)
    for p in sorted(mod_dir.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            _facade().py_compile.compile(str(p), doraise=True)
        except _facade().py_compile.PyCompileError as e:
            rel = p.relative_to(mod_dir).as_posix()
            errors.append(f"{rel}: {e.msg}")
        except OSError as e:
            rel = p.relative_to(mod_dir).as_posix()
            errors.append(f"{rel}: {e}")
    return (errors, warnings)


def _collect_pack_depends_on_ids(
    manifest: _facade().Dict[str, _facade().Any],
) -> _facade().List[str]:
    deps: _facade().List[str] = []
    seen: set[str] = set()

    def _add(raw: _facade().Any) -> None:
        if not isinstance(raw, list):
            return
        for item in raw:
            eid = str(item).strip()
            if eid and eid not in seen:
                seen.add(eid)
                deps.append(eid)

    _add(manifest.get("depends_on"))
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}
    _add(collab.get("depends_on"))
    return deps


def _collect_pack_skill_paths(
    manifest: _facade().Dict[str, _facade().Any], pack_dir: _facade().Path
) -> _facade().List[str]:
    paths: _facade().List[str] = []
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
    for s in cog.get("skills") if isinstance(cog.get("skills"), list) else []:
        if isinstance(s, dict):
            for key in ("path", "file", "skill_path"):
                val = str(s.get(key) or "").strip()
                if val:
                    paths.append(val)
            name = str(s.get("name") or "").strip()
            if name:
                guessed = f"skills/{name}.md" if not name.endswith(".md") else name
                if guessed not in paths:
                    paths.append(guessed)
        elif isinstance(s, str) and s.strip():
            paths.append(s.strip())
    yaml_path = pack_dir / "employee.yaml"
    if yaml_path.is_file():
        try:
            import yaml

            ydata = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(ydata, dict):
                for sk in (ydata.get("skills") if isinstance(ydata.get("skills"), list) else []):
                    if isinstance(sk, str) and sk.strip():
                        paths.append(sk.strip())
        except RECOVERABLE_ERRORS:
            pass
    return paths


def _manifest_validation_stage(
    pack_dir: _facade().Path,
) -> _facade().Dict[str, _facade().Any]:
    stage: _facade().Dict[str, _facade().Any] = {"status": "ok", "errors": []}
    mf, mf_err = _facade().read_manifest(pack_dir)
    if mf_err or not mf:
        stage["status"] = "fail"
        stage["errors"].append(mf_err or "manifest.json 不可读")
        return stage
    if not str(mf.get("id") or "").strip():
        stage["status"] = "fail"
        stage["errors"].append("manifest 缺少 id")
    if str(mf.get("artifact") or "").strip() not in ("employee_pack", ""):
        art = str(mf.get("artifact") or "")
        if art and art != "employee_pack":
            stage["errors"].append(f"artifact 应为 employee_pack，当前为 {art!r}")
            stage["status"] = "fail"
    emp = mf.get("employee") if isinstance(mf.get("employee"), dict) else {}
    if not str(emp.get("id") or "").strip():
        stage["errors"].append("manifest.employee.id 缺失")
        stage["status"] = "fail"
    v2 = mf.get("employee_config_v2") if isinstance(mf.get("employee_config_v2"), dict) else {}
    ident = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
    for key in ("owner", "area"):
        val = ident.get(key)
        if val is not None and (not isinstance(val, str)):
            stage["errors"].append(f"employee_config_v2.identity.{key} 须为字符串")
            stage["status"] = "fail"
    wp = v2.get("workspace_policy") if isinstance(v2.get("workspace_policy"), dict) else {}
    scope = wp.get("scope_globs") if isinstance(wp.get("scope_globs"), list) else []
    forbidden = wp.get("forbidden_globs") if isinstance(wp.get("forbidden_globs"), list) else []
    overlap = set((str(x) for x in scope)) & set((str(x) for x in forbidden))
    if overlap:
        stage["errors"].append(f"scope_globs 与 forbidden_globs 冲突: {sorted(overlap)[:4]}")
        stage["status"] = "fail"
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    handlers = actions.get("handlers")
    if not isinstance(handlers, list) or not handlers:
        stage["errors"].append("employee_config_v2.actions.handlers 为空")
        stage["status"] = "fail"
    yaml_path = pack_dir / "employee.yaml"
    if yaml_path.is_file():
        try:
            import yaml

            ydata = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(ydata, dict):
                for req in ("id", "name", "owner", "area"):
                    if not str(ydata.get(req) or "").strip():
                        stage["errors"].append(f"employee.yaml 缺少必填字段 {req}")
                        stage["status"] = "fail"
                yo = ydata.get("owner")
                ya = ydata.get("area")
                if yo is not None and (not isinstance(yo, str)):
                    stage["errors"].append("employee.yaml owner 须为字符串")
                    stage["status"] = "fail"
                if ya is not None and (not isinstance(ya, str)):
                    stage["errors"].append("employee.yaml area 须为字符串")
                    stage["status"] = "fail"
        except RECOVERABLE_ERRORS as exc:
            stage["errors"].append(f"employee.yaml 解析失败: {exc}")
            stage["status"] = "fail"
    return stage


def _consistency_check_stage(
    pack_dir: _facade().Path,
    manifest: _facade().Dict[str, _facade().Any],
    *,
    db: _facade().Optional[_facade().Session] = None,
) -> _facade().Dict[str, _facade().Any]:
    stage: _facade().Dict[str, _facade().Any] = {
        "status": "ok",
        "missing_skills": [],
        "missing_depends": [],
        "warnings": [],
    }
    registered = _facade().global_registered_employee_ids(db=db)
    pack_id = str(manifest.get("id") or pack_dir.name).strip()
    if pack_id:
        registered.add(pack_id)
    for dep in _facade()._collect_pack_depends_on_ids(manifest):
        if dep not in registered:
            stage["missing_depends"].append(dep)
    pack_id_for_skills = str(manifest.get("id") or pack_dir.name).strip()
    yuangon_pack: _facade().Optional[_facade().Path] = None
    try:
        from modstore_server.daily_employee_briefs import _resolve_pack_dir
        from modstore_server.duty_roster import yuangon_area_for_pkg

        area = yuangon_area_for_pkg(pack_id_for_skills)
        if area:
            _, yuangon_pack = _resolve_pack_dir(area, pack_id_for_skills)
    except RECOVERABLE_ERRORS:
        yuangon_pack = None
    for rel in _facade()._collect_pack_skill_paths(manifest, pack_dir):
        rel_norm = rel.lstrip("/")
        candidates = [
            pack_dir / rel_norm,
            pack_dir / "skills" / _facade().Path(rel_norm).name,
        ]
        if yuangon_pack is not None:
            candidates.append(yuangon_pack / rel_norm)
            candidates.append(yuangon_pack / "skills" / _facade().Path(rel_norm).name)
        if not any((c.is_file() for c in candidates)):
            stage["missing_skills"].append(rel_norm)
    cons_warns = _facade().employee_pack_consistency_warnings(pack_dir)
    if cons_warns:
        stage["warnings"].extend(cons_warns[:12])
    if stage["missing_depends"] or stage["missing_skills"]:
        stage["status"] = "fail"
    return stage


async def _xcemp_validation_stage(
    pack_dir: _facade().Path,
    manifest: _facade().Dict[str, _facade().Any],
    *,
    timeout_seconds: float = 20.0,
) -> _facade().Dict[str, _facade().Any]:
    stage: _facade().Dict[str, _facade().Any] = {
        "status": "ok",
        "errors": [],
        "escalate_to_human": False,
        "package_hash": "",
        "timeout_log": "",
    }
    pack_id = str(manifest.get("id") or pack_dir.name).strip() or "employee-pack"
    try:
        from modstore_server.employee_pack_export import (
            _build_employee_pack_zip_with_source,
            collect_vendor_modules_from_pack,
        )

        vendor = collect_vendor_modules_from_pack(pack_dir) if pack_dir.is_dir() else None
        zip_bytes = _build_employee_pack_zip_with_source(
            pack_id, manifest, None, vendor_modules=vendor
        )
        stage["package_hash"] = _facade().hashlib.sha256(zip_bytes).hexdigest()[:16]
        with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tf:
            tf.write(zip_bytes)
            tmp_path = tf.name
        try:
            proc = await _facade().asyncio.wait_for(
                _facade().asyncio.create_subprocess_exec(
                    _facade().sys.executable,
                    tmp_path,
                    "validate",
                    stdout=_facade().asyncio.subprocess.PIPE,
                    stderr=_facade().asyncio.subprocess.PIPE,
                ),
                timeout=timeout_seconds,
            )
            stdout, stderr = await _facade().asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            if proc.returncode != 0:
                stage["status"] = "fail"
                out = (stderr or stdout or b"").decode("utf-8", errors="replace")[:500]
                stage["errors"].append(f"validate 退出码 {proc.returncode}: {out}")
        except _facade().asyncio.TimeoutError:
            stage["status"] = "fail"
            stage["timeout_log"] = (
                f"python {pack_id}.xcemp validate 超时（{timeout_seconds}s）；package_hash={stage['package_hash']}"
            )
            stage["errors"].append(stage["timeout_log"])
            stage["escalate_to_human"] = True
        finally:
            try:
                _facade().os.unlink(tmp_path)
            except OSError:
                pass
    except RECOVERABLE_ERRORS as exc:
        stage["status"] = "fail"
        stage["errors"].append(f"xcemp 构建或验证异常: {exc!s}"[:400])
    return stage


async def run_employee_pack_code_validation_report(
    pack_dir: _facade().Path,
    *,
    db: _facade().Optional[_facade().Session] = None,
    xcemp_timeout_seconds: float = 20.0,
) -> _facade().Dict[str, _facade().Any]:
    """code-validator / skill-code-validation 结构化校验报告（四阶段 JSON）。"""
    pack_dir = _facade().Path(pack_dir)
    employee_id = pack_dir.name if pack_dir.name else ""
    if not pack_dir.is_dir():
        summary = f"员工包根目录不存在或不可读: {pack_dir}"
        return {
            "status": "fail",
            "employee_id": employee_id,
            "manifest_validation": {"status": "fail", "errors": [summary]},
            "python_compile": {"status": "skipped", "warnings": [], "errors": []},
            "consistency_check": {
                "status": "skipped",
                "missing_skills": [],
                "missing_depends": [],
            },
            "xcemp_validation": {
                "status": "skipped",
                "errors": [],
                "escalate_to_human": False,
            },
            "summary": summary,
        }
    mf, mf_err = _facade().read_manifest(pack_dir)
    if mf_err or not isinstance(mf, dict):
        mf = {}
    employee_id = str(mf.get("id") or employee_id).strip()
    manifest_validation = _facade()._manifest_validation_stage(pack_dir)
    report: _facade().Dict[str, _facade().Any] = {
        "status": "ok",
        "employee_id": employee_id,
        "manifest_validation": manifest_validation,
        "python_compile": {"status": "ok", "warnings": [], "errors": []},
        "consistency_check": {
            "status": "ok",
            "missing_skills": [],
            "missing_depends": [],
        },
        "xcemp_validation": {"status": "ok", "errors": [], "escalate_to_human": False},
        "summary": "",
    }
    if manifest_validation.get("status") == "fail":
        report["status"] = "fail"
        report["python_compile"]["status"] = "skipped"
        report["consistency_check"]["status"] = "skipped"
        report["xcemp_validation"]["status"] = "skipped"
        report["summary"] = (
            "manifest 校验失败: " + "；".join(manifest_validation.get("errors") or [])[:400]
        )
        return report
    py_errors, py_warns = _facade().employee_pack_compileall_errors(pack_dir)
    backend_warns = _facade().mod_compileall_warnings(pack_dir)
    merged_warns = list(dict.fromkeys(py_warns + backend_warns))
    report["python_compile"] = {
        "status": "fail" if py_errors else "ok",
        "warnings": merged_warns,
        "errors": py_errors,
    }
    if py_errors:
        report["status"] = "fail"
    consistency = _facade()._consistency_check_stage(pack_dir, mf, db=db)
    report["consistency_check"] = {
        "status": consistency.get("status"),
        "missing_skills": consistency.get("missing_skills") or [],
        "missing_depends": consistency.get("missing_depends") or [],
        "warnings": consistency.get("warnings") or [],
    }
    if consistency.get("status") == "fail":
        report["status"] = "fail"
    xcemp = await _facade()._xcemp_validation_stage(
        pack_dir, mf, timeout_seconds=xcemp_timeout_seconds
    )
    report["xcemp_validation"] = {
        "status": xcemp.get("status"),
        "errors": xcemp.get("errors") or [],
        "escalate_to_human": bool(xcemp.get("escalate_to_human")),
        "package_hash": xcemp.get("package_hash") or "",
        "timeout_log": xcemp.get("timeout_log") or "",
    }
    if xcemp.get("status") == "fail":
        report["status"] = "fail"
        if xcemp.get("escalate_to_human"):
            try:
                from modstore_server.craft_failure_signals import _employee_escalate_to_human

                if _employee_escalate_to_human("code-validator"):
                    report["xcemp_validation"]["escalate_to_human"] = True
            except RECOVERABLE_ERRORS:
                report["xcemp_validation"]["escalate_to_human"] = True
    parts: _facade().List[str] = []
    if report["status"] == "ok":
        parts.append("员工包四阶段校验通过")
    else:
        if manifest_validation.get("status") == "fail":
            parts.append("manifest 未通过")
        if report["python_compile"].get("status") == "fail":
            parts.append(f"Python 编译 {len(py_errors)} 处错误")
        if consistency.get("missing_depends"):
            parts.append(f"depends_on 未注册: {', '.join(consistency['missing_depends'][:4])}")
        if consistency.get("missing_skills"):
            parts.append(f"skills 缺失: {', '.join(consistency['missing_skills'][:4])}")
        if xcemp.get("status") == "fail":
            parts.append("xcemp validate 未通过")
    report["summary"] = "；".join(parts) if parts else report["status"]
    return report


# --- from mod_scaffold_runner_part02_part01_part02.py ---
"""Implementation extracted from the public facade module."""


def resolve_llm_provider_model(
    db: _facade().Session,
    user: _facade().User,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Optional[str], _facade().Optional[str], _facade().Optional[str]]:
    """
    返回 (provider, model, error_message)。
    若 body 未传 provider/model，则读用户 default_llm_json。
    """
    prov = (provider or "").strip()
    mdl = (model or "").strip()
    if prov and mdl:
        if prov not in _facade().KNOWN_PROVIDERS:
            return (None, None, f"不支持的供应商: {prov}")
        return (prov, mdl, None)
    urow = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    raw_pref = ((urow.default_llm_json if urow else None) or "").strip()
    prefs: _facade().Dict[str, _facade().Any] = {}
    if raw_pref:
        try:
            loaded = _facade().json.loads(raw_pref)
            if isinstance(loaded, dict):
                prefs = loaded
        except _facade().json.JSONDecodeError:
            prefs = {}
    prov = str(prefs.get("provider") or "").strip()
    mdl = str(prefs.get("model") or "").strip()
    if not prov or prov not in _facade().KNOWN_PROVIDERS or (not mdl):
        return (
            None,
            None,
            "请先在 LLM 设置中选择默认供应商与模型，或在请求中传入 provider 与 model",
        )
    return (prov, mdl, None)


async def resolve_llm_provider_model_auto(
    db: _facade().Session,
    user: _facade().User,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Optional[str], _facade().Optional[str], _facade().Optional[str]]:
    """
    工作台 Auto 语义：显式 provider/model 必须可用；否则优先账户默认，
    默认无 key 时自动切到第一个有 key 且能拿到模型目录的供应商。
    """
    prov = (provider or "").strip()
    mdl = (model or "").strip()
    if prov and mdl:
        if prov not in _facade().KNOWN_PROVIDERS:
            return (None, None, f"不支持的供应商: {prov}")
        api_key, _ = _facade().resolve_api_key(db, user.id, prov)
        if not api_key:
            return (None, None, f"供应商 {prov} 未配置可用 API Key")
        return (prov, mdl, None)
    from modstore_server.llm_catalog import get_models_for_provider

    async def first_model_id(p: str) -> str:
        try:
            block = await get_models_for_provider(db, user.id, p, force_refresh=False)
        except RECOVERABLE_ERRORS:
            return ""
        mids = list(block.get("models") or [])
        return str(mids[0]).strip() if mids else ""

    urow = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    raw_pref = ((urow.default_llm_json if urow else None) or "").strip()
    prefs: _facade().Dict[str, _facade().Any] = {}
    if raw_pref:
        try:
            loaded = _facade().json.loads(raw_pref)
            if isinstance(loaded, dict):
                prefs = loaded
        except _facade().json.JSONDecodeError:
            prefs = {}
    pref_p = str(prefs.get("provider") or "").strip()
    pref_m = str(prefs.get("model") or "").strip()
    if pref_p in _facade().KNOWN_PROVIDERS:
        api_key, _ = _facade().resolve_api_key(db, user.id, pref_p)
        if api_key:
            if pref_m:
                return (pref_p, pref_m, None)
            m0 = await first_model_id(pref_p)
            if m0:
                return (pref_p, m0, None)
    if "xiaomi" in _facade().KNOWN_PROVIDERS:
        api_key, _ = _facade().resolve_api_key(db, user.id, "xiaomi")
        if api_key:
            m0 = await first_model_id("xiaomi")
            if m0:
                return ("xiaomi", m0, None)
    for p in _facade().KNOWN_PROVIDERS:
        api_key, _ = _facade().resolve_api_key(db, user.id, p)
        if not api_key:
            continue
        m0 = await first_model_id(p)
        if m0:
            return (p, m0, None)
    return (None, None, "没有找到已配置 API Key 且可用模型目录的 LLM 供应商")


# --- from mod_scaffold_runner_part03_part01_part01.py ---
"""Implementation extracted from the public facade module."""


async def generate_workflow_for_intent(
    db: _facade().Session,
    user: _facade().User,
    *,
    role: str,
    scenario: str,
    workflow_name: str,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    target_employee_pack_id: _facade().Optional[str] = None,
    target_employee_label: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    """为 employee_ai_pipeline Stage 2 兜底生成：创建 Workflow 记录 + NL 生图。

    返回 {"ok": True, "workflow_id": int, "name": str} 或 {"ok": False, "error": str}。
    不进行完整沙箱回归（沙箱验证留给用户在工作流页面手动运行），
    但会记录工作流以供 Stage 6 manifest 引用。
    """
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    name = (workflow_name or f"AI 生成工作流 - {role[:20]}")[:256]
    brief_for_nl = f"角色：{role}\n场景：{scenario}" if scenario else role
    wf = _facade().Workflow(
        user_id=user.id, name=name, description=brief_for_nl[:1000], is_active=True
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    nl = await apply_nl_workflow_graph(
        db,
        user,
        workflow_id=wf.id,
        brief=brief_for_nl,
        provider=prov,
        model=mdl,
        target_employee_pack_id=target_employee_pack_id,
        target_employee_label=target_employee_label,
        status_hook=None,
    )
    if not nl.get("ok"):
        return {"ok": False, "error": f"工作流 NL 生图失败: {nl.get('error') or ''}"}
    return {"ok": True, "workflow_id": wf.id, "name": name}


async def run_mod_ai_scaffold_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    suggested_id: _facade().Optional[str] = None,
    replace: bool = True,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    generate_frontend: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """
    生成并导入 Mod。成功: {"ok": True, "id", "path", "manifest"}；
    失败: {"ok": False, "error": "..."}。
    """
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {"ok": False, "error": "描述过短"}
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return {"ok": False, "error": "该供应商未配置可用 API Key（平台或 BYOK）"}
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    user_lines = [brief]
    hint = _facade().normalize_mod_id(suggested_id or "")
    if hint:
        user_lines.append(f"作者希望的 manifest.id（若与描述不冲突可采用）: {hint}")
    msgs = [
        {"role": "system", "content": _facade().SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_lines)},
    ]
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base,
        model=mdl,
        messages=msgs,
        max_tokens=2048,
        response_format=_facade()._json_response_format(prov),
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "upstream error"}
    manifest, perr = _facade().parse_llm_manifest_json(str(result.get("content") or ""))
    if perr or not manifest:
        return {"ok": False, "error": perr or "无法解析模型输出为 manifest"}
    mid = str(manifest.get("id") or "").strip()
    mname = str(manifest.get("name") or mid)
    lib = _facade().modstore_library_path()
    dest_path = lib / mid
    if dest_path.is_dir() and (not replace):
        return {
            "ok": False,
            "error": f"Mod {mid} 已存在，请传 replace=true 覆盖或更换描述",
        }
    try:
        raw_zip = _facade().build_scaffold_zip(mid, mname, manifest)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    with _facade().tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        dest = _facade().import_zip(tmp_path, lib, replace=replace)
    except (ValueError, FileExistsError) as e:
        return {"ok": False, "error": str(e)}
    finally:
        tmp_path.unlink(missing_ok=True)
    _facade().add_user_mod(user.id, dest.name)
    return {"ok": True, "id": dest.name, "path": str(dest), "manifest": manifest}


def _suite_blueprint_file(
    blueprint: _facade().Dict[str, _facade().Any],
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> str:
    data = dict(blueprint)
    data["workflow_results"] = workflow_results
    return _facade().json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _suite_validation_summary(
    mod_dir: _facade().Path,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    from modman.manifest_util import read_manifest, validate_manifest_dict

    manifest_warnings: _facade().List[str] = []
    data, err = read_manifest(mod_dir)
    if err or not data:
        manifest_warnings.append(err or "manifest 无效")
    else:
        manifest_warnings.extend(validate_manifest_dict(data))
    python_warnings = _facade().mod_compileall_warnings(mod_dir)
    workflow_warnings: _facade().List[str] = []
    for item in workflow_results:
        if not isinstance(item, dict):
            continue
        graph = item.get("graph")
        if isinstance(graph, dict):
            if not graph.get("ok", True):
                workflow_warnings.append(str(graph.get("error") or "工作流图生成失败"))
            for err_item in graph.get("validation_errors") or []:
                workflow_warnings.append(str(err_item))
            for warn in graph.get("llm_warnings") or []:
                workflow_warnings.append(str(warn))
        elif item.get("error"):
            workflow_warnings.append(str(item.get("error")))
    repair_suggestions: _facade().List[str] = []
    if manifest_warnings:
        repair_suggestions.append("检查 manifest 字段、目录名与 workflow_employees 结构。")
    if python_warnings:
        repair_suggestions.append("打开 backend/blueprints.py，根据 Python 语法提示修复路由骨架。")
    if workflow_warnings:
        repair_suggestions.append("进入工作流画布检查节点配置、员工 id、知识库或 OpenAPI 参数。")
    return {
        "ok": not (manifest_warnings or python_warnings or workflow_warnings),
        "manifest_warnings": manifest_warnings,
        "python_warnings": python_warnings,
        "workflow_warnings": workflow_warnings,
        "repair_suggestions": repair_suggestions,
    }


def _json_response_format(
    provider: _facade().Optional[str],
) -> _facade().Optional[_facade().Dict[str, str]]:
    if provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        return {"type": "json_object"}
    return None


def _mod_suite_industry_card_payload(
    blueprint: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    industry = blueprint.get("industry") if isinstance(blueprint.get("industry"), dict) else {}
    manifest = blueprint.get("manifest") if isinstance(blueprint.get("manifest"), dict) else {}
    card: _facade().Dict[str, _facade().Any] = {
        "schema_version": 1,
        "id": str(
            industry.get("id") or industry.get("name") or manifest.get("id") or "通用"
        ).strip()
        or "通用",
        "name": str(industry.get("name") or manifest.get("name") or "通用").strip() or "通用",
        "scenario": str(industry.get("scenario") or manifest.get("description") or "").strip(),
        "description": str(
            industry.get("description")
            or industry.get("scenario")
            or manifest.get("description")
            or ""
        ).strip(),
        "source": "ai_blueprint",
    }
    for key in (
        "units",
        "quantity_fields",
        "product_fields",
        "order_types",
        "intent_keywords",
        "print_config",
        "fields",
        "keywords",
    ):
        value = industry.get(key)
        if value not in (None, "", [], {}):
            card[key] = value
    return card


def _mod_suite_ui_shell_payload(
    blueprint: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    manifest = blueprint.get("manifest") if isinstance(blueprint.get("manifest"), dict) else {}
    frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
    frontend_shell = frontend.get("shell") if isinstance(frontend.get("shell"), dict) else {}
    ui_shell = blueprint.get("ui_shell") if isinstance(blueprint.get("ui_shell"), dict) else {}
    industry = blueprint.get("industry") if isinstance(blueprint.get("industry"), dict) else {}
    payload: _facade().Dict[str, _facade().Any] = dict(frontend_shell)
    payload.update(ui_shell)
    payload.setdefault("schema_version", 1)
    payload.setdefault("target", "traditional-mode")
    payload.setdefault("mod_id", manifest.get("id") or "")
    payload.setdefault("mod_name", manifest.get("name") or manifest.get("id") or "")
    payload.setdefault("industry", industry.get("name") or "通用")
    payload.setdefault("sidebar_menu", [])
    payload.setdefault(
        "menu_overrides",
        frontend.get("menu_overrides") if isinstance(frontend.get("menu_overrides"), list) else [],
    )
    payload.setdefault(
        "settings",
        {
            "default_industry": industry.get("name") or "通用",
            "industry_options": [industry.get("name") or "通用"],
        },
    )
    payload.setdefault("make_scene", {})
    return payload


def _mod_suite_user_lines(brief: str, suggested_id: _facade().Optional[str]) -> _facade().List[str]:
    user_lines = [brief]
    hint = _facade().normalize_mod_id(suggested_id or "")
    if hint:
        user_lines.append(f"作者希望的 manifest.id（若与描述不冲突可采用）: {hint}")
    return user_lines


async def _repair_mod_suite_json_async(
    prov: str,
    *,
    api_key: str,
    base_url: _facade().Optional[str],
    model: str,
    raw: str,
    parse_error: str,
) -> _facade().Tuple[_facade().Optional[_facade().Dict[str, _facade().Any]], str, bool]:
    repair_prompt = "你是严格 JSON 修复器。用户会提供一个被截断、带多余文字或字符串未闭合的 Mod 蓝图 JSON。请只输出一个合法 JSON 对象，不要 markdown，不要解释。保持原意，缺失字段按最小可用值补全，必须包含 manifest、industry、employees、configs。"
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": repair_prompt},
            {
                "role": "user",
                "content": f"解析错误：{parse_error}\n\n原始输出：\n{raw[:20000]}",
            },
        ],
        max_tokens=8192,
        response_format=_facade()._json_response_format(prov),
    )
    if not result.get("ok"):
        return (None, result.get("error") or "JSON 修复调用失败", True)
    parsed, perr = _facade().parse_llm_mod_suite_json(str(result.get("content") or ""))
    return (parsed, perr, True)


async def generate_mod_suite_blueprint_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    suggested_id: _facade().Optional[str] = None,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
) -> _facade().Dict[str, _facade().Any]:
    """生成并解析 Mod 套件蓝图；失败时尝试一次 JSON 修复。"""
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {"ok": False, "error": "描述过短"}
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return {"ok": False, "error": "该供应商未配置可用 API Key（平台或 BYOK）"}
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    result = await _facade().chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base,
        model=mdl,
        messages=[
            {"role": "system", "content": _facade().SYSTEM_PROMPT_SUITE},
            {
                "role": "user",
                "content": "\n\n".join(_facade()._mod_suite_user_lines(brief, suggested_id)),
            },
        ],
        max_tokens=8192,
        response_format=_facade()._json_response_format(prov),
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "upstream error"}
    raw = str(result.get("content") or "")
    parsed, perr = _facade().parse_llm_mod_suite_json(raw)
    repair_used = False
    if perr or not parsed:
        parsed, perr, repair_used = await _facade()._repair_mod_suite_json_async(
            prov,
            api_key=api_key,
            base_url=base,
            model=mdl,
            raw=raw,
            parse_error=perr or "无法解析模型输出为 Mod 蓝图",
        )
    if perr or not parsed:
        return {
            "ok": False,
            "error": perr or "无法解析模型输出为 Mod 蓝图",
            "raw_content": raw[:4000],
        }
    return {
        "ok": True,
        "provider": prov,
        "model": mdl,
        "parsed": parsed,
        "raw_content": raw[:4000],
        "repair_used": repair_used,
    }


# --- from mod_scaffold_runner_part03_part01_part02.py ---
"""Implementation extracted from the public facade module."""


def import_mod_suite_repository(
    db: _facade().Session,
    user: _facade().User,
    *,
    parsed: _facade().Dict[str, _facade().Any],
    replace: bool = True,
    generate_frontend: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    manifest = parsed["manifest"]
    employees = parsed.get("employees") or []
    blueprint = parsed.get("blueprint") or {}
    mid = str(manifest.get("id") or "").strip()
    mname = str(manifest.get("name") or mid)
    lib = _facade().modstore_library_path()
    dest_path = lib / mid
    if dest_path.is_dir() and (not replace):
        return {
            "ok": False,
            "error": f"Mod {mid} 已存在，请传 replace=true 覆盖或更换描述",
        }
    employees_for_routes = _facade().merge_employees_for_blueprint_routes(manifest, employees)
    extra_files = {
        "backend/blueprints.py": _facade().render_suite_blueprints_py(
            mid, mname, employees_for_routes
        ),
        "config/ai_blueprint.json": _facade()._suite_blueprint_file(blueprint, []),
        "config/industry_card.json": _facade().json.dumps(
            _facade()._mod_suite_industry_card_payload(blueprint),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "config/ui_shell.json": _facade().json.dumps(
            _facade()._mod_suite_ui_shell_payload(blueprint),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    }
    frontend_app = (
        blueprint.get("frontend_app") if isinstance(blueprint.get("frontend_app"), dict) else {}
    )
    had_frontend_fallback = False
    if generate_frontend and (not frontend_app):
        desc = str(manifest.get("description") or "").strip()
        industry_payload = _facade()._sanitize_industry(
            blueprint.get("industry") if isinstance(blueprint.get("industry"), dict) else {},
            mod_name=mname,
            description=desc,
        )
        fe = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
        menu_raw = fe.get("menu") if isinstance(fe.get("menu"), list) else None
        fm = _facade()._normalize_frontend_menu(menu_raw, mod_id=mid, mod_name=mname)
        bp_emp = blueprint.get("employees") if isinstance(blueprint.get("employees"), list) else []
        emp_for_fe = employees if employees else bp_emp
        if not isinstance(emp_for_fe, list):
            emp_for_fe = []
        frontend_app = _facade()._normalize_frontend_app(
            {},
            mod_id=mid,
            mod_name=mname,
            description=desc,
            industry=industry_payload,
            employees=emp_for_fe,
            frontend_menu=fm,
        )
        had_frontend_fallback = True
        if isinstance(blueprint, dict):
            blueprint["frontend_app"] = frontend_app
        if isinstance(parsed, dict):
            bp_store = parsed.get("blueprint")
            if not isinstance(bp_store, dict):
                parsed["blueprint"] = {}
                bp_store = parsed["blueprint"]
            bp_store["frontend_app"] = frontend_app
    if generate_frontend and frontend_app:
        entry_path = str(frontend_app.get("entry_path") or f"/{mid}")
        extra_files.update(
            {
                "config/frontend_spec.json": _facade().json.dumps(
                    frontend_app, ensure_ascii=False, indent=2
                )
                + "\n",
                "frontend/routes.js": _facade().render_frontend_routes_js(mid, mname, entry_path),
                "frontend/views/HomeView.vue": _facade().render_generated_home_vue(
                    mid, mname, frontend_app
                ),
            }
        )
    try:
        raw_zip = _facade().build_scaffold_zip(mid, mname, manifest, extra_files=extra_files)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    with _facade().tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        dest = _facade().import_zip(tmp_path, lib, replace=replace)
    except (ValueError, FileExistsError) as e:
        return {"ok": False, "error": str(e)}
    finally:
        tmp_path.unlink(missing_ok=True)
    _facade().add_user_mod(user.id, dest.name)
    return {
        "ok": True,
        "id": dest.name,
        "path": str(dest),
        "manifest": manifest,
        "employees": employees,
        "blueprint": blueprint,
        "frontend_app": frontend_app if generate_frontend else None,
        "had_frontend_fallback": had_frontend_fallback,
    }


def write_mod_suite_industry_card(
    mod_dir: _facade().Path, blueprint: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    card = _facade()._mod_suite_industry_card_payload(blueprint)
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "industry_card.json").write_text(
        _facade().json.dumps(card, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return card


def write_mod_suite_ui_shell(
    mod_dir: _facade().Path, blueprint: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    ui_shell = _facade()._mod_suite_ui_shell_payload(blueprint)
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "ui_shell.json").write_text(
        _facade().json.dumps(ui_shell, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ui_shell


def _openapi_node_summary(
    db: _facade().Session, workflow_id: int
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    rows = (
        db.query(_facade().WorkflowNode)
        .filter(
            _facade().WorkflowNode.workflow_id == int(workflow_id),
            _facade().WorkflowNode.node_type == "openapi_operation",
        )
        .all()
    )
    out: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for row in rows:
        try:
            cfg = _facade().json.loads(row.config or "{}")
        except _facade().json.JSONDecodeError:
            cfg = {}
        out.append(
            {
                "workflow_id": workflow_id,
                "node_id": row.id,
                "name": row.name,
                "connector_id": int(cfg.get("connector_id") or 0),
                "operation_id": str(cfg.get("operation_id") or ""),
                "needs_configuration": not int(cfg.get("connector_id") or 0)
                or not str(cfg.get("operation_id") or "").strip(),
            }
        )
    return out


async def create_mod_suite_workflows_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    mod_dir: _facade().Path,
    employees: _facade().List[_facade().Dict[str, _facade().Any]],
    brief: str,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    step_message_hook: _facade().Optional[
        _facade().Callable[[str], _facade().Awaitable[None]]
    ] = None,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workflow_mod_link import (
        WorkflowModLinkBody,
        merge_workflow_id_into_existing_entry,
    )
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]] = []
    api_nodes: _facade().List[_facade().Dict[str, _facade().Any]] = []
    mod_manifest, mod_manifest_err = _facade().read_manifest(mod_dir)
    if mod_manifest_err or not isinstance(mod_manifest, dict):
        mod_manifest = {"id": mod_dir.name}
    n_employees = sum((1 for e in employees if isinstance(e, dict)))
    emp_ord = 0
    for idx, emp in enumerate(employees):
        if not isinstance(emp, dict):
            continue
        try:
            wf_cfg = emp.get("workflow") if isinstance(emp.get("workflow"), dict) else {}
            wf_name = str(
                wf_cfg.get("name") or f"{emp.get('label') or f'员工{idx + 1}'}工作流"
            ).strip()
            wf_desc = str(wf_cfg.get("description") or emp.get("panel_summary") or brief).strip()
            wf = _facade().Workflow(
                user_id=user.id,
                name=(wf_name or f"工作流 {idx + 1}")[:256],
                description=wf_desc[:4000],
                is_active=True,
            )
            db.add(wf)
            db.commit()
            db.refresh(wf)
            emp_ord += 1
            wf_label = str(wf.name or wf_name or f"工作流{emp_ord}")[:256]
            if step_message_hook:
                short = wf_label[:36] + "…" if len(wf_label) > 36 else wf_label
                await step_message_hook(
                    f"第 {emp_ord}/{max(n_employees, 1)} 名员工：已建工作流「{short}」，即将请求模型生成节点与边…"
                )

            async def _nl_status(
                msg: str,
                cur: int = emp_ord,
                tot: int = n_employees,
                wlab: str = wf_label,
            ) -> None:
                if step_message_hook:
                    snippet = wlab[:28] + "…" if len(wlab) > 28 else wlab
                    await step_message_hook(f"第 {cur}/{max(tot, 1)} 名「{snippet}」：{msg}")

            (
                pack_manifest,
                _pack_manifest_err,
            ) = _facade().build_employee_pack_manifest_from_workflow(
                mod_dir.name, mod_manifest, emp, workflow_index=idx
            )
            target_pack_id = str((pack_manifest or {}).get("id") or "").strip()
            target_label = str(
                emp.get("label") or emp.get("panel_title") or target_pack_id or ""
            ).strip()
            nl = await apply_nl_workflow_graph(
                db,
                user,
                workflow_id=wf.id,
                brief=wf_desc or brief,
                provider=provider,
                model=model,
                target_employee_pack_id=target_pack_id or None,
                target_employee_label=target_label or None,
                status_hook=_nl_status if step_message_hook else None,
            )
            link_result = merge_workflow_id_into_existing_entry(
                mod_dir,
                WorkflowModLinkBody(workflow_id=wf.id, workflow_index=idx),
                workflow_name=wf.name,
                workflow_description=wf.description or "",
            )
            wf_api_nodes = _facade()._openapi_node_summary(db, wf.id)
            api_nodes.extend(wf_api_nodes)
            _nl_ok = bool(nl.get("ok", True))
            workflow_results.append(
                {
                    "ok": _nl_ok,
                    "automation_complete": _nl_ok and bool(wf.id),
                    "employee_id": target_pack_id,
                    "workflow_id": wf.id,
                    "workflow_name": wf.name,
                    "workflow_index": idx,
                    "graph": nl,
                    "api_nodes": wf_api_nodes,
                    "manifest_link": link_result,
                }
            )
        except RECOVERABLE_ERRORS as e:
            workflow_results.append(
                {
                    "ok": False,
                    "automation_complete": False,
                    "employee_id": target_pack_id if "target_pack_id" in dir() else "",
                    "workflow_index": idx,
                    "stage": "workflow_binding",
                    "error": str(e)[:1000],
                }
            )
    return {
        "ok": not any((not item.get("ok", True) for item in workflow_results)),
        "workflow_results": workflow_results,
        "api_nodes": api_nodes,
        "api_warnings": [
            f"{n.get('name') or n.get('node_id')} 需要配置 connector_id/operation_id"
            for n in api_nodes
            if n.get("needs_configuration")
        ],
    }


def run_mod_suite_workflow_sandboxes(
    db: _facade().Session,
    user: _facade().User,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.workflow_engine import run_workflow_sandbox
    from modstore_server.workflow_sandbox_state import record_workflow_sandbox_run

    reports: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for item in workflow_results:
        wid = item.get("workflow_id") if isinstance(item, dict) else None
        if not wid:
            continue
        report = run_workflow_sandbox(int(wid), {}, mock_employees=True, validate_only=False)
        try:
            record_workflow_sandbox_run(
                db,
                workflow_id=int(wid),
                user_id=user.id,
                report=report,
                validate_only=False,
                mock_employees=True,
            )
        except RECOVERABLE_ERRORS:
            pass
        item["sandbox_report"] = report
        reports.append({"workflow_id": int(wid), "ok": bool(report.get("ok")), "report": report})
    return {
        "ok": all((r.get("ok") for r in reports)) if reports else True,
        "reports": reports,
    }


def write_mod_suite_blueprint(
    mod_dir: _facade().Path,
    blueprint: _facade().Dict[str, _facade().Any],
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
    *,
    industry_card: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    ui_shell: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    api_summary: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    workflow_sandbox: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    employee_readiness: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    vibe_index: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    vibe_heal: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> None:
    data = dict(blueprint)
    if industry_card is not None:
        data["industry_card"] = industry_card
    if ui_shell is not None:
        data["ui_shell"] = ui_shell
    if api_summary is not None:
        data["api_summary"] = api_summary
    if workflow_sandbox is not None:
        data["workflow_sandbox"] = workflow_sandbox
    if employee_readiness is not None:
        data["employee_readiness"] = employee_readiness
    if vibe_index is not None:
        data["vibe_index"] = vibe_index
    if vibe_heal is not None:
        data["vibe_heal"] = vibe_heal
    (mod_dir / "config").mkdir(parents=True, exist_ok=True)
    (mod_dir / "config" / "ai_blueprint.json").write_text(
        _facade()._suite_blueprint_file(data, workflow_results), encoding="utf-8"
    )


def run_mod_suite_mod_sandbox(
    mod_dir: _facade().Path,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    from modman.manifest_util import read_manifest

    checks: _facade().List[_facade().Dict[str, _facade().Any]] = []
    data, err = read_manifest(mod_dir)
    checks.append(
        {
            "id": "manifest",
            "ok": not err and bool(data),
            "message": err or "manifest 可读取",
        }
    )
    blueprint_path = mod_dir / "config" / "ai_blueprint.json"
    try:
        blueprint = _facade().json.loads(blueprint_path.read_text(encoding="utf-8"))
        checks.append(
            {
                "id": "blueprint",
                "ok": isinstance(blueprint, dict),
                "message": "ai_blueprint 可读取",
            }
        )
    except RECOVERABLE_ERRORS as e:
        blueprint = {}
        checks.append({"id": "blueprint", "ok": False, "message": str(e)})
    linked_ids = {
        int(x.get("workflow_id"))
        for x in workflow_results
        if isinstance(x, dict) and x.get("workflow_id")
    }
    manifest_entries = data.get("workflow_employees") if isinstance(data, dict) else []
    missing_links: _facade().List[str] = []
    if isinstance(manifest_entries, list):
        for item in manifest_entries:
            if not isinstance(item, dict):
                continue
            wid = item.get("workflow_id")
            if wid and int(wid) not in linked_ids:
                missing_links.append(str(wid))
    checks.append(
        {
            "id": "workflow_links",
            "ok": not missing_links,
            "message": (
                "workflow_employees 已对齐"
                if not missing_links
                else f"未找到工作流: {', '.join(missing_links)}"
            ),
        }
    )
    py_warnings = _facade().mod_compileall_warnings(mod_dir)
    checks.append(
        {
            "id": "python_compile",
            "ok": not py_warnings,
            "message": "Python 路由骨架可编译" if not py_warnings else "；".join(py_warnings),
        }
    )
    return {"ok": all((bool(c.get("ok")) for c in checks)), "checks": checks}


# --- from mod_scaffold_runner_part04_part01_part01.py ---
"""Implementation extracted from the public facade module."""


async def run_mod_suite_ai_scaffold_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    suggested_id: _facade().Optional[str] = None,
    replace: bool = True,
    industry_id: _facade().Optional[str] = None,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    generate_frontend: bool = True,
    enable_vibe_heal: bool = True,
    manifest_override: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """
    文档/需求驱动的一体化 Mod 生成：manifest + ai_blueprint + 员工路由骨架，
    并为每个员工创建工作流后回写 workflow_id。

    ``generate_frontend`` 之前是 NameError 导致仓库页 AI 脚手架直接挂；现在补默认。
    ``enable_vibe_heal`` 控制是否在导入后调用 vibe-coding 的 ``heal_project`` 自愈一轮。
    ``manifest_override`` 当前端已通过 AI 流水线生成完整 manifest 时直接传入，
    跳过蓝图生成阶段，避免用户编辑被覆盖。
    """
    if manifest_override and isinstance(manifest_override, dict):
        gen: _facade().Dict[str, _facade().Any] = {
            "ok": True,
            "parsed": manifest_override,
        }
    else:
        gen = await _facade().generate_mod_suite_blueprint_async(
            db,
            user,
            brief=brief,
            suggested_id=suggested_id,
            provider=provider,
            model=model,
        )
    if not gen.get("ok"):
        return gen
    imported = _facade().import_mod_suite_repository(
        db,
        user,
        parsed=gen["parsed"],
        replace=replace,
        generate_frontend=generate_frontend,
    )
    if not imported.get("ok"):
        return imported
    dest = _facade().Path(imported["path"])
    manifest = imported["manifest"]
    employees = imported.get("employees") or []
    blueprint = imported.get("blueprint") or {}
    industry_card = _facade().write_mod_suite_industry_card(dest, blueprint)
    ui_shell = _facade().write_mod_suite_ui_shell(dest, blueprint)
    wf = await _facade().create_mod_suite_workflows_async(
        db,
        user,
        mod_dir=dest,
        employees=employees,
        brief=brief,
        provider=gen.get("provider"),
        model=gen.get("model"),
    )
    workflow_results = wf.get("workflow_results") or []
    workflow_sandbox = _facade().run_mod_suite_workflow_sandboxes(db, user, workflow_results)
    api_summary = {
        "nodes": wf.get("api_nodes") or [],
        "warnings": wf.get("api_warnings") or [],
    }
    employee_readiness = _facade().analyze_mod_employee_readiness(db, user, dest)
    pack_registration: _facade().Dict[str, _facade().Any] = {
        "registered": [],
        "errors": [],
    }
    if employees:
        try:
            pack_registration = await _facade().register_mod_employee_packs_async(
                db,
                user,
                mod_dir=dest,
                workflow_results=workflow_results,
                industry=str(manifest.get("industry") or "通用"),
            )
        except RECOVERABLE_ERRORS:
            import logging

            logging.getLogger(__name__).exception(
                "register_mod_employee_packs_async failed in ai-scaffold"
            )
    graph_patch_result = _facade().patch_workflow_graph_employee_nodes(
        db, user, mod_dir=dest, workflow_results=workflow_results
    )
    vibe_index_summary = (
        await _facade().asyncio.to_thread(
            _facade()._index_mod_with_vibe,
            db,
            user,
            mod_dir=dest,
            provider=gen.get("provider") or "",
            model=gen.get("model") or "",
        )
        if enable_vibe_heal
        else {"enabled": False}
    )
    _facade().write_mod_suite_blueprint(
        dest,
        blueprint,
        workflow_results,
        industry_card=industry_card,
        ui_shell=ui_shell,
        api_summary=api_summary,
        workflow_sandbox=workflow_sandbox,
        employee_readiness=employee_readiness,
        vibe_index=vibe_index_summary,
    )
    chosen_industry = str(industry_id or "").strip()
    if chosen_industry and chosen_industry != "通用":
        try:
            from modman.industry_presets import apply_industry_to_mod_dir
            from modman.manifest_util import read_manifest as _read_manifest

            apply_industry_to_mod_dir(dest, chosen_industry)
            data, err = _read_manifest(dest)
            if not err and data:
                manifest = data
        except RECOVERABLE_ERRORS:
            import logging

            logging.getLogger(__name__).exception(
                "apply_industry_to_mod_dir failed for %s", chosen_industry
            )
    mod_sandbox = _facade().run_mod_suite_mod_sandbox(dest, workflow_results)
    validation_summary = _facade()._suite_validation_summary(dest, workflow_results)
    validation_summary["mod_sandbox"] = mod_sandbox
    validation_summary["api_warnings"] = api_summary["warnings"]
    validation_summary["employee_readiness"] = employee_readiness
    validation_summary["vibe_index"] = vibe_index_summary
    validation_summary["pack_registration"] = pack_registration
    data, err = (None, None)
    try:
        from modman.manifest_util import read_manifest

        data, err = read_manifest(dest)
    except RECOVERABLE_ERRORS:
        data, err = (None, None)
    return {
        "ok": True,
        "id": dest.name,
        "path": str(dest),
        "manifest": data or manifest,
        "workflow_results": workflow_results,
        "blueprint": blueprint,
        "industry_card": industry_card,
        "ui_shell": ui_shell,
        "api_summary": api_summary,
        "workflow_sandbox": workflow_sandbox,
        "employee_readiness": employee_readiness,
        "graph_patch": graph_patch_result,
        "mod_sandbox": mod_sandbox,
        "validation_summary": validation_summary,
        "vibe_index": vibe_index_summary,
    }


def _index_mod_with_vibe(
    db: _facade().Session,
    user: _facade().User,
    *,
    mod_dir: _facade().Path,
    provider: str,
    model: str,
) -> _facade().Dict[str, _facade().Any]:
    """同步辅助:用 vibe-coding 的 ``ProjectVibeCoder.index_project`` 缓存索引。

    任何失败都视为可降级,只把 reason 留在返回值,不阻塞 Mod 流水线。
    """
    if not provider or not model:
        return {"enabled": False, "reason": "缺少 provider/model,跳过 vibe 索引"}
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
            get_project_vibe_coder,
        )
    except ImportError as exc:
        return {"enabled": False, "reason": f"integrations 未导入: {exc}"}
    try:
        coder = get_project_vibe_coder(
            mod_dir, session=db, user_id=user.id, provider=provider, model=model
        )
    except VibeIntegrationError as exc:
        return {"enabled": False, "reason": str(exc)}
    except RECOVERABLE_ERRORS as exc:
        return {"enabled": False, "reason": f"vibe coder 构造失败: {exc}"}
    try:
        idx = coder.index_project(refresh=True)
    except RECOVERABLE_ERRORS as exc:
        return {"enabled": True, "ok": False, "reason": f"index_project 失败: {exc}"}
    summary: _facade().Dict[str, _facade().Any] = {"enabled": True, "ok": True}
    try:
        if hasattr(idx, "summary") and callable(idx.summary):
            summary["summary"] = idx.summary()
        else:
            summary["summary"] = {
                "files": getattr(idx, "files_count", None) or len(getattr(idx, "files", []) or [])
            }
    except RECOVERABLE_ERRORS as exc:
        summary["summary"] = {"error": f"index summary 取数失败: {exc}"}
    return summary


async def attach_nl_workflow_to_employee_pack_dir(
    db: _facade().Session,
    user: _facade().User,
    *,
    pack_dir: _facade().Path,
    brief: str,
    workflow_name: _facade().Optional[str],
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
    status_hook: _facade().Optional[_facade().Callable[..., _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """在已落盘的员工包目录上创建画布工作流、NL 生图，并把 ``workflow_id`` 写回 manifest。

    改进：在调用 apply_nl_workflow_graph 之前，先把员工包 .py 注册为真实可执行 ESkill，
    生成的 preset_eskill_nodes 传给 NL 图生成器，画布节点将直接引用真脚本 Skill。
    若注册失败（vibe-coding 未安装/无脚本），自动退化为旧行为。
    """
    from modstore_server.workflow_nl_graph import apply_nl_workflow_graph

    name = ((workflow_name or "").strip() or f"员工包工作流 {pack_dir.name}")[:256]
    panel_summary = ""
    mf_path = pack_dir / "manifest.json"
    if mf_path.is_file():
        try:
            _mf_raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
            rows = _mf_raw.get("workflow_employees")
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                panel_summary = str(rows[0].get("panel_summary") or "").strip()
        except RECOVERABLE_ERRORS:
            pass
    eskill_specs: list[dict] = []
    try:
        from modstore_server.employee_skill_register import register_employee_pack_as_eskills

        eskill_specs = await register_employee_pack_as_eskills(
            db,
            user,
            pack_dir=pack_dir,
            brief=(brief or "").strip(),
            panel_summary=panel_summary,
            provider=provider,
            model=model,
            status_hook=status_hook,
        )
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.warning("员工 Skill 注册失败，退化为旧 NL 图行为: %s", exc)
    wf = _facade().Workflow(
        user_id=user.id,
        name=name,
        description=(brief or "").strip()[:4000] or "由工作台「做员工」生成的单员工工作流",
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    target_pack_id = pack_dir.name
    target_label = pack_dir.name
    try:
        mf_for_target = (
            _facade().json.loads(mf_path.read_text(encoding="utf-8")) if mf_path.is_file() else {}
        )
        target_pack_id = str(mf_for_target.get("id") or pack_dir.name).strip() or pack_dir.name
        emp_obj = (
            mf_for_target.get("employee") if isinstance(mf_for_target.get("employee"), dict) else {}
        )
        target_label = (
            str(emp_obj.get("label") or mf_for_target.get("name") or target_pack_id).strip()
            or target_pack_id
        )
    except RECOVERABLE_ERRORS:
        pass
    nl = await apply_nl_workflow_graph(
        db,
        user,
        workflow_id=wf.id,
        brief=(brief or "单员工任务流").strip(),
        provider=provider,
        model=model,
        status_hook=status_hook,
        preset_eskill_nodes=eskill_specs or None,
        target_employee_pack_id=target_pack_id,
        target_employee_label=target_label,
    )
    fallback_graph = _facade()._ensure_minimal_employee_workflow_graph(
        db,
        wf.id,
        employee_id=target_pack_id,
        employee_label=target_label,
        task=brief or "根据工作流输入完成员工任务",
    )
    mf = pack_dir / "manifest.json"
    if not mf.is_file():
        return {"ok": False, "error": "manifest.json 缺失", "workflow_id": wf.id}
    try:
        raw = _facade().json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, _facade().json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e), "workflow_id": wf.id}
    rows = raw.get("workflow_employees")
    panel_summary = panel_summary or ""
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        rows[0] = {**rows[0], "workflow_id": wf.id}
        panel_summary = panel_summary or str(rows[0].get("panel_summary") or "").strip()
        raw["workflow_employees"] = rows
    v2 = raw.get("employee_config_v2")
    if isinstance(v2, dict):
        collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}
        workflow = collab.get("workflow") if isinstance(collab.get("workflow"), dict) else {}
        workflow = {**workflow, "workflow_id": wf.id}
        v2["collaboration"] = {**collab, "workflow": workflow}
        cognition = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
        agent = cognition.get("agent") if isinstance(cognition.get("agent"), dict) else {}
        if panel_summary and (not str(agent.get("system_prompt") or "").strip()):
            agent = {**agent, "system_prompt": panel_summary}
            cognition = {**cognition, "agent": agent}
            v2["cognition"] = cognition
        raw["employee_config_v2"] = v2
    raw["workflow_attachment"] = {
        "workflow_id": wf.id,
        "nl_graph_ok": bool(nl.get("ok")),
        "nodes_created": int(nl.get("nodes_created") or 0),
        "fallback_graph": fallback_graph,
        "eskills": [
            {
                "eskill_id": s["eskill_id"],
                "name": s["name"],
                "vibe_skill_id": s["vibe_skill_id"],
            }
            for s in eskill_specs
        ],
    }
    try:
        from modstore_server.employee_pack_workflow_bundle import embed_workflow_bundles_in_manifest

        embed_workflow_bundles_in_manifest(db, raw)
    except RECOVERABLE_ERRORS as _bundle_exc:
        _facade().logger.warning(
            "attach_nl_workflow: embed bundles failed wf_id=%d: %s", wf.id, _bundle_exc
        )
    mf.write_text(_facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        from modstore_server.employee_asset_pipeline import reconcile_employee_pack_manifest

        reconcile_employee_pack_manifest(pack_dir, brief=(brief or "").strip())
    except RECOVERABLE_ERRORS as _rec_exc:
        _facade().logger.warning("attach_nl_workflow: manifest reconcile failed: %s", _rec_exc)
    return {
        "ok": True,
        "automation_complete": True,
        "workflow_id": wf.id,
        "nl": nl,
        "eskill_count": len(eskill_specs),
    }


# --- from mod_scaffold_runner_part04_part01_part02.py ---
"""Implementation extracted from the public facade module."""


