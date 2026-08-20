# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


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
    key, _src = _facade().resolve_api_key(db, user_id, provider)
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
    except RECOVERABLE_ERRORS:
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
    payload: _facade().Dict[str, _facade().Any],
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
    except RECOVERABLE_ERRORS:
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
        except (_facade().asyncio.CancelledError, RECOVERABLE_ERRORS):
            exc = None
        if exc is None:
            return
        _facade()._LOG.exception(
            "workbench pipeline task failed unhandled session=%s err=%s",
            sid,
            exc,
            exc_info=exc,
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
        except RECOVERABLE_ERRORS:
            pass

    return _cb
