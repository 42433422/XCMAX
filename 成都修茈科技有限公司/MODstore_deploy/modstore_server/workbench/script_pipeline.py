"""Script pipeline for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Dict, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class ScriptPorts:
    sessions: SessionStore
    progress: ProgressCallbacks
    execute: Callable[..., Awaitable[dict[str, Any]]]
    commit: Callable[..., dict[str, Any] | None]


async def _run_workbench_script_pipeline(
    sid, user_id, payload, execution_mode, brief, prov, mdl, db, *, ports: ScriptPorts
):
    await ports.progress.set_step(sid, "generate", "running", "正在生成处理脚本")
    await ports.progress.set_step(sid, "validate", "pending")
    files = payload.get("_files") or []
    try:
        result = await ports.execute(
            db=db,
            user_id=user_id,
            session_id=sid,
            brief=brief,
            files=files,
            provider=prov,
            model=mdl,
        )
    except RECOVERABLE_ERRORS as e:
        msg = str(e)[:800]
        await ports.progress.set_step(sid, "generate", "error", msg)
        await ports.progress.fail(sid, "generate", msg)
        return
    await ports.progress.set_step(sid, "generate", "done", "脚本已生成")
    if result.get("errors"):
        await ports.progress.set_step(
            sid, "validate", "error", "；".join(result.get("errors") or [])
        )
        await ports.progress.fail(sid, "validate", "；".join(result.get("errors") or []))
        async with ports.sessions.lock:
            sess = ports.sessions.data.get(sid)
            if sess:
                sess["script_result"] = result
                sess["artifact"] = {"execution_mode": "script", "outputs": []}
                ports.sessions.persist(sid)
        return
    await ports.progress.set_step(sid, "validate", "done", "安全检查通过")
    await ports.progress.set_step(sid, "run", "running", "正在执行脚本")
    script_wf: Optional[Dict[str, Any]] = None
    if not result.get("ok"):
        await ports.progress.set_step(
            sid, "run", "error", (result.get("stderr") or "脚本执行失败")[:300]
        )
        await ports.progress.fail(sid, "run", (result.get("stderr") or "脚本执行失败")[:1000])
    else:
        try:
            script_wf = ports.commit(
                db, user_id=user_id, session_id=sid, payload=payload, files=files, result=result
            )
        except RECOVERABLE_ERRORS as e:
            msg = f"保存脚本工作流失败: {e}"
            await ports.progress.set_step(sid, "run", "error", msg[:300])
            await ports.progress.fail(sid, "run", msg[:1000])
            async with ports.sessions.lock:
                sess = ports.sessions.data.get(sid)
                if sess:
                    sess["script_result"] = result
                    sess["artifact"] = {"execution_mode": "script", "outputs": []}
                    ports.sessions.persist(sid)
            return
        await ports.progress.set_step(
            sid, "run", "done", f"生成 {len(result.get('outputs') or [])} 个文件"
        )
        await ports.progress.set_step(sid, "complete", "done")
    async with ports.sessions.lock:
        sess = ports.sessions.data.get(sid)
        if sess:
            sess["script_result"] = result
            sess["status"] = "done" if result.get("ok") else "error"
            sess["artifact"] = {
                "execution_mode": "script",
                "script_workflow_id": script_wf.get("id") if script_wf else None,
                "script_workflow_name": script_wf.get("name") if script_wf else None,
                "outputs": [
                    {
                        "filename": o.get("filename"),
                        "size": o.get("size"),
                        "download_url": f"/api/workbench/sessions/{sid}/files/{o.get('filename')}",
                    }
                    for o in result.get("outputs") or []
                ],
            }
            if not result.get("ok"):
                sess["error"] = (result.get("stderr") or "脚本执行失败")[:1000]
            ports.sessions.persist(sid)
    return
