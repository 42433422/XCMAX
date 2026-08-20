"""Workbench script pipeline branch."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_workbench_script_pipeline(
    sid, user_id, payload, execution_mode, brief, prov, mdl, db
):
    await _facade()._set_step(sid, "generate", "running", "正在生成处理脚本")
    await _facade()._set_step(sid, "validate", "pending")
    files = payload.get("_files") or []
    try:
        result = await _facade().run_script_job(
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
        await _facade()._set_step(sid, "generate", "error", msg)
        await _facade()._fail_session(sid, "generate", msg)
        return
    await _facade()._set_step(sid, "generate", "done", "脚本已生成")
    if result.get("errors"):
        await _facade()._set_step(sid, "validate", "error", "；".join(result.get("errors") or []))
        await _facade()._fail_session(sid, "validate", "；".join(result.get("errors") or []))
        async with _facade()._SESSION_LOCK:
            sess = _facade().WORKBENCH_SESSIONS.get(sid)
            if sess:
                sess["script_result"] = result
                sess["artifact"] = {"execution_mode": "script", "outputs": []}
                _facade()._persist_workbench_session_unlocked(sid)
        return
    await _facade()._set_step(sid, "validate", "done", "安全检查通过")
    await _facade()._set_step(sid, "run", "running", "正在执行脚本")
    script_wf: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    if not result.get("ok"):
        await _facade()._set_step(
            sid, "run", "error", (result.get("stderr") or "脚本执行失败")[:300]
        )
        await _facade()._fail_session(sid, "run", (result.get("stderr") or "脚本执行失败")[:1000])
    else:
        try:
            script_wf = _facade()._commit_script_workflow_from_result(
                db,
                user_id=user_id,
                session_id=sid,
                payload=payload,
                files=files,
                result=result,
            )
        except RECOVERABLE_ERRORS as e:
            msg = f"保存脚本工作流失败: {e}"
            await _facade()._set_step(sid, "run", "error", msg[:300])
            await _facade()._fail_session(sid, "run", msg[:1000])
            async with _facade()._SESSION_LOCK:
                sess = _facade().WORKBENCH_SESSIONS.get(sid)
                if sess:
                    sess["script_result"] = result
                    sess["artifact"] = {"execution_mode": "script", "outputs": []}
                    _facade()._persist_workbench_session_unlocked(sid)
            return
        await _facade()._set_step(
            sid, "run", "done", f"生成 {len(result.get('outputs') or [])} 个文件"
        )
        await _facade()._set_step(sid, "complete", "done")
    async with _facade()._SESSION_LOCK:
        sess = _facade().WORKBENCH_SESSIONS.get(sid)
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
            _facade()._persist_workbench_session_unlocked(sid)
    return
