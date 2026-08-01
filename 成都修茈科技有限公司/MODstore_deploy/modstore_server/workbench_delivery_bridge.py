"""工作台生产会话供客户定制交付复用的窄接口。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any


async def start_workbench_session_for_user(user_id: int, payload: dict[str, Any]) -> dict[str, str]:
    from modstore_server import workbench_api as workbench

    body = workbench._parse_workbench_session_create(dict(payload or {}))
    normalized = body.model_dump()
    raw_files = payload.get("_files") if isinstance(payload.get("_files"), list) else []
    if raw_files:
        normalized["_files"] = raw_files
    session_id = uuid.uuid4().hex[:24]
    async with workbench._SESSION_LOCK:
        workbench.WORKBENCH_SESSIONS[session_id] = {
            "id": session_id,
            "user_id": int(user_id),
            "intent": body.intent,
            "status": "running",
            "steps": workbench._default_steps(
                body.intent,
                body.execution_mode,
                employee_target=str(getattr(body, "employee_target", None) or "pack_only"),
            ),
            "planning_record": workbench._planning_record(normalized),
            "artifact": None,
            "error": None,
            "validate_warnings": None,
            "sandbox_report": None,
            "script_result": None,
        }
        workbench._persist_workbench_session_unlocked(session_id)
    task = asyncio.create_task(workbench._run_pipeline(session_id, int(user_id), normalized))
    task.add_done_callback(workbench._pipeline_task_failsafe(session_id))
    return {"session_id": session_id, "status": "running"}


async def get_workbench_session_snapshot(session_id: str, user_id: int) -> dict[str, Any] | None:
    from modstore_server import workbench_api as workbench

    async with workbench._SESSION_LOCK:
        workbench._hydrate_workbench_session_unlocked(session_id)
        session = workbench.WORKBENCH_SESSIONS.get(session_id)
    if not session or int(session.get("user_id") or 0) != int(user_id):
        return None
    script_result = session.get("script_result") or {}
    return {
        "id": session["id"],
        "intent": workbench._canonical_workbench_intent(str(session.get("intent") or "")),
        "status": session["status"],
        "steps": session["steps"],
        "artifact": workbench._enrich_artifact_skill_aliases(
            dict(session["artifact"]) if isinstance(session.get("artifact"), dict) else None
        ),
        "planning_record": session.get("planning_record"),
        "error": session.get("error"),
        "validate_warnings": session.get("validate_warnings"),
        "sandbox_report": session.get("sandbox_report"),
        "quality_report": session.get("quality_report"),
        "six_dimension_report": session.get("six_dimension_report"),
        "script_result": {
            "ok": script_result.get("ok"),
            "stdout": script_result.get("stdout", ""),
            "stderr": script_result.get("stderr", ""),
            "outputs": [
                {
                    "filename": output.get("filename"),
                    "size": output.get("size"),
                    "download_url": f"/api/workbench/sessions/{session_id}/files/{output.get('filename')}",
                }
                for output in (script_result.get("outputs") or [])
            ],
        } if session.get("script_result") else None,
    }


__all__ = ["get_workbench_session_snapshot", "start_workbench_session_for_user"]
