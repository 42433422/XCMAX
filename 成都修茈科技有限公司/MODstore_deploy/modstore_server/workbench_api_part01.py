# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib
from typing import Literal


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _contains_uploaded_docx(raw_files: _facade().Any) -> bool:
    """Return whether the normalized upload payload contains a Word document."""
    if not isinstance(raw_files, (list, tuple)):
        return False
    for item in raw_files:
        if isinstance(item, dict):
            filename = item.get("filename") or item.get("name") or ""
        else:
            filename = getattr(item, "filename", "") or getattr(item, "name", "")
        if str(filename).strip().lower().endswith(".docx"):
            return True
    return False


def _canonical_workbench_intent(intent: _facade().Optional[str]) -> str:
    s = (intent or "").strip().lower()
    if s == "workflow":
        return _facade().CANVAS_SKILL_INTENT
    return s


def _employee_asset_publish_catalog_from_env() -> bool:
    """资产驱动「做员工」是否在生成后写入 ``packages.json`` + ``catalog_items``（默认否，以保持既有测试）。

    部署可设 ``MODSTORE_EMPLOYEE_ASSET_PUBLISH_CATALOG=1``，生成即登记，避免 ``/manifest`` 404。
    """
    return (
        _facade().os.environ.get("MODSTORE_EMPLOYEE_ASSET_PUBLISH_CATALOG") or ""
    ).strip().lower() in ("1", "true", "yes", "on")


def _enrich_artifact_skill_aliases(
    artifact: _facade().Optional[_facade().Dict[str, _facade().Any]]
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    if not artifact or not isinstance(artifact, dict):
        return artifact
    out = dict(artifact)
    wid = out.get("workflow_id")
    if wid is not None:
        out.setdefault("skill_group_id", wid)
    wn = out.get("workflow_name")
    if wn is not None:
        out.setdefault("skill_group_name", wn)
    return out


def _workbench_session_store_dir() -> _facade().Path:
    d = _facade().Path(__file__).resolve().parent / "data" / "workbench_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _workbench_session_file(sid: str) -> _facade().Path:
    s = str(sid or "").strip().lower()
    if len(s) < 16 or len(s) > 32 or any((c not in "0123456789abcdef" for c in s)):
        raise ValueError("invalid session id")
    return _facade()._workbench_session_store_dir() / f"{s}.json"


def _persist_workbench_session_unlocked(sid: str) -> None:
    """多 worker / 多进程时内存 dict 不共享，落盘以便 GET 轮询命中任意进程可读。"""
    sess = _facade().WORKBENCH_SESSIONS.get(sid)
    if not sess:
        return
    try:
        path = _facade()._workbench_session_file(sid)
    except ValueError:
        return
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            _facade().json.dumps(sess, ensure_ascii=False, default=str), encoding="utf-8"
        )
        tmp.replace(path)
    except OSError:
        pass


def _load_workbench_session_unlocked(
    sid: str,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    try:
        path = _facade()._workbench_session_file(sid)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        raw = _facade().json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, _facade().json.JSONDecodeError):
        return None


def _hydrate_workbench_session_unlocked(sid: str) -> None:
    if sid in _facade().WORKBENCH_SESSIONS:
        return
    loaded = _facade()._load_workbench_session_unlocked(sid)
    if loaded and str(loaded.get("id") or "") == str(sid):
        if loaded.get("intent") == "workflow":
            loaded["intent"] = _facade().CANVAS_SKILL_INTENT
        _facade().WORKBENCH_SESSIONS[sid] = loaded


async def _persist_workbench_session(sid: str) -> None:
    async with _facade()._SESSION_LOCK:
        _facade()._persist_workbench_session_unlocked(sid)


class EmployeeAiDraftBody(_facade().BaseModel):
    brief: str = _facade().Field(..., min_length=3, max_length=8000)
    provider: _facade().Optional[str] = _facade().Field(None, max_length=64)
    model: _facade().Optional[str] = _facade().Field(None, max_length=128)
    suggested_id: _facade().Optional[str] = _facade().Field(None, max_length=64)


class EmployeeAiRefinePromptBody(_facade().BaseModel):
    current_prompt: str = _facade().Field(..., min_length=1, max_length=16000)
    instruction: str = _facade().Field(..., min_length=3, max_length=2000)
    role_context: str = _facade().Field("", max_length=500)
    provider: _facade().Optional[str] = _facade().Field(None, max_length=64)
    model: _facade().Optional[str] = _facade().Field(None, max_length=128)


class WorkbenchResearchBody(_facade().BaseModel):
    brief: str = _facade().Field(..., min_length=3, max_length=4000)
    intent: Literal["workflow", "mod", "employee", "skill"] = "skill"
    max_repos: int = _facade().Field(3, ge=1, le=5)
    max_web: int = _facade().Field(6, ge=1, le=12, description="Tavily 网页摘要条数上限")
    max_chars: int = _facade().Field(8000, ge=2000, le=20000)


class WorkbenchWebSearchBody(_facade().BaseModel):
    query: str = _facade().Field(..., min_length=2, max_length=500)
    max_results: int = _facade().Field(8, ge=1, le=12)
    max_chars: int = _facade().Field(8000, ge=1000, le=12000)


class WorkbenchSessionCreateBody(_facade().BaseModel):
    model_config = _facade().ConfigDict(extra="ignore")
    intent: Literal["mod", "employee", "workflow", "skill"]
    brief: str = _facade().Field(..., min_length=3, max_length=30000)
    workflow_name: _facade().Optional[str] = _facade().Field(None, max_length=256)
    skill_group_name: _facade().Optional[str] = _facade().Field(
        None,
        max_length=256,
        description="画布 Skill 组名称；若填且未填 workflow_name，则写入 workflow_name",
    )
    plan_notes: _facade().Optional[str] = _facade().Field("", max_length=4000)
    suggested_mod_id: _facade().Optional[str] = _facade().Field(None, max_length=64)
    replace: bool = True
    provider: _facade().Optional[str] = _facade().Field(None, max_length=64)
    model: _facade().Optional[str] = _facade().Field(None, max_length=128)
    generate_workflow_graph: bool = _facade().Field(
        True,
        description="为画布 intent（skill，旧称 workflow）时是否用 LLM 生成节点与边（false 则仅创建空 Skill 组容器）",
    )
    generate_full_suite: bool = _facade().Field(
        True, description="为 mod intent 时是否生成 Mod + 员工 + 工作流绑定的一体化套件"
    )
    generate_frontend: bool = _facade().Field(
        True, description="为 mod intent 时是否生成定制 Vue 前端页面；false 时仅保留最小前端占位"
    )
    planning_messages: _facade().List[_facade().Dict[str, _facade().Any]] = _facade().Field(
        default_factory=list
    )
    execution_checklist: _facade().List[str] = _facade().Field(default_factory=list)
    source_documents: _facade().List[_facade().Dict[str, _facade().Any]] = _facade().Field(
        default_factory=list
    )
    execution_mode: Literal["workflow", "script"] = "workflow"
    employee_target: Literal["pack_only", "pack_plus_workflow"] = _facade().Field(
        "pack_only",
        description="做员工：pack_only 仅生成包体；pack_plus_workflow 额外创建画布工作流并写回 manifest",
    )
    employee_workflow_name: _facade().Optional[str] = _facade().Field(
        None, max_length=256, description="pack_plus_workflow 时画布工作流名称（可选）"
    )
    fhd_base_url: _facade().Optional[str] = _facade().Field(
        None,
        max_length=512,
        description="可选 FHD 宿主根 URL，用于编排末尾 GET /api/mods/ 连通性探测",
    )
    embed_script_workflow: bool = _facade().Field(
        False,
        description="做员工：在生成员工包之前先走脚本生成/沙箱 pipeline，落库 ScriptWorkflow 并把 workflow_id 写入 employee_config_v2.collaboration.script_workflows",
    )

    @_facade().field_validator("intent", mode="before")
    @classmethod
    def _session_intent_alias(cls, v: object) -> object:
        if isinstance(v, str) and v.strip().lower() == "workflow":
            return _facade().CANVAS_SKILL_INTENT
        return v

    @_facade().model_validator(mode="before")
    @classmethod
    def _skill_group_name_merge(cls, data: _facade().Any) -> _facade().Any:
        if not isinstance(data, dict):
            return data
        wn = (data.get("workflow_name") or "").strip()
        sg = (data.get("skill_group_name") or "").strip()
        if not wn and sg:
            data["workflow_name"] = sg
        return data

    @_facade().field_validator("execution_checklist", mode="before")
    @classmethod
    def _coerce_execution_checklist(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [str(x) for x in v]

    @_facade().field_validator("planning_messages", mode="before")
    @classmethod
    def _coerce_planning_messages(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [x for x in v if isinstance(x, dict)]

    @_facade().field_validator("source_documents", mode="before")
    @classmethod
    def _coerce_source_documents(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [x for x in v if isinstance(x, dict)]


def _parse_workbench_session_create(
    meta: _facade().Dict[str, _facade().Any]
) -> WorkbenchSessionCreateBody:
    """解析工作台创建会话体；把 Pydantic 校验失败转成可读中文 detail。"""
    try:
        return _facade().WorkbenchSessionCreateBody.model_validate(meta)
    except _facade().ValidationError as e:
        parts: _facade().List[str] = []
        for err in e.errors():
            loc = ".".join((str(x) for x in err.get("loc", ()) if str(x) != "body"))
            msg = str(err.get("msg") or "").strip()
            if loc:
                parts.append(f"{loc}: {msg}")
            elif msg:
                parts.append(msg)
        detail = "；".join(parts)[:1800] if parts else str(e)
        raise _facade().HTTPException(
            status_code=422, detail=f"工作台请求参数无效：{detail}"
        ) from e


def _default_steps(
    intent: str, execution_mode: str = "workflow", *, employee_target: str = "pack_only"
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    intent = _facade()._canonical_workbench_intent(intent)
    if execution_mode == "script":
        return [
            {"id": "spec", "label": "理解任务", "status": "pending", "message": None},
            {"id": "generate", "label": "生成处理脚本", "status": "pending", "message": None},
            {"id": "validate", "label": "安全检查", "status": "pending", "message": None},
            {"id": "run", "label": "运行并生成文件", "status": "pending", "message": None},
            {"id": "complete", "label": "完成", "status": "pending", "message": None},
        ]
    if intent == "mod":
        return [
            {"id": "spec", "label": "理解需求", "status": "pending", "message": None},
            {"id": "manifest", "label": "生成蓝图与 JSON", "status": "pending", "message": None},
            {"id": "repo", "label": "新建 Mod 仓库", "status": "pending", "message": None},
            {"id": "industry", "label": "生成行业卡片", "status": "pending", "message": None},
            {"id": "employees", "label": "创建员工骨架", "status": "pending", "message": None},
            {"id": "employee_impls", "label": "生成员工脚本", "status": "pending", "message": None},
            {
                "id": "workflows",
                "label": "生成员工 Skill 组（画布编排）",
                "status": "pending",
                "message": None,
            },
            {
                "id": "register_packs",
                "label": "登记员工包并修复图",
                "status": "pending",
                "message": None,
            },
            {"id": "api", "label": "生成/绑定 API 节点", "status": "pending", "message": None},
            {
                "id": "workflow_sandbox",
                "label": "工作流沙箱测试",
                "status": "pending",
                "message": None,
            },
            {"id": "mod_sandbox", "label": "Mod 沙箱测试", "status": "pending", "message": None},
            {"id": "complete", "label": "完成", "status": "pending", "message": None},
        ]
    base = [
        {"id": "spec", "label": "理解需求", "status": "pending", "message": None},
        {"id": "generate", "label": "生成产物", "status": "pending", "message": None},
        {"id": "validate", "label": "服务端校验", "status": "pending", "message": None},
    ]
    if intent == "employee":
        base.insert(
            1,
            {
                "id": "employee_plan",
                "label": "规划一站式员工",
                "status": "pending",
                "message": None,
            },
        )
        base.extend(
            [
                {
                    "id": "script_workflow",
                    "label": "生成配套小程序",
                    "status": "pending",
                    "message": None,
                },
                {"id": "embed_script", "label": "绑定到员工", "status": "pending", "message": None},
            ]
        )
        if (employee_target or "").strip().lower() == "pack_plus_workflow":
            base.extend(
                [
                    {
                        "id": "workflow",
                        "label": "生成自动化流程",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "register_pack",
                        "label": "登记员工包",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "workflow_sandbox",
                        "label": "流程沙箱测试",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "mod_sandbox",
                        "label": "包体与 Python 校验",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "standalone_smoke",
                        "label": "独立可执行自检",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "host_check",
                        "label": "宿主连通性检查",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "six_dim_gate",
                        "label": "六维质量评估",
                        "status": "pending",
                        "message": None,
                    },
                ]
            )
        else:
            base.extend(
                [
                    {
                        "id": "workflow",
                        "label": "生成自动化流程",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "register_pack",
                        "label": "登记员工包",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "workflow_sandbox",
                        "label": "流程沙箱测试",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "mod_sandbox",
                        "label": "包体与 Python 校验",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "standalone_smoke",
                        "label": "独立可执行自检",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "host_check",
                        "label": "宿主连通性检查",
                        "status": "pending",
                        "message": None,
                    },
                    {
                        "id": "six_dim_gate",
                        "label": "六维质量评估",
                        "status": "pending",
                        "message": None,
                    },
                ]
            )
    base.append({"id": "complete", "label": "完成", "status": "pending", "message": None})
    if intent == _facade().CANVAS_SKILL_INTENT:
        base[1]["label"] = "创建 Skill 组"
    return base


async def _set_step(
    sid: str,
    step_id: str,
    status: str,
    message: _facade().Optional[_facade().Union[str, dict]] = None,
) -> None:
    """Update a workbench step.

    ``message`` may now be either a plain string (legacy) or a structured
    dict with keys: ``summary``, ``round``, ``current_tool``, ``todos``,
    ``slow_hint``.  The Vue frontend uses ``summary`` as the fallback text
    when it encounters a dict.

    ``status`` may be: pending / running / done / skipped / error.
    ``skipped`` is distinct from ``done`` — it means the step was not
    applicable and was bypassed, not that it completed successfully.
    """
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(sid)
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
        if not sess:
            return
        for s in sess["steps"]:
            if s["id"] == step_id:
                prev_status = s.get("status")
                if prev_status in ("done", "error") and status not in ("done", "error", "skipped"):
                    break
                if prev_status == "running" and status == "pending":
                    break
                s["status"] = status
                if message is not None:
                    s["message"] = message
                if status == "running" and prev_status != "running":
                    s["started_at"] = (
                        _facade().datetime.now(_facade().timezone.utc).isoformat() + "Z"
                    )
                elif status in ("done", "error", "skipped"):
                    s.pop("started_at", None)
                break
        _facade()._persist_workbench_session_unlocked(sid)
    if status in ("done", "error", "skipped"):
        _facade()._record_craft_step_skip_metric(step_id, status, sess)


def _record_craft_step_skip_metric(
    step_id: str, status: str, sess: _facade().Optional[dict]
) -> None:
    if status not in ("skipped",):
        return
    try:
        from modstore_server.craft_executor import (
            _record_craft_execution,
            craft_step_to_employee_id,
        )

        employee_id = craft_step_to_employee_id(step_id)
        if not employee_id:
            return
        user_id = 0
        if sess:
            user_id = sess.get("user_id", 0)
        _record_craft_execution(
            employee_id=employee_id,
            user_id=user_id,
            task=f"craft pipeline step: {step_id}",
            status="skipped",
            duration_ms=0,
            llm_tokens=0,
        )
    except Exception:
        pass


async def _fail_session(sid: str, step_id: str, err: str) -> None:
    msg = (err or "步骤失败").strip()[:1000]
    if step_id == "workflow_sandbox" and msg:
        try:
            from modstore_server.craft_failure_signals import emit_craft_step_failure

            async with _facade()._SESSION_LOCK:
                _facade()._hydrate_workbench_session_unlocked(sid)
                sess = _facade().WORKBENCH_SESSIONS.get(sid) or {}
            emit_craft_step_failure(
                step_id="workflow_sandbox", error=msg, user_id=int(sess.get("user_id") or 0)
            )
        except Exception:
            _facade()._LOG.debug("workflow_sandbox fail signal emit skipped", exc_info=True)
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(sid)
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
        if not sess:
            return
        sess["status"] = "error"
        sess["error"] = msg
        updated = False
        for s in sess["steps"]:
            if s["id"] == step_id and s["status"] == "running":
                s["status"] = "error"
                s["message"] = msg
                updated = True
                break
        if not updated:
            for s in sess["steps"]:
                if s["id"] == step_id:
                    s["status"] = "error"
                    s["message"] = msg
                    break
        _facade()._persist_workbench_session_unlocked(sid)


async def _finalize_session_done(sid: str, artifact: _facade().Dict[str, _facade().Any]) -> None:
    """Atomically write artifact + status=done.

    Guards against the case where a pipeline branch returns early without
    explicitly completing every step: any step still in pending/running is
    force-promoted to done so the frontend never sees status=done alongside
    non-terminal steps (which would cause premature navigation).

    If the session already ended in ``error`` (e.g. :func:`_fail_session`), this
    function is a no-op so we never overwrite a failure with a false ``done``.
    """
    async with _facade()._SESSION_LOCK:
        _facade()._hydrate_workbench_session_unlocked(sid)
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
        if not sess:
            return
        if sess.get("status") == "error":
            _facade()._LOG.warning(
                "finalize_session_done skipped: session already error sid=%s err=%s",
                sid,
                (sess.get("error") or "")[:200],
            )
            return
        for s in sess.get("steps") or []:
            if s.get("status") not in ("done", "error", "skipped"):
                _facade()._LOG.warning(
                    "workbench session=%s step=%s was still in state=%s at finalize; marking skipped",
                    sid,
                    s.get("id"),
                    s.get("status"),
                )
                s["status"] = "skipped"
                if not s.get("message"):
                    s["message"] = "管线收尾时标记跳过"
                s.pop("started_at", None)
        sess["status"] = "done"
        sess["artifact"] = artifact
        _facade()._persist_workbench_session_unlocked(sid)
