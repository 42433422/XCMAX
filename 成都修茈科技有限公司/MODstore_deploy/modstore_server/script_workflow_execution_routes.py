# ruff: noqa
"""Execution, lifecycle, artifact, and version routes for script workflows."""
from __future__ import annotations
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import ScriptWorkflowRun, ScriptWorkflowVersion, User
from modstore_server.script_agent.brief import Brief
from modstore_server.script_workflow_models import EditWithAiBody


def _facade() -> Any:
    return sys.modules["modstore_server.script_workflow_api"]


router = _facade().router


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
    wf = _facade()._load_workflow(db, workflow_id, user)
    if wf.status not in ("sandbox_testing", "active"):
        raise _facade().HTTPException(400, f"当前状态 {wf.status} 不支持沙箱试用")
    files_data = await _facade()._read_uploads(files)
    llm_cfg = _facade()._resolve_llm_for_user(db, user, hint_provider=None, hint_model=None)
    cv = _facade()._current_version(db, workflow_id)
    run = _facade().ScriptWorkflowRun(
        workflow_id=wf.id,
        version_id=cv.id if cv else None,
        user_id=user.id,
        mode="manual_sandbox",
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    result = await _facade().run_in_sandbox(
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
    run.outputs_meta_json = _facade().json.dumps(result.outputs, ensure_ascii=False)
    run.runtime_sdk_calls_json = _facade().json.dumps(result.sdk_calls, ensure_ascii=False)
    if result.timed_out:
        run.status = "timeout"
        run.error_message = "脚本超时"
    elif result.ok and result.outputs:
        run.status = "success"
    else:
        run.status = "failed"
        run.error_message = "; ".join(result.errors) or f"返回码 {result.returncode}"
    run.completed_at = _facade().datetime.now(_facade().timezone.utc)
    if run.status == "success":
        wf.last_manual_sandbox_run_id = run.id
        wf.updated_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    db.refresh(run)
    return _facade()._serialize_run(run, with_artifacts=True, result=result)


@router.post(
    "/{workflow_id}/activate",
    summary="启用脚本工作流（强校验：必须有过 successful manual_sandbox run）",
)
async def activate_workflow(
    workflow_id: int, db: Session = Depends(get_db), user: User = Depends(_get_current_user)
):
    wf = _facade()._load_workflow(db, workflow_id, user)
    if wf.status == "active":
        return _facade()._serialize_workflow(wf)
    if wf.status not in ("sandbox_testing",):
        raise _facade().HTTPException(400, f"当前状态 {wf.status} 不能启用")
    last_run = None
    if wf.last_manual_sandbox_run_id:
        last_run = (
            db.query(_facade().ScriptWorkflowRun)
            .filter(_facade().ScriptWorkflowRun.id == wf.last_manual_sandbox_run_id)
            .first()
        )
    if not last_run or last_run.status != "success":
        raise _facade().HTTPException(
            400, "启用前必须至少有一次成功的人工沙箱测试（manual_sandbox-run）"
        )
    wf.status = "active"
    wf.updated_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    db.refresh(wf)
    return _facade()._serialize_workflow(wf)


@router.post("/{workflow_id}/deactivate", summary="停用脚本工作流（status=deprecated）")
async def deactivate_workflow(
    workflow_id: int, db: Session = Depends(get_db), user: User = Depends(_get_current_user)
):
    wf = _facade()._load_workflow(db, workflow_id, user)
    wf.status = "deprecated"
    wf.updated_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    db.refresh(wf)
    return _facade()._serialize_workflow(wf)


@router.post("/{workflow_id}/edit-with-ai", summary="对已保存脚本继续 agent loop 改（SSE）")
async def edit_with_ai(
    workflow_id: int,
    body: EditWithAiBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _facade()._load_workflow(db, workflow_id, user)
    try:
        brief_data = _facade().json.loads(wf.brief_json or "{}")
    except _facade().json.JSONDecodeError:
        brief_data = {}
    brief = _facade().Brief.from_dict(brief_data)
    brief = _facade().Brief.from_dict(
        {**brief.to_dict(), "goal": brief.goal + "\n\n[用户改进] " + body.hint.strip()}
    )
    llm_cfg = _facade()._resolve_llm_for_user(
        db, user, hint_provider=body.provider, hint_model=body.model
    )
    sid = _facade().secrets.token_urlsafe(16)
    async with _facade()._SESSION_LOCK:
        _facade().SCRIPT_AGENT_SESSIONS[sid] = _facade()._Session(
            user_id=user.id,
            brief=brief.to_dict(),
            status="running",
            events=[],
            outcome=None,
            error="",
            started_at=_facade().datetime.now(_facade().timezone.utc).timestamp(),
            files_meta=[],
            workflow_id=wf.id,
        )
        _facade()._gc_sessions()
    wf.status = "draft"
    wf.agent_session_id = sid
    wf.updated_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    return _facade().StreamingResponse(
        _facade()._stream_agent_loop(
            sid=sid, user_id=user.id, brief=brief, files=[], llm_cfg=llm_cfg
        ),
        media_type="text/event-stream",
        headers={"X-Script-Session-Id": sid, "Cache-Control": "no-cache"},
    )


@router.post("/{workflow_id}/run", summary="生产调用（mode=production；仅 active 可调）")
async def production_run(
    workflow_id: int,
    files: List[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    wf = _facade()._load_workflow(db, workflow_id, user)
    if wf.status != "active":
        raise _facade().HTTPException(400, "工作流未启用，无法进行生产调用")
    files_data = await _facade()._read_uploads(files)
    llm_cfg = _facade()._resolve_llm_for_user(db, user, hint_provider=None, hint_model=None)
    cv = _facade()._current_version(db, workflow_id)
    run = _facade().ScriptWorkflowRun(
        workflow_id=wf.id,
        version_id=cv.id if cv else None,
        user_id=user.id,
        mode="production",
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    result = await _facade().run_in_sandbox(
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
    run.outputs_meta_json = _facade().json.dumps(result.outputs, ensure_ascii=False)
    run.runtime_sdk_calls_json = _facade().json.dumps(result.sdk_calls, ensure_ascii=False)
    if result.timed_out:
        run.status = "timeout"
        run.error_message = "脚本超时"
    elif result.ok and result.outputs:
        run.status = "success"
    else:
        run.status = "failed"
        run.error_message = "; ".join(result.errors) or f"返回码 {result.returncode}"
    run.completed_at = _facade().datetime.now(_facade().timezone.utc)
    db.commit()
    db.refresh(run)
    return _facade()._serialize_run(run, with_artifacts=True, result=result)


def _serialize_run(
    run: ScriptWorkflowRun, *, with_artifacts: bool = False, result: Optional[Any] = None
) -> Dict[str, Any]:
    try:
        outputs = _facade().json.loads(run.outputs_meta_json or "[]")
    except _facade().json.JSONDecodeError:
        outputs = []
    try:
        sdk_calls = _facade().json.loads(run.runtime_sdk_calls_json or "[]")
    except _facade().json.JSONDecodeError:
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
    _facade()._load_workflow(db, workflow_id, user)
    q = db.query(_facade().ScriptWorkflowRun).filter(
        _facade().ScriptWorkflowRun.workflow_id == workflow_id
    )
    if mode:
        q = q.filter(_facade().ScriptWorkflowRun.mode == mode)
    rows = (
        q.order_by(_facade().ScriptWorkflowRun.started_at.desc()).limit(limit).offset(offset).all()
    )
    return [_facade()._serialize_run(r) for r in rows]


@router.get("/{workflow_id}/runs/{run_id}/files/{filename}", summary="下载脚本工作流单次运行产物")
async def download_run_file(
    workflow_id: int,
    run_id: int,
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    _facade()._load_workflow(db, workflow_id, user)
    run = (
        db.query(_facade().ScriptWorkflowRun)
        .filter(
            _facade().ScriptWorkflowRun.id == run_id,
            _facade().ScriptWorkflowRun.workflow_id == workflow_id,
        )
        .first()
    )
    if not run:
        raise _facade().HTTPException(404, "运行记录不存在")
    try:
        outputs = _facade().json.loads(run.outputs_meta_json or "[]")
    except _facade().json.JSONDecodeError:
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
    raise _facade().HTTPException(404, "产物文件不存在")


@router.get("/{workflow_id}/versions", summary="历史版本")
async def list_versions(
    workflow_id: int, db: Session = Depends(get_db), user: User = Depends(_get_current_user)
):
    _facade()._load_workflow(db, workflow_id, user)
    rows = (
        db.query(_facade().ScriptWorkflowVersion)
        .filter(_facade().ScriptWorkflowVersion.workflow_id == workflow_id)
        .order_by(_facade().ScriptWorkflowVersion.version_no.desc())
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
