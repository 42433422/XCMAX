# mypy: disable-error-code="attr-defined, dict-item, index, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _employee_pack_workflow_reference_report(
    db: _facade().Session,
    user: _facade().User,
    manifest: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, _facade().Any]:
    """Validate workflow/script_workflow ID references against the current DB.

    Employee packs currently package manifest/runtime files only; workflow and
    ScriptWorkflow definitions are not migrated inside the .xcemp.  A manifest
    that references IDs not present in the target DB will install successfully
    but fail at runtime, so export/save records an explicit report.
    """
    workflow_ids: _facade().List[int] = []
    script_workflow_ids: _facade().List[int] = []
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
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}
    wf = collab.get("workflow") if isinstance(collab.get("workflow"), dict) else {}
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
    workflow_found: _facade().List[int] = []
    for wid in workflow_ids:
        row = (
            db.query(_facade().Workflow)
            .filter(_facade().Workflow.id == wid, _facade().Workflow.user_id == user.id)
            .first()
        )
        if row:
            workflow_found.append(wid)
    script_found: _facade().List[int] = []
    for sid in script_workflow_ids:
        row = (
            db.query(_facade().ScriptWorkflow)
            .filter(
                _facade().ScriptWorkflow.id == sid,
                _facade().ScriptWorkflow.user_id == user.id,
            )
            .first()
        )
        if row:
            script_found.append(sid)
    missing_workflows = [wid for wid in workflow_ids if wid not in workflow_found]
    missing_scripts = [sid for sid in script_workflow_ids if sid not in script_found]
    warnings: _facade().List[str] = []
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
    db: _facade().Session,
    user: _facade().User,
    manifest: _facade().Dict[str, _facade().Any],
) -> _facade().List[str]:
    report = _facade()._employee_pack_workflow_reference_report(db, user, manifest)
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    meta = v2.get("metadata") if isinstance(v2.get("metadata"), dict) else {}
    meta["workflow_reference_report"] = report
    meta["workflow_runtime_check"] = (
        "employee_pack 不内嵌 workflow/script_workflow；上线前须确认目标库存在这些 ID 或重新绑定。"
    )
    v2["metadata"] = meta
    manifest["employee_config_v2"] = v2
    return list(report.get("warnings") or [])


def _cleanup_mod_pipeline_resources(
    db: _facade().Session, resources: _facade().List[_facade().Dict[str, _facade().Any]]
) -> None:
    """做 Mod 全流程失败时尽量撤销已创建目录与数据库记录（尽力而为）。"""
    import shutil

    for res in reversed(resources):
        try:
            if res["type"] == "mod_dir":
                p = _facade().Path(res["path"])
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
            elif res["type"] == "workflow_ids":
                for wid in res.get("ids") or []:
                    try:
                        wid_int = int(wid)
                    except (TypeError, ValueError):
                        continue
                    db.query(_facade().WorkflowEdge).filter(
                        _facade().WorkflowEdge.workflow_id == wid_int
                    ).delete(synchronize_session=False)
                    db.query(_facade().WorkflowNode).filter(
                        _facade().WorkflowNode.workflow_id == wid_int
                    ).delete(synchronize_session=False)
                    wf = (
                        db.query(_facade().Workflow)
                        .filter(_facade().Workflow.id == wid_int)
                        .first()
                    )
                    if wf:
                        db.delete(wf)
                db.commit()
            elif res["type"] == "catalog_by_pkg":
                pkg_id = str(res.get("pkg_id") or "").strip()
                if pkg_id:
                    db.query(_facade().CatalogItem).filter(
                        _facade().CatalogItem.pkg_id == pkg_id
                    ).delete(synchronize_session=False)
                    db.commit()
        except RECOVERABLE_ERRORS:
            _facade()._LOG.exception("cleanup pipeline resource failed res=%s", res)


def _script_workflow_brief(
    payload: _facade().Dict[str, _facade().Any],
    files: _facade().List[_facade().Dict[str, _facade().Any]],
) -> _facade().Dict[str, _facade().Any]:
    brief = (payload.get("brief") or "").strip()
    filenames = [str((f or {}).get("filename") or "upload.bin") for f in files or []]
    return {
        "goal": brief,
        "inputs": [{"filename": name, "description": "工作台上传样本文件"} for name in filenames],
        "outputs": "生成处理后的结果文件到 outputs/，用于下载和沙箱复核",
        "acceptance": "脚本运行成功，outputs/ 至少生成一个结果文件",
        "fallback": "",
        "trigger_type": "manual",
        "references": {"source": "workbench-script-session"},
    }


def _embed_script_workflow_in_employee_pack(
    pack_dir: _facade().Path,
    *,
    script_workflow: _facade().Dict[str, _facade().Any],
    brief: str,
    db: _facade().Optional[_facade().Session] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Write ScriptWorkflow linkage into an employee pack manifest in-place.

    When *db* is supplied the function also embeds a portable
    ``script_workflow_bundles`` entry so the pack is self-contained and can be
    installed into a different environment without losing the script definition.
    """
    mf = pack_dir / "manifest.json"
    if not mf.is_file():
        raise FileNotFoundError(f"embed_script: manifest.json 不存在：{mf}")
    try:
        raw = _facade().json.loads(mf.read_text(encoding="utf-8"))
    except (_facade().json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"embed_script: manifest.json 解析失败（{mf}）：{exc}") from exc
    v2 = raw.get("employee_config_v2") if isinstance(raw.get("employee_config_v2"), dict) else {}
    collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}
    entries = collab.get("script_workflows")
    if not isinstance(entries, list):
        entries = []
    sid = script_workflow.get("id")
    sid_int = int(sid) if sid is not None else 0
    entry = {
        "script_workflow_id": sid_int,
        "workflow_id": sid_int,
        "name": str(script_workflow.get("name") or "员工脚本工作流"),
        "trigger_type": "manual",
        "role": "primary_program",
        "description": (brief or "").strip()[:1000],
    }
    deduped: _facade().List[_facade().Any] = []
    for x in entries:
        if not isinstance(x, dict):
            deduped.append(x)
            continue
        try:
            existing_id = int(x.get("script_workflow_id") or x.get("workflow_id") or 0)
        except (TypeError, ValueError):
            existing_id = 0
        if existing_id != sid_int:
            deduped.append(x)
    entries = deduped
    entries.insert(0, entry)
    collab = {**collab, "script_workflows": entries}
    v2["collaboration"] = collab
    raw["employee_config_v2"] = v2
    raw["script_workflow_attachment"] = {
        "script_workflow_id": sid_int,
        "name": entry["name"],
        "trigger_type": entry["trigger_type"],
    }
    if db is not None and sid_int > 0:
        try:
            from modstore_server.employee_pack_workflow_bundle import (
                embed_workflow_bundles_in_manifest,
            )

            embed_workflow_bundles_in_manifest(db, raw)
        except RECOVERABLE_ERRORS as _e:
            _facade()._LOG.warning("embed script workflow bundle failed sid=%d: %s", sid_int, _e)
    _pack_id = str(raw.get("id") or pack_dir.name).strip() or pack_dir.name
    if isinstance(raw.get("employee"), dict):
        raw["employee"]["id"] = _pack_id
    for _wf_row in raw.get("workflow_employees") or []:
        if isinstance(_wf_row, dict):
            _wf_row["id"] = _pack_id
    mf.write_text(_facade().json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return raw["script_workflow_attachment"]


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        import re

        t = re.sub("^```(?:json)?\\s*", "", t, flags=re.I)
        t = re.sub("\\s*```\\s*$", "", t)
    return t.strip()


def _fallback_employee_orchestration_plan(
    brief: str, payload: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.csv_tabular_runtime import (
        is_csv_full_read,
        is_csv_generate,
        resolve_csv_orchestration_plan,
    )
    from modstore_server.employee_brief_utils import (
        compact_routing_brief,
        extract_routing_brief,
    )
    from modstore_server.excel_tabular_runtime import (
        is_excel_full_read,
        is_excel_generate,
        resolve_excel_orchestration_plan,
    )
    from modstore_server.pdf_extract_runtime import (
        is_pdf_full_read,
        is_pdf_generate,
        resolve_pdf_orchestration_plan,
    )
    from modstore_server.txt_extract_runtime import (
        is_txt_full_read,
        is_txt_generate,
        resolve_txt_orchestration_plan,
    )
    from modstore_server.word_extract_runtime import (
        is_word_full_extract,
        word_extract_orchestration_plan,
    )
    from modstore_server.word_generate_runtime import (
        is_word_generate,
        word_generate_orchestration_plan,
    )

    routing_brief = extract_routing_brief(
        payload if isinstance(payload, dict) else {"brief": brief}, fallback=brief
    )
    if is_csv_full_read(routing_brief) or is_csv_generate(routing_brief):
        return resolve_csv_orchestration_plan(routing_brief, payload)
    if is_excel_full_read(routing_brief) or is_excel_generate(routing_brief):
        return resolve_excel_orchestration_plan(routing_brief, payload)
    if is_txt_full_read(routing_brief) or is_txt_generate(routing_brief):
        return resolve_txt_orchestration_plan(routing_brief, payload)
    if is_pdf_full_read(routing_brief) or is_pdf_generate(routing_brief):
        return resolve_pdf_orchestration_plan(routing_brief, payload)
    if is_word_generate(routing_brief):
        return word_generate_orchestration_plan(routing_brief, payload)
    if is_word_full_extract(routing_brief):
        return word_extract_orchestration_plan(routing_brief, payload)
    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join((f"- {x}" for x in checklist if isinstance(x, str)))
        if isinstance(checklist, list)
        else ""
    )
    source_docs = payload.get("source_documents")
    doc_hint = ""
    if isinstance(source_docs, list) and source_docs:
        names = [
            str((x or {}).get("name") or "").strip() for x in source_docs if isinstance(x, dict)
        ]
        doc_hint = "参考资料：" + "、".join([n for n in names if n][:8])
    merged = "\n".join(
        (
            x
            for x in [
                compact_routing_brief(routing_brief, max_len=500) or routing_brief,
                checklist_text,
                doc_hint,
            ]
            if x
        )
    ).strip()
    short = (compact_routing_brief(routing_brief, max_len=40) or "员工助手").strip() or "员工助手"
    bl = (routing_brief or "").lower()
    is_word_extract = any(
        (k in bl for k in ("word", "docx", "doc", "txt", "文本", "文档"))
    ) and any((k in bl for k in ("提取", "解析", "保存", "转换", "全量")))
    script_brief = (
        f"{merged or brief}\n\n请生成 Python 脚本：读取 inputs/ 中的 .doc/.docx 文件，提取全部纯文本，写入 outputs/ 下同名 .txt；无输入时在 outputs/ 写入说明文件。"
        if is_word_extract
        else f"{merged or brief}\n\n请生成配套 Python 脚本：读取 inputs/ 中的文档或数据文件，递归整理可读文本，输出 Markdown 摘要/处理结果到 outputs/；没有输入文件时输出示例说明。"
    )
    script_runtime = (
        "只能读 inputs/、写 outputs/；使用 python-docx 或等价库解析 Word；禁止联网和越界文件访问。"
        if is_word_extract
        else "只能读 inputs/、写 outputs/；允许 os.walk 遍历 inputs；禁止联网和越界文件访问。"
    )
    workflow_brief = (
        f"{merged or brief}\n\nSkill 组流程：接收 Word 上传 → 解析提取全文 → 保存 txt → 交付用户。"
        if is_word_extract
        else f"{merged or brief}\n\n请把该员工拆成可执行 Skill 组：接收输入、读取/归纳、生成结果、人工复核。"
    )
    return {
        "employee_name": short,
        "employee_brief": merged or brief,
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": script_runtime,
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": workflow_brief,
        "acceptance": [
            "员工包可安装并能解释自己的职责",
            "脚本工作流可空跑并生成 outputs/ 结果文件",
            "Skill 组体现输入、处理、输出、复核的顺序",
        ],
    }
