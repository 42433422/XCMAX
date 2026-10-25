"""Auto-merged part* modules (debt24)."""

# mypy: ignore-errors

# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _load_public_module():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


_facade = _load_public_module


# --- from mod_scaffold_runner_part01_part01_part01.py ---
"""Implementation extracted from the public facade module."""


async def run_employee_ai_scaffold_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    replace: bool = True,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    publish_to_catalog: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """
    生成 employee_pack 并导入用户库。商店执行器仍读 CatalogItem；此处产物用于本地库与「员工制作」页继续上架。

    :param publish_to_catalog: 默认 True，保持向后兼容（CLI / 旧脚手架直接调用时仍会写 ``packages.json``
        与 ``catalog_items``）。工作台「做员工」流水线会传 False，仅在 ``library/<pid>`` 落本地工作目录，
        让用户在 ModAuthoring / 员工编辑器里检查后再点 ``/api/workbench/employee-publish`` 发布。
    """
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {"ok": False, "error": "描述过短"}
    from modstore_server.csv_tabular_runtime import is_csv_full_read, is_csv_generate
    from modstore_server.employee_brief_utils import extract_routing_brief
    from modstore_server.excel_tabular_runtime import (
        is_excel_full_read,
        is_excel_generate,
    )
    from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate
    from modstore_server.txt_extract_runtime import is_txt_full_read, is_txt_generate
    from modstore_server.word_extract_runtime import is_word_full_extract
    from modstore_server.word_generate_runtime import is_word_generate

    rb = extract_routing_brief({"brief": brief}, fallback=brief)
    if is_csv_full_read(rb) or is_csv_generate(rb):
        return {
            "ok": False,
            "error": "CSV 读取/生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_excel_full_read(rb) or is_excel_generate(rb):
        return {
            "ok": False,
            "error": "Excel 读取/生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_txt_full_read(rb) or is_txt_generate(rb):
        return {
            "ok": False,
            "error": "TXT 员工必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_pdf_full_read(rb) or is_pdf_generate(rb):
        return {
            "ok": False,
            "error": "PDF 员工必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_word_full_extract(rb):
        return {
            "ok": False,
            "error": "Word 全量提取必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_word_generate(rb):
        return {
            "ok": False,
            "error": "Word 生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
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
    msgs = [
        {"role": "system", "content": _facade().SYSTEM_PROMPT_EMPLOYEE},
        {"role": "user", "content": brief},
    ]
    result = await _facade().chat_dispatch(
        prov, api_key=api_key, base_url=base, model=mdl, messages=msgs, max_tokens=6000
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "upstream error"}
    manifest, perr = _facade().parse_employee_pack_llm_json(str(result.get("content") or ""))
    if perr or not manifest:
        return {"ok": False, "error": perr or "无法解析模型输出"}
    from modstore_server.employee_ai_scaffold import (
        _is_template_brief,
        _validate_skill_quality,
    )

    _v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    _cognition = _v2.get("cognition") if isinstance(_v2.get("cognition"), dict) else {}
    _skills = _cognition.get("skills") if isinstance(_cognition.get("skills"), list) else []
    _emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    _label = str(_emp.get("label") or manifest.get("name") or "").strip()
    _desc = str(manifest.get("description") or "").strip()
    _poor_briefs = sum(
        (
            1
            for sk in _skills
            if isinstance(sk, dict) and _is_template_brief(str(sk.get("brief") or ""))
        )
    )
    if _poor_briefs > 0 and len(_skills) > 0:
        _retry_prompt = f"""上一次生成的员工技能描述质量不足，包含模板化套话。请重新为以下技能生成具体的、有业务语义的 brief 描述。\n每个 brief 必须说明：该技能做什么、处理什么输入、输出什么结果。不要使用'围绕...执行...相关任务'这种套话。\n只输出 JSON 数组，不要 markdown 围栏：\n[{{"name":"技能id","brief":"具体描述"}}]\n\n技能列表：{_facade().json.dumps([{"name": sk.get("name"), "brief": sk.get("brief")} for sk in _skills if isinstance(sk, dict)], ensure_ascii=False)}\n员工名称：{_label}\n员工描述：{_desc}"""
        try:
            _retry_result = await _facade().chat_dispatch(
                prov,
                api_key=api_key,
                base_url=base,
                model=mdl,
                messages=[{"role": "user", "content": _retry_prompt}],
                max_tokens=2000,
            )
            if _retry_result.get("ok"):
                import re as _re

                _retry_raw = _re.sub(
                    "^```(?:json)?\\s*",
                    "",
                    (_retry_result.get("content") or "").strip(),
                    flags=_re.I,
                )
                _retry_raw = _re.sub("\\s*```\\s*$", "", _retry_raw).strip()
                _retry_skills = _facade().json.loads(_retry_raw)
                if isinstance(_retry_skills, list):
                    _name_to_brief = {}
                    for rsk in _retry_skills:
                        if isinstance(rsk, dict):
                            _rn = str(rsk.get("name") or "").strip()
                            _rb = str(rsk.get("brief") or "").strip()
                            if _rn and _rb and (not _is_template_brief(_rb)):
                                _name_to_brief[_rn] = _rb
                    for sk in _skills:
                        if isinstance(sk, dict):
                            _sn = str(sk.get("name") or "").strip()
                            if _sn in _name_to_brief:
                                sk["brief"] = _name_to_brief[_sn]
                    _cognition["skills"] = _validate_skill_quality(
                        _skills, label=_label, description=_desc
                    )
                    _v2["cognition"] = _cognition
                    manifest["employee_config_v2"] = _v2
        except RECOVERABLE_ERRORS:
            _cognition["skills"] = _validate_skill_quality(_skills, label=_label, description=_desc)
            _v2["cognition"] = _cognition
            manifest["employee_config_v2"] = _v2
    pid = str(manifest.get("id") or "").strip()
    lib = _facade().modstore_library_path()
    if (lib / pid).is_dir() and (not replace):
        return {"ok": False, "error": f"包 {pid} 已存在，请传 replace=true 覆盖"}
    raw_zip = _facade().build_employee_pack_zip(pid, manifest)
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
    saved_package: _facade().Dict[str, _facade().Any] = {}
    if publish_to_catalog:
        with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(raw_zip)
            pkg_tmp_path = _facade().Path(tmp.name)
        try:
            from modstore_server.catalog_store import append_package
            from modstore_server.models import CatalogItem

            rec = {
                "id": pid,
                "name": str(manifest.get("name") or pid),
                "version": str(manifest.get("version") or "1.0.0"),
                "description": str(manifest.get("description") or ""),
                "artifact": "employee_pack",
                "industry": str(manifest.get("industry") or "通用"),
                "release_channel": "stable",
                "commerce": {"mode": "free", "price": 0},
                "license": {"type": "personal", "verify_url": None},
            }
            saved_package = append_package(rec, pkg_tmp_path)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pid).first()
            if not row:
                row = CatalogItem(pkg_id=pid, author_id=user.id)
                db.add(row)
            row.version = saved_package.get("version") or rec["version"]
            row.name = saved_package.get("name") or rec["name"]
            row.description = saved_package.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.industry = saved_package.get("industry") or rec["industry"]
            row.stored_filename = saved_package.get("stored_filename") or ""
            row.sha256 = saved_package.get("sha256") or ""
            db.commit()
        finally:
            pkg_tmp_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "id": dest.name,
        "path": str(dest),
        "manifest": manifest,
        "package": saved_package,
        "published": bool(publish_to_catalog and saved_package),
    }


# --- from mod_scaffold_runner_part05_part01_part01.py ---
"""Implementation extracted from the public facade module."""


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


# --- from mod_scaffold_runner_part05_part01_part02.py ---
"""Implementation extracted from the public facade module."""


def patch_workflow_graph_employee_nodes(
    db: _facade().Session,
    user: _facade().User,
    *,
    mod_dir: _facade().Path,
    workflow_results: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    """
    对每条工作流，确保存在 employee 节点且 config.employee_id 与 expected_pack_id 对齐。

    策略：
    - 若图里已有 employee 节点：把 **首个** 节点的 employee_id 覆盖为 expected_pack_id；
      其余保持不动（用户可以在画布手工调整）。
    - 若没有 employee 节点：在 start -> end 路径间 **插入一个** 新 employee 节点，
      连接 start -> employee -> end（若有从 start 直达 end 的边则删除）。
    幂等：已经正确对齐则不写入任何变更。
    """
    from modman.manifest_util import read_manifest
    from modstore_server.models import WorkflowEdge

    data, err = read_manifest(mod_dir)
    if err or not data:
        return {"ok": False, "error": err or "manifest 无效", "patches": []}
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or not rows:
        return {"ok": True, "patches": [], "note": "无员工，无需修图"}
    patches: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for idx, entry in enumerate(rows):
        if not isinstance(entry, dict):
            continue
        wf_id = _facade()._parse_positive_int(entry.get("workflow_id") or entry.get("workflowId"))
        if not wf_id:
            patches.append({"workflow_index": idx, "skipped": "无 workflow_id"})
            continue
        wf = db.query(_facade().Workflow).filter(_facade().Workflow.id == wf_id).first()
        if not wf:
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "skipped": "workflow 不存在",
                }
            )
            continue
        if not getattr(user, "is_admin", False) and int(wf.user_id) != int(user.id):
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "skipped": "当前用户无权修改",
                }
            )
            continue
        expected_pack_id, perr, _pack_manifest = _facade()._resolve_workflow_entry_pack_id(
            mod_dir, data, entry, idx
        )
        if perr or not expected_pack_id:
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "skipped": perr or "无法推导 expected_pack_id",
                }
            )
            continue
        emp_rows = _facade()._employee_node_ids_for_workflow_cfg(db, wf_id)
        if emp_rows:
            first = emp_rows[0]
            cfg = first["cfg"]
            current_eid = str(cfg.get("employee_id") or "").strip()
            if current_eid == expected_pack_id and any(
                (
                    str(x["cfg"].get("employee_id") or "").strip() == expected_pack_id
                    for x in emp_rows
                )
            ):
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "action": "noop",
                        "employee_id": expected_pack_id,
                    }
                )
                continue
            cfg["employee_id"] = expected_pack_id
            if not str(cfg.get("task") or "").strip():
                cfg["task"] = str(entry.get("panel_summary") or "根据工作流上下文完成员工任务")[
                    :400
                ]
            try:
                first["node"].config = _facade().json.dumps(cfg, ensure_ascii=False)
                db.commit()
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "action": "update",
                        "node_id": first["node"].id,
                        "employee_id": expected_pack_id,
                    }
                )
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "error": f"update failed: {e}",
                    }
                )
            continue
        try:
            start = (
                db.query(_facade().WorkflowNode)
                .filter(
                    _facade().WorkflowNode.workflow_id == wf_id,
                    _facade().WorkflowNode.node_type == "start",
                )
                .first()
            )
            end = (
                db.query(_facade().WorkflowNode)
                .filter(
                    _facade().WorkflowNode.workflow_id == wf_id,
                    _facade().WorkflowNode.node_type == "end",
                )
                .first()
            )
            if not start or not end:
                _facade()._ensure_workflow_start_end_skeleton(db, wf_id)
                db.flush()
                start = (
                    db.query(_facade().WorkflowNode)
                    .filter(
                        _facade().WorkflowNode.workflow_id == wf_id,
                        _facade().WorkflowNode.node_type == "start",
                    )
                    .first()
                )
                end = (
                    db.query(_facade().WorkflowNode)
                    .filter(
                        _facade().WorkflowNode.workflow_id == wf_id,
                        _facade().WorkflowNode.node_type == "end",
                    )
                    .first()
                )
            if not start or not end:
                patches.append(
                    {
                        "workflow_index": idx,
                        "workflow_id": wf_id,
                        "skipped": "图缺 start/end，自动补全后仍无法插入员工节点",
                    }
                )
                continue
            emp_node = _facade().WorkflowNode(
                workflow_id=wf_id,
                node_type="employee",
                name=str(entry.get("label") or "员工")[:256],
                config=_facade().json.dumps(
                    {
                        "employee_id": expected_pack_id,
                        "task": str(entry.get("panel_summary") or "根据工作流上下文完成员工任务")[
                            :400
                        ],
                    },
                    ensure_ascii=False,
                ),
                position_x=float(getattr(start, "position_x", 0.0) or 0.0) + 220.0,
                position_y=float(getattr(start, "position_y", 0.0) or 0.0),
            )
            db.add(emp_node)
            db.flush()
            db.query(WorkflowEdge).filter(
                WorkflowEdge.workflow_id == wf_id,
                WorkflowEdge.source_node_id == start.id,
                WorkflowEdge.target_node_id == end.id,
            ).delete(synchronize_session=False)
            db.add(
                WorkflowEdge(
                    workflow_id=wf_id,
                    source_node_id=start.id,
                    target_node_id=emp_node.id,
                    condition="",
                )
            )
            db.add(
                WorkflowEdge(
                    workflow_id=wf_id,
                    source_node_id=emp_node.id,
                    target_node_id=end.id,
                    condition="",
                )
            )
            db.commit()
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "action": "insert",
                    "node_id": emp_node.id,
                    "employee_id": expected_pack_id,
                }
            )
        except RECOVERABLE_ERRORS as e:
            db.rollback()
            patches.append(
                {
                    "workflow_index": idx,
                    "workflow_id": wf_id,
                    "error": f"insert failed: {e}",
                }
            )
    return {"ok": not any(("error" in p for p in patches)), "patches": patches}
