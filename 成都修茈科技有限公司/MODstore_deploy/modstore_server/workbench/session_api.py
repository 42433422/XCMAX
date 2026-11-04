"""Session api for workbench delivery."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, cast

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.intent import CANVAS_SKILL_INTENT, _default_steps
from modstore_server.workbench.planning import _planning_record
from modstore_server.workbench.schemas import _parse_workbench_session_create
from modstore_server.workbench.sessions import SessionStore
from modstore_server.workbench.uploads import read_workbench_uploads

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class SessionApiPorts:
    sessions: SessionStore
    start: Callable[..., Awaitable[dict[str, Any]]]
    snapshot: Callable[..., Awaitable[dict[str, Any] | None]]
    run_pipeline: Callable[..., Coroutine[Any, Any, None]]


async def create_workbench_session(
    request: Request, user: User = Depends(_get_current_user), *, ports: SessionApiPorts
):
    raw_files: List[Dict[str, Any]] = []
    content_type = request.headers.get("content-type", "")
    if content_type.lower().startswith("multipart/form-data"):
        form = await request.form()
        try:
            meta_raw = str(form.get("metadata") or "{}")
            try:
                meta = json.loads(meta_raw)
            except json.JSONDecodeError as e:
                raise HTTPException(400, "metadata 必须是 JSON") from e
            if not isinstance(meta, dict):
                raise HTTPException(400, "metadata 必须是 JSON 对象")
            body = _parse_workbench_session_create(meta)
            uploads = [v for _, v in form.multi_items() if isinstance(v, StarletteUploadFile)]
            raw_files = await read_workbench_uploads(uploads)
        finally:
            await form.close()
    else:
        try:
            meta = await request.json()
        except RECOVERABLE_ERRORS as e:
            raise HTTPException(400, "请求体必须是 JSON 对象") from e
        if not isinstance(meta, dict):
            raise HTTPException(400, "请求体必须是 JSON 对象")
        body = _parse_workbench_session_create(meta)
    payload = body.model_dump()
    if raw_files:
        payload["_files"] = raw_files
    return await ports.start(int(cast(int, user.id)), payload)


async def create_workbench_script_session(
    metadata: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    user: User = Depends(_get_current_user),
    *,
    ports: SessionApiPorts,
):
    try:
        try:
            meta = json.loads(metadata or "{}")
        except json.JSONDecodeError as e:
            raise HTTPException(400, "metadata 必须是 JSON") from e
        if not isinstance(meta, dict):
            raise HTTPException(400, "metadata 必须是 JSON 对象")
        brief = str(meta.get("brief") or "").strip()
        if len(brief) < 3:
            raise HTTPException(400, "brief 不能为空")
        raw_files = await read_workbench_uploads(files or [])
    finally:
        for upload in files or []:
            await upload.close()
    if not raw_files:
        raise HTTPException(400, "请上传至少一个文件")
    sid = uuid.uuid4().hex[:24]
    payload = {
        "intent": CANVAS_SKILL_INTENT,
        "execution_mode": "script",
        "brief": brief,
        "workflow_name": meta.get("workflow_name"),
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "_files": raw_files,
    }
    async with ports.sessions.lock:
        ports.sessions.data[sid] = {
            "id": sid,
            "user_id": cast(int, user.id),
            "intent": CANVAS_SKILL_INTENT,
            "status": "running",
            "steps": _default_steps(CANVAS_SKILL_INTENT, "script"),
            "planning_record": _planning_record(payload),
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        ports.sessions.persist(sid)
    _script_task = asyncio.create_task(ports.run_pipeline(sid, cast(int, user.id), payload))
    _script_task.add_done_callback(ports.sessions.task_failsafe(sid))
    return {"session_id": sid, "status": "running"}


async def get_workbench_session(
    session_id: str, user: User = Depends(_get_current_user), *, ports: SessionApiPorts
):
    payload = await ports.snapshot(session_id, int(cast(int, user.id)))
    if payload is None:
        async with ports.sessions.lock:
            ports.sessions.hydrate(session_id)
            exists = ports.sessions.data.get(session_id)
        if not exists:
            raise HTTPException(404, "会话不存在或已过期")
        raise HTTPException(403, "无权访问此会话")
    return payload


async def download_workbench_session_file(
    session_id: str,
    filename: str,
    user: User = Depends(_get_current_user),
    *,
    ports: SessionApiPorts,
):
    async with ports.sessions.lock:
        ports.sessions.hydrate(session_id)
        sess = ports.sessions.data.get(session_id)
    if not sess:
        raise HTTPException(404, "会话不存在或已过期")
    if sess.get("user_id") != cast(int, user.id):
        raise HTTPException(403, "无权访问此会话")
    result = sess.get("script_result") or {}
    for o in result.get("outputs") or []:
        if o.get("filename") == filename:
            path = Path(str(o.get("path") or ""))
            if path.is_file():
                return FileResponse(path, filename=filename)
    raise HTTPException(404, "文件不存在")


async def retry_workbench_session(
    session_id: str, user: User = Depends(_get_current_user), *, ports: SessionApiPorts
):
    async with ports.sessions.lock:
        ports.sessions.hydrate(session_id)
        old = ports.sessions.data.get(session_id)
    if not old:
        raise HTTPException(404, "会话不存在或已过期")
    if old.get("user_id") != cast(int, user.id):
        raise HTTPException(403, "无权访问此会话")
    checkpoint = old.get("_pipeline_checkpoint") or {}
    failed_step = checkpoint.get("failed_step")
    can_resume = bool(failed_step and checkpoint.get("res") and checkpoint.get("pack_dir"))
    if can_resume:
        new_sid = uuid.uuid4().hex[:24]
        steps = _default_steps(
            old.get("intent", "employee"),
            old.get("planning_record", {}).get("execution_mode") or "employee",
            employee_target=str(checkpoint.get("employee_target") or "pack_plus_workflow"),
        )
        _step_order = [s["id"] for s in steps]
        if failed_step in _step_order:
            for s in steps:
                if _step_order.index(s["id"]) < _step_order.index(failed_step):
                    s["status"] = "done"
                    s["message"] = "已完成（重试复用）"
        async with ports.sessions.lock:
            ports.sessions.data[new_sid] = {
                "id": new_sid,
                "user_id": cast(int, user.id),
                "intent": old.get("intent", "employee"),
                "status": "running",
                "steps": steps,
                "planning_record": dict(old.get("planning_record") or {}),
                "artifact": None,
                "error": None,
                "validate_warnings": None,
                "sandbox_report": None,
                "script_result": None,
                "_resume_checkpoint": checkpoint,
            }
            ports.sessions.persist(new_sid)
        _task = asyncio.create_task(
            ports.run_pipeline(new_sid, cast(int, user.id), old.get("planning_record") or {})
        )
        _task.add_done_callback(ports.sessions.task_failsafe(new_sid))
        return {"session_id": new_sid, "status": "running", "resumed_from": failed_step}
    new_sid = uuid.uuid4().hex[:24]
    payload = old.get("planning_record") or {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("intent", old.get("intent", "employee"))
    payload.setdefault("brief", "")
    payload.setdefault("replace", True)
    async with ports.sessions.lock:
        ports.sessions.data[new_sid] = {
            "id": new_sid,
            "user_id": cast(int, user.id),
            "intent": payload.get("intent") or old.get("intent", "employee"),
            "status": "running",
            "steps": _default_steps(
                payload.get("intent") or old.get("intent", "employee"),
                payload.get("execution_mode") or "employee",
                employee_target=str(payload.get("employee_target") or "pack_plus_workflow"),
            ),
            "planning_record": dict(payload),
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        ports.sessions.persist(new_sid)
    _task = asyncio.create_task(ports.run_pipeline(new_sid, cast(int, user.id), payload))
    _task.add_done_callback(ports.sessions.task_failsafe(new_sid))
    return {"session_id": new_sid, "status": "running"}
