# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _employee_pack_workflow_reference_report(
    db: _facade().Session, user: _facade().User, manifest: _facade().Dict[str, _facade().Any]
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
            .filter(_facade().ScriptWorkflow.id == sid, _facade().ScriptWorkflow.user_id == user.id)
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
    db: _facade().Session, user: _facade().User, manifest: _facade().Dict[str, _facade().Any]
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
        except Exception:
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
        except Exception as _e:
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
    from modstore_server.employee_brief_utils import compact_routing_brief, extract_routing_brief
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


async def _build_employee_orchestration_plan(
    db: _facade().Session,
    user_id: int,
    *,
    payload: _facade().Dict[str, _facade().Any],
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.employee_brief_utils import extract_routing_brief
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

    brief = (payload.get("brief") or "").strip()
    routing_brief = extract_routing_brief(payload, fallback=brief)
    from modstore_server.employee_pipeline_routing import (
        resolve_deterministic_orchestration_plan,
        skip_employee_plan_llm,
    )

    det_plan = resolve_deterministic_orchestration_plan(routing_brief, payload)
    if det_plan and skip_employee_plan_llm(payload, routing_brief):
        return det_plan
    if is_txt_full_read(routing_brief) or is_txt_generate(routing_brief):
        return resolve_txt_orchestration_plan(routing_brief, payload)
    if is_pdf_full_read(routing_brief) or is_pdf_generate(routing_brief):
        return resolve_pdf_orchestration_plan(routing_brief, payload)
    if is_word_generate(routing_brief):
        return word_generate_orchestration_plan(routing_brief, payload)
    if is_word_full_extract(routing_brief):
        return word_extract_orchestration_plan(routing_brief, payload)
    fallback = _facade()._fallback_employee_orchestration_plan(routing_brief, payload)
    if not provider or not model:
        return fallback
    (key, _src) = _facade().resolve_api_key(db, user_id, provider)
    if not key:
        return fallback
    checklist = payload.get("execution_checklist")
    messages = payload.get("planning_messages")
    docs = payload.get("source_documents")
    planning_context = {
        "brief": routing_brief,
        "execution_checklist": checklist if isinstance(checklist, list) else [],
        "planning_messages": messages if isinstance(messages, list) else [],
        "source_documents": docs if isinstance(docs, list) else [],
    }
    sys_prompt = "你是 XCAGI「做员工」一站式编排规划器。只输出 JSON 对象，不要 markdown。\n你要把同一个用户需求拆成三份互相一致的 brief：\n1 employee_brief：给员工包生成器，描述角色、边界、输出格式。\n2 script_brief：给 Python 脚本工作流生成器，描述如何读取 inputs/、写 outputs/，没有输入也能空跑生成说明文件。\n3 workflow_brief：给画布 Skill 组生成器，描述多步自动化流程。\n字段必须包含：employee_name, employee_brief, script_workflow_name, script_brief, script_runtime_notes, workflow_name, workflow_brief, acceptance。\nscript_brief 必须明确：只能读 inputs/、只能写 outputs/；如需遍历文件，用 os.walk('inputs')；输出 Markdown 或 JSON 结果文件。\n若需求是 Word 全量提取（段落/表格/图片/样式/元数据），employee_brief 必须要求 direct_python + document_full.json，script_brief 必须要求 python-docx/zipfile 解析，workflow_brief 必须包含上传→解析→校验→交付步骤。\n不要让脚本读取真实磁盘绝对路径，不要要求联网。"
    try:
        res = await _facade().chat_dispatch(
            provider,
            api_key=key,
            base_url=_facade().resolve_base_url(db, user_id, provider),
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {
                    "role": "user",
                    "content": _facade().json.dumps(planning_context, ensure_ascii=False)[:12000],
                },
            ],
            max_tokens=1800,
        )
    except Exception:
        _facade()._LOG.exception("employee orchestration plan LLM failed")
        return fallback
    if not res.get("ok"):
        return fallback
    try:
        data = _facade().json.loads(_facade()._strip_json_fence(str(res.get("content") or "")))
    except _facade().json.JSONDecodeError:
        return fallback
    if not isinstance(data, dict):
        return fallback
    out = {**fallback}
    for k in (
        "employee_name",
        "employee_brief",
        "script_workflow_name",
        "script_brief",
        "script_runtime_notes",
        "workflow_name",
        "workflow_brief",
    ):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    acc = data.get("acceptance")
    if isinstance(acc, list):
        out["acceptance"] = [str(x).strip() for x in acc if str(x).strip()][:8]
    return out


def _planning_record(
    payload: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    """把前端需求规划材料固定进服务端会话，方便审计与重新生成。"""
    messages = payload.get("planning_messages")
    checklist = payload.get("execution_checklist")
    docs = payload.get("source_documents")
    return {
        "brief": (payload.get("brief") or "").strip(),
        "plan_notes": (payload.get("plan_notes") or "").strip(),
        "messages": messages if isinstance(messages, list) else [],
        "execution_checklist": checklist if isinstance(checklist, list) else [],
        "source_documents": docs if isinstance(docs, list) else [],
        "created_at": _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z",
    }


async def _read_workbench_uploads(
    files: _facade().List[_facade().UploadFile],
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    raw_files: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for f in files or []:
        content = await f.read()
        if len(content) > 30 * 1024 * 1024:
            raise _facade().HTTPException(400, f"文件过大: {f.filename}")
        raw_files.append({"filename": f.filename or "upload.bin", "content": content})
    return raw_files


def _commit_script_workflow_from_result(
    db: _facade().Session,
    *,
    user_id: int,
    session_id: str,
    payload: _facade().Dict[str, _facade().Any],
    files: _facade().List[_facade().Dict[str, _facade().Any]],
    result: _facade().Dict[str, _facade().Any],
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """把工作台的一次性脚本结果保存为可继续沙箱调试的脚本工作流。"""
    code = str(result.get("script") or "").strip()
    if not result.get("ok") or not code:
        _facade()._LOG.warning(
            "commit_script_workflow: skip — ok=%s script_len=%d errors=%s session=%s",
            result.get("ok"),
            len(code),
            result.get("errors"),
            session_id,
        )
        return None
    raw_name = str(payload.get("workflow_name") or "").strip()
    if not raw_name:
        raw_name = str(payload.get("brief") or "").strip()[:40] or "Excel 文件处理"
    name = raw_name if raw_name.endswith("脚本工作流") else f"{raw_name} 脚本工作流"
    brief_json = _facade()._script_workflow_brief(payload, files)
    wf = _facade().ScriptWorkflow(
        user_id=user_id,
        name=name[:256],
        brief_json=_facade().json.dumps(brief_json, ensure_ascii=False),
        script_text=code,
        schema_in_json=_facade().json.dumps({}, ensure_ascii=False),
        status="sandbox_testing",
        agent_session_id=session_id,
    )
    db.add(wf)
    db.flush()
    version = _facade().ScriptWorkflowVersion(
        workflow_id=wf.id,
        version_no=1,
        script_text=code,
        plan_md="由工作台附件生成的初始脚本工作流。",
        agent_log_json=_facade().json.dumps(
            {"source": "workbench", "session_id": session_id}, ensure_ascii=False
        ),
        is_current=True,
    )
    db.add(version)
    db.flush()
    run = _facade().ScriptWorkflowRun(
        workflow_id=wf.id,
        version_id=version.id,
        user_id=user_id,
        mode="auto",
        status="success",
        stdout=str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or ""),
        outputs_meta_json=_facade().json.dumps(result.get("outputs") or [], ensure_ascii=False),
        runtime_sdk_calls_json=_facade().json.dumps(
            result.get("sdk_calls") or [], ensure_ascii=False
        ),
        error_message="",
        completed_at=_facade().datetime.now(_facade().timezone.utc),
    )
    db.add(run)
    wf.updated_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    db.refresh(wf)
    return {"id": wf.id, "name": wf.name}


async def _resolve_default_llm_for_pipeline(db: _facade().Any, user_id: int) -> tuple:
    from modstore_server.llm_api import resolve_default_llm_route

    _facade()._LOG.debug("pipeline: provider/model missing, resolving default for user=%s", user_id)
    try:
        resolved = await resolve_default_llm_route(db, user_id)
        rp = str(resolved.get("provider") or "").strip() or None
        rm = str(resolved.get("model") or "").strip() or None
        return (rp, rm)
    except Exception:
        _facade()._LOG.debug(
            "pipeline: resolve_default_llm_route failed, no LLM available for user=%s",
            user_id,
            exc_info=True,
        )
        return (None, None)


def _pipeline_task_failsafe(sid: str) -> _facade().Any:
    """Return a done-callback for asyncio tasks created from _run_pipeline.

    If the task raises an unhandled exception (any branch that forgot try/except),
    this callback marks the session as error and sets the first running step to error,
    preventing the zombie-session where status stays 'running' forever.
    """

    def _cb(task: _facade().asyncio.Task[None]) -> None:
        try:
            exc = task.exception()
        except (_facade().asyncio.CancelledError, Exception):
            exc = None
        if exc is None:
            return
        _facade()._LOG.exception(
            "workbench pipeline task failed unhandled session=%s err=%s", sid, exc, exc_info=exc
        )
        err_msg = f"[内部错误] {type(exc).__name__}: {exc!s}"[:2000]
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
        if not sess:
            return
        if sess.get("status") == "running":
            sess["status"] = "error"
            sess["error"] = err_msg
        for s in sess.get("steps") or []:
            if s.get("status") == "running":
                s["status"] = "error"
                s["message"] = err_msg[:480]
                s.pop("started_at", None)
                break
        try:
            _facade()._persist_workbench_session_unlocked(sid)
        except Exception:
            pass

    return _cb
