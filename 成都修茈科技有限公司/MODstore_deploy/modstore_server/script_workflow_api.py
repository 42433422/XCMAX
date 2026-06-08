"""脚本即工作流 API：替代 ``workflow_api`` 的图相关端点。

接管的能力：

- ``POST /api/script-workflows/sessions`` —— 携结构化 Brief + 上传文件启动 agent loop，
  以 SSE 形式流式返回 ``context|plan|code|check|run|observe|repair|done|error`` 事件
- ``GET /api/script-workflows/sessions/{sid}`` —— 拉取会话已发生事件 / outcome（轮询 / 重连兼容）
- ``POST /api/script-workflows/sessions/{sid}/feedback`` —— 用户基于已生成产物提改进，
  内部会以 brief + extra hint 重启一轮 agent loop
- ``POST /api/script-workflows/sessions/{sid}/commit`` —— agent 自动验收通过后落库为
  正式 ``ScriptWorkflow``（状态 ``sandbox_testing``，**不会**直接 active）
- ``GET/PUT/DELETE /api/script-workflows[/{id}]`` —— 列表 / 详情 / 元信息编辑 / 删除
- ``POST /api/script-workflows/{id}/sandbox-run`` —— 用户人工沙箱跑（mode=manual_sandbox）
- ``POST /api/script-workflows/{id}/activate`` —— 启用，硬约束：必须有过 successful manual_sandbox run
- ``POST /api/script-workflows/{id}/edit-with-ai`` —— 已保存脚本继续 agent loop 改
- ``POST /api/script-workflows/{id}/run`` —— 生产调用（mode=production，仅 ``active`` 可调）
- ``GET /api/script-workflows/{id}/runs`` —— 历史运行
- ``GET /api/script-workflows/{id}/versions`` —— 历史版本

注：会话存内存，单进程（生产可换 Redis）；连接断开后 ``GET /sessions/{sid}`` 仍可重放历史事件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_key_resolver import resolve_api_key, resolve_base_url
from modstore_server.models import (
    ScriptWorkflow,
    ScriptWorkflowRun,
    ScriptWorkflowVersion,
    User,
)
from modstore_server.script_agent.agent_loop import run_agent_loop
from modstore_server.script_agent.brief import Brief
from modstore_server.script_agent.llm_client import RealLlmClient
from modstore_server.script_agent.sandbox_runner import run_in_sandbox
from modstore_server.workbench_script_runner import DEFAULT_SCRIPT_AGENT_ITERATIONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/script-workflows", tags=["script-workflow"])


# ----------------------------- 会话内存存储 ----------------------------- #


class _Session(Dict[str, Any]):
    """轻量字典：方便 ``sess["events"]`` 之类直接用。"""


SCRIPT_AGENT_SESSIONS: Dict[str, _Session] = {}
_SESSION_LOCK = asyncio.Lock()
_MAX_KEEP_SESSIONS = 200  # 避免内存爆


# ----------------------------- helpers ----------------------------- #


def _resolve_llm_for_user(
    db: Session, user: User, *, hint_provider: Optional[str], hint_model: Optional[str]
) -> Dict[str, Any]:
    """优先使用前端传的 provider/model，其次回落到用户 ``default_llm_json``。

    注意：``user`` 可能是 dependency override 出来的 ``SimpleNamespace``（测试场景）；
    因此直接从 DB 重读 ``User`` 行拿 ``default_llm_json``，避免字段缺失。
    """
    provider = (hint_provider or "").strip()
    model = (hint_model or "").strip()
    if not provider or not model:
        u_row = db.query(User).filter(User.id == user.id).first()
        raw = ((u_row.default_llm_json if u_row else "") or "").strip()
        if raw:
            try:
                prefs = json.loads(raw)
            except json.JSONDecodeError:
                prefs = {}
            provider = provider or str(prefs.get("provider") or "").strip()
            model = model or str(prefs.get("model") or "").strip()
    if not provider or not model:
        raise HTTPException(
            400, "缺少 LLM 配置：请先在「我的密钥」选择默认模型，或在请求里传 provider/model"
        )
    api_key, _src = resolve_api_key(db, user.id, provider)
    if not api_key:
        raise HTTPException(400, f"用户未配置 {provider} 的 API Key")
    base_url = resolve_base_url(db, user.id, provider)
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }


def _build_llm_client(cfg: Dict[str, Any]) -> RealLlmClient:
    return RealLlmClient(
        cfg["provider"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        base_url=cfg.get("base_url"),
        forbid_reasoning_fallback=True,
    )


async def _read_uploads(uploads: List[UploadFile]) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    for f in uploads or []:
        content = await f.read()
        files.append({"filename": f.filename or "upload.bin", "content": content})
    return files


def _gc_sessions() -> None:
    if len(SCRIPT_AGENT_SESSIONS) <= _MAX_KEEP_SESSIONS:
        return
    items = sorted(
        SCRIPT_AGENT_SESSIONS.items(),
        key=lambda kv: kv[1].get("started_at", 0.0),
    )
    drop = len(items) - _MAX_KEEP_SESSIONS
    for sid, _ in items[:drop]:
        SCRIPT_AGENT_SESSIONS.pop(sid, None)


async def _record_event(sid: str, ev_dict: Dict[str, Any]) -> None:
    sess = SCRIPT_AGENT_SESSIONS.get(sid)
    if sess is None:
        return
    sess["events"].append(ev_dict)
    if ev_dict["type"] == "done":
        sess["status"] = "done"
        sess["outcome"] = (ev_dict.get("payload") or {}).get("outcome")
    elif ev_dict["type"] == "error":
        sess["status"] = "error"
        sess["outcome"] = (ev_dict.get("payload") or {}).get("outcome")
        sess["error"] = (ev_dict.get("payload") or {}).get("reason")


async def _stream_agent_loop(
    *,
    sid: str,
    user_id: int,
    brief: Brief,
    files: List[Dict[str, Any]],
    llm_cfg: Dict[str, Any],
) -> AsyncIterator[bytes]:
    """复用：把 agent loop 输出转 SSE 帧并同时存到 session events。"""
    llm = _build_llm_client(llm_cfg)
    first = {"type": "session_started", "iteration": -1, "payload": {"session_id": sid}}
    await _record_event(sid, first)
    yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n".encode("utf-8")

    try:
        async for ev in run_agent_loop(
            brief,
            llm=llm,
            user_id=user_id,
            session_id=sid,
            files=files,
            sandbox_kwargs={
                "provider": llm_cfg["provider"],
                "model": llm_cfg["model"],
                "api_key": llm_cfg["api_key"],
                "base_url": llm_cfg.get("base_url"),
            },
            # 与工作台 run_script_agent_job 一致，避免此处默默只用 agent_loop 默认 4 轮
            max_iterations=DEFAULT_SCRIPT_AGENT_ITERATIONS,
        ):
            evd = ev.to_dict()
            await _record_event(sid, evd)
            yield f"data: {json.dumps(evd, ensure_ascii=False)}\n\n".encode("utf-8")
    except Exception as e:  # noqa: BLE001
        evd = {
            "type": "error",
            "iteration": -1,
            "payload": {"reason": f"agent loop crash: {e}"},
        }
        await _record_event(sid, evd)
        yield f"data: {json.dumps(evd, ensure_ascii=False)}\n\n".encode("utf-8")


# ----------------------------- pydantic ----------------------------- #


class WorkflowSummary(BaseModel):
    id: int
    name: str
    status: str
    brief_goal: str
    created_at: str
    updated_at: str


class CommitSessionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    schema_in: Dict[str, Any] = Field(default_factory=dict)


class FeedbackBody(BaseModel):
    hint: str = Field(..., min_length=1, max_length=4000)


class EditWithAiBody(BaseModel):
    hint: str = Field(..., min_length=1, max_length=4000)
    provider: Optional[str] = None
    model: Optional[str] = None


class UpdateWorkflowBody(BaseModel):
    name: Optional[str] = None
    schema_in: Optional[Dict[str, Any]] = None


# ----------------------------- 会话端点 ----------------------------- #


@router.post(
    "/sessions",
    summary="启动 agent 会话（multipart：brief_json + 文件，SSE 响应）",
)
async def start_session(
    brief_json: str = Form(...),
    provider: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    files: List[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    try:
        brief_data = json.loads(brief_json)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"brief_json 解析失败: {e}") from e
    brief = Brief.from_dict(brief_data)
    if not brief.goal.strip() or not brief.outputs.strip() or not brief.acceptance.strip():
        raise HTTPException(400, "brief 必须包含 goal/outputs/acceptance")

    files_data = await _read_uploads(files)
    llm_cfg = _resolve_llm_for_user(db, user, hint_provider=provider, hint_model=model)

    sid = secrets.token_urlsafe(16)
    async with _SESSION_LOCK:
        SCRIPT_AGENT_SESSIONS[sid] = _Session(
            user_id=user.id,
            brief=brief.to_dict(),
            status="running",
            events=[],
            outcome=None,
            error="",
            started_at=datetime.now(timezone.utc).timestamp(),
            files_meta=[
                {"filename": f["filename"], "size": len(f["content"] or b"")} for f in files_data
            ],
        )
        _gc_sessions()

    return StreamingResponse(
        _stream_agent_loop(
            sid=sid, user_id=user.id, brief=brief, files=files_data, llm_cfg=llm_cfg
        ),
        media_type="text/event-stream",
        headers={
            "X-Script-Session-Id": sid,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions/{sid}", summary="拉取会话状态与全部已发生事件（用于轮询/重连）")
async def get_session(
    sid: str,
    user: User = Depends(_get_current_user),
):
    sess = SCRIPT_AGENT_SESSIONS.get(sid)
    if sess is None:
        raise HTTPException(404, "会话不存在")
    if sess.get("user_id") != user.id and not user.is_admin:
        raise HTTPException(403, "无权访问此会话")
    return {
        "session_id": sid,
        "status": sess.get("status"),
        "events": sess.get("events", []),
        "outcome": sess.get("outcome"),
        "error": sess.get("error", ""),
        "brief": sess.get("brief"),
        "files_meta": sess.get("files_meta", []),
    }


@router.post(
    "/sessions/{sid}/feedback",
    summary="用户给反馈，重启一轮 agent loop（SSE 续流）",
)
async def session_feedback(
    sid: str,
    body: FeedbackBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    sess = SCRIPT_AGENT_SESSIONS.get(sid)
    if sess is None:
        raise HTTPException(404, "会话不存在")
    if sess.get("user_id") != user.id and not user.is_admin:
        raise HTTPException(403, "无权访问此会话")

    brief = Brief.from_dict(sess["brief"])
    # 把 hint 拼到 brief.goal 末尾，再跑一轮（轻量做法，复用同一 sid 但累加 events）
    brief = Brief.from_dict(
        {**brief.to_dict(), "goal": brief.goal + "\n\n[用户补充] " + body.hint.strip()}
    )
    sess["status"] = "running"
    sess["outcome"] = None
    sess["error"] = ""
    llm_cfg = _resolve_llm_for_user(db, user, hint_provider=None, hint_model=None)
    return StreamingResponse(
        _stream_agent_loop(sid=sid, user_id=user.id, brief=brief, files=[], llm_cfg=llm_cfg),
        media_type="text/event-stream",
        headers={"X-Script-Session-Id": sid, "Cache-Control": "no-cache"},
    )


@router.post(
    "/sessions/{sid}/commit",
    summary="会话验收通过后落库为正式脚本工作流（状态 = sandbox_testing）",
)
async def commit_session(
    sid: str,
    body: CommitSessionBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    sess = SCRIPT_AGENT_SESSIONS.get(sid)
    if sess is None:
        raise HTTPException(404, "会话不存在")
    if sess.get("user_id") != user.id and not user.is_admin:
        raise HTTPException(403, "无权访问此会话")
    outcome = sess.get("outcome") or {}
    if not outcome.get("ok"):
        raise HTTPException(400, "会话尚未通过自动验收，无法落库")
    final_code = str(outcome.get("final_code") or "").strip()
    if not final_code:
        raise HTTPException(400, "会话未产出有效脚本")

    wf = ScriptWorkflow(
        user_id=user.id,
        name=body.name.strip(),
        brief_json=json.dumps(sess.get("brief") or {}, ensure_ascii=False),
        script_text=final_code,
        schema_in_json=json.dumps(body.schema_in or {}, ensure_ascii=False),
        status="sandbox_testing",
        agent_session_id=sid,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    version = ScriptWorkflowVersion(
        workflow_id=wf.id,
        version_no=1,
        script_text=final_code,
        plan_md=str(outcome.get("plan_md") or ""),
        agent_log_json=json.dumps(
            {"trace": outcome.get("trace") or [], "iterations": outcome.get("iterations")},
            ensure_ascii=False,
        ),
        is_current=True,
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    return _serialize_workflow(wf, current_version=version)


# ----------------------------- 工作流 CRUD ----------------------------- #


def _serialize_workflow(
    wf: ScriptWorkflow,
    *,
    current_version: Optional[ScriptWorkflowVersion] = None,
) -> Dict[str, Any]:
    try:
        brief = json.loads(wf.brief_json or "{}")
    except json.JSONDecodeError:
        brief = {}
    try:
        schema_in = json.loads(wf.schema_in_json or "{}")
    except json.JSONDecodeError:
        schema_in = {}
    return {
        "id": wf.id,
        "name": wf.name,
        "status": wf.status,
        "brief": brief,
        "schema_in": schema_in,
        "script_text": wf.script_text,
        "agent_session_id": wf.agent_session_id,
        "migrated_from_workflow_id": wf.migrated_from_workflow_id,
        "current_version_id": current_version.id if current_version else None,
        "created_at": wf.created_at.isoformat(),
        "updated_at": wf.updated_at.isoformat(),
    }


def _load_workflow(db: Session, workflow_id: int, user: User) -> ScriptWorkflow:
    wf = db.query(ScriptWorkflow).filter(ScriptWorkflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, "脚本工作流不存在")
    if wf.user_id != user.id and not user.is_admin:
        raise HTTPException(403, "无权访问该脚本工作流")
    return wf


def _current_version(db: Session, workflow_id: int) -> Optional[ScriptWorkflowVersion]:
    return (
        db.query(ScriptWorkflowVersion)
        .filter(
            ScriptWorkflowVersion.workflow_id == workflow_id,
            ScriptWorkflowVersion.is_current.is_(True),
        )
        .first()
    )


@router.get("", summary="列出当前用户的脚本工作流")
async def list_workflows(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(ScriptWorkflow).filter(ScriptWorkflow.user_id == user.id)
    if status:
        q = q.filter(ScriptWorkflow.status == status)
    rows = q.order_by(ScriptWorkflow.updated_at.desc()).all()
    return [_serialize_workflow(r) for r in rows]


@router.get("/{workflow_id}", summary="脚本工作流详情")
async def get_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    cv = _current_version(db, workflow_id)
    return _serialize_workflow(wf, current_version=cv)


@router.put("/{workflow_id}", summary="编辑工作流元信息（不改脚本，要走 edit-with-ai）")
async def update_workflow(
    workflow_id: int,
    body: UpdateWorkflowBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    if body.name is not None:
        wf.name = body.name.strip()
    if body.schema_in is not None:
        wf.schema_in_json = json.dumps(body.schema_in, ensure_ascii=False)
    wf.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(wf)
    return _serialize_workflow(wf)


@router.delete("/{workflow_id}", summary="删除脚本工作流（含版本与运行记录）")
async def delete_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    db.query(ScriptWorkflowRun).filter(ScriptWorkflowRun.workflow_id == wf.id).delete()
    db.query(ScriptWorkflowVersion).filter(ScriptWorkflowVersion.workflow_id == wf.id).delete()
    db.delete(wf)
    db.commit()
    return {"ok": True}


# ----------------------------- 状态流转 ----------------------------- #


@router.post(
    "/{workflow_id}/sandbox-run",
    summary="用户人工沙箱跑（multipart：上传真实输入；mode=manual_sandbox）",
)
async def manual_sandbox_run(
    workflow_id: int,
    files: List[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    if wf.status not in ("sandbox_testing", "active"):
        raise HTTPException(400, f"当前状态 {wf.status} 不支持沙箱试用")
    files_data = await _read_uploads(files)
    llm_cfg = _resolve_llm_for_user(db, user, hint_provider=None, hint_model=None)

    cv = _current_version(db, workflow_id)
    run = ScriptWorkflowRun(
        workflow_id=wf.id,
        version_id=cv.id if cv else None,
        user_id=user.id,
        mode="manual_sandbox",
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    result = await run_in_sandbox(
        user_id=user.id,
        session_id=f"manual_{run.id}",
        script_text=wf.script_text,
        files=files_data,
        provider=llm_cfg["provider"],
        model=llm_cfg["model"],
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg.get("base_url"),
    )

    run.stdout = result.stdout[-8000:]
    run.stderr = result.stderr[-8000:]
    run.outputs_meta_json = json.dumps(result.outputs, ensure_ascii=False)
    run.runtime_sdk_calls_json = json.dumps(result.sdk_calls, ensure_ascii=False)
    if result.timed_out:
        run.status = "timeout"
        run.error_message = "脚本超时"
    elif result.ok and result.outputs:
        run.status = "success"
    else:
        run.status = "failed"
        run.error_message = "; ".join(result.errors) or f"返回码 {result.returncode}"
    run.completed_at = datetime.now(timezone.utc)
    if run.status == "success":
        wf.last_manual_sandbox_run_id = run.id
        wf.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)

    return _serialize_run(run, with_artifacts=True, result=result)


@router.post(
    "/{workflow_id}/activate",
    summary="启用脚本工作流（强校验：必须有过 successful manual_sandbox run）",
)
async def activate_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    if wf.status == "active":
        return _serialize_workflow(wf)
    if wf.status not in ("sandbox_testing",):
        raise HTTPException(400, f"当前状态 {wf.status} 不能启用")
    last_run = None
    if wf.last_manual_sandbox_run_id:
        last_run = (
            db.query(ScriptWorkflowRun)
            .filter(ScriptWorkflowRun.id == wf.last_manual_sandbox_run_id)
            .first()
        )
    if not last_run or last_run.status != "success":
        raise HTTPException(400, "启用前必须至少有一次成功的人工沙箱测试（manual_sandbox-run）")
    wf.status = "active"
    wf.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(wf)
    return _serialize_workflow(wf)


@router.post(
    "/{workflow_id}/deactivate",
    summary="停用脚本工作流（status=deprecated）",
)
async def deactivate_workflow(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    wf.status = "deprecated"
    wf.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(wf)
    return _serialize_workflow(wf)


@router.post(
    "/{workflow_id}/edit-with-ai",
    summary="对已保存脚本继续 agent loop 改（SSE）",
)
async def edit_with_ai(
    workflow_id: int,
    body: EditWithAiBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    try:
        brief_data = json.loads(wf.brief_json or "{}")
    except json.JSONDecodeError:
        brief_data = {}
    brief = Brief.from_dict(brief_data)
    brief = Brief.from_dict(
        {**brief.to_dict(), "goal": brief.goal + "\n\n[用户改进] " + body.hint.strip()}
    )

    llm_cfg = _resolve_llm_for_user(db, user, hint_provider=body.provider, hint_model=body.model)
    sid = secrets.token_urlsafe(16)
    async with _SESSION_LOCK:
        SCRIPT_AGENT_SESSIONS[sid] = _Session(
            user_id=user.id,
            brief=brief.to_dict(),
            status="running",
            events=[],
            outcome=None,
            error="",
            started_at=datetime.now(timezone.utc).timestamp(),
            files_meta=[],
            workflow_id=wf.id,
        )
        _gc_sessions()
    wf.status = "draft"
    wf.agent_session_id = sid
    wf.updated_at = datetime.now(timezone.utc)
    db.commit()

    return StreamingResponse(
        _stream_agent_loop(sid=sid, user_id=user.id, brief=brief, files=[], llm_cfg=llm_cfg),
        media_type="text/event-stream",
        headers={"X-Script-Session-Id": sid, "Cache-Control": "no-cache"},
    )


@router.post(
    "/{workflow_id}/run",
    summary="生产调用（mode=production；仅 active 可调）",
)
async def production_run(
    workflow_id: int,
    files: List[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _load_workflow(db, workflow_id, user)
    if wf.status != "active":
        raise HTTPException(400, "工作流未启用，无法进行生产调用")
    files_data = await _read_uploads(files)
    llm_cfg = _resolve_llm_for_user(db, user, hint_provider=None, hint_model=None)
    cv = _current_version(db, workflow_id)

    run = ScriptWorkflowRun(
        workflow_id=wf.id,
        version_id=cv.id if cv else None,
        user_id=user.id,
        mode="production",
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    result = await run_in_sandbox(
        user_id=user.id,
        session_id=f"prod_{run.id}",
        script_text=wf.script_text,
        files=files_data,
        provider=llm_cfg["provider"],
        model=llm_cfg["model"],
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg.get("base_url"),
    )
    run.stdout = result.stdout[-8000:]
    run.stderr = result.stderr[-8000:]
    run.outputs_meta_json = json.dumps(result.outputs, ensure_ascii=False)
    run.runtime_sdk_calls_json = json.dumps(result.sdk_calls, ensure_ascii=False)
    if result.timed_out:
        run.status = "timeout"
        run.error_message = "脚本超时"
    elif result.ok and result.outputs:
        run.status = "success"
    else:
        run.status = "failed"
        run.error_message = "; ".join(result.errors) or f"返回码 {result.returncode}"
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _serialize_run(run, with_artifacts=True, result=result)


# ----------------------------- 历史查询 ----------------------------- #


def _serialize_run(
    run: ScriptWorkflowRun,
    *,
    with_artifacts: bool = False,
    result: Optional[Any] = None,
) -> Dict[str, Any]:
    try:
        outputs = json.loads(run.outputs_meta_json or "[]")
    except json.JSONDecodeError:
        outputs = []
    try:
        sdk_calls = json.loads(run.runtime_sdk_calls_json or "[]")
    except json.JSONDecodeError:
        sdk_calls = []
    payload: Dict[str, Any] = {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "version_id": run.version_id,
        "mode": run.mode,
        "status": run.status,
        "stdout_tail": (run.stdout or "")[-2000:],
        "stderr_tail": (run.stderr or "")[-2000:],
        "outputs": outputs,
        "sdk_calls": sdk_calls,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
    if with_artifacts and result is not None:
        payload["work_dir"] = getattr(result, "work_dir", "")
    return payload


@router.get("/{workflow_id}/runs", summary="历史运行记录")
async def list_runs(
    workflow_id: int,
    mode: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _load_workflow(db, workflow_id, user)
    q = db.query(ScriptWorkflowRun).filter(ScriptWorkflowRun.workflow_id == workflow_id)
    if mode:
        q = q.filter(ScriptWorkflowRun.mode == mode)
    rows = q.order_by(ScriptWorkflowRun.started_at.desc()).limit(limit).offset(offset).all()
    return [_serialize_run(r) for r in rows]


@router.get(
    "/{workflow_id}/runs/{run_id}/files/{filename}",
    summary="下载脚本工作流单次运行产物",
)
async def download_run_file(
    workflow_id: int,
    run_id: int,
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _load_workflow(db, workflow_id, user)
    run = (
        db.query(ScriptWorkflowRun)
        .filter(
            ScriptWorkflowRun.id == run_id,
            ScriptWorkflowRun.workflow_id == workflow_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(404, "运行记录不存在")
    try:
        outputs = json.loads(run.outputs_meta_json or "[]")
    except json.JSONDecodeError:
        outputs = []
    for item in outputs:
        if not isinstance(item, dict):
            continue
        if item.get("filename") != filename:
            continue
        path = Path(str(item.get("path") or "")).resolve()
        try:
            expected_parent = path.parent.parent
            if (
                path.is_file()
                and path.parent.name == "outputs"
                and expected_parent.name.startswith(f"u{user.id}_")
            ):
                return FileResponse(path, filename=filename)
        except Exception:
            pass
    raise HTTPException(404, "产物文件不存在")


@router.get("/{workflow_id}/versions", summary="历史版本")
async def list_versions(
    workflow_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _load_workflow(db, workflow_id, user)
    rows = (
        db.query(ScriptWorkflowVersion)
        .filter(ScriptWorkflowVersion.workflow_id == workflow_id)
        .order_by(ScriptWorkflowVersion.version_no.desc())
        .all()
    )
    return [
        {
            "id": v.id,
            "version_no": v.version_no,
            "is_current": bool(v.is_current),
            "script_text": v.script_text,
            "plan_md": v.plan_md,
            "created_at": v.created_at.isoformat(),
        }
        for v in rows
    ]
