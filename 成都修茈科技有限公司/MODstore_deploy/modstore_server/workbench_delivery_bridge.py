"""工作台生产会话供客户定制交付复用的窄接口。"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import nullcontext
from typing import Any

_ACTIVE_INLINE_SESSIONS: set[str] = set()


async def start_workbench_session_for_user(
    user_id: int,
    payload: dict[str, Any],
    *,
    session_id: str = "",
    run_inline: bool = False,
    delivery_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    from modstore_server import workbench_api as workbench

    body = workbench._parse_workbench_session_create(dict(payload or {}))
    normalized = body.model_dump()
    raw_files = payload.get("_files") if isinstance(payload.get("_files"), list) else []
    if raw_files:
        normalized["_files"] = raw_files
    session_id = session_id or uuid.uuid4().hex[:24]
    source_scope = None
    if delivery_context:
        from modstore_server.customer_delivery_sources import create_private_source_scope

        source_scope = create_private_source_scope(
            int(user_id), session_id, int(delivery_context["ticket_id"])
        )
    async with workbench._SESSION_LOCK:
        workbench._hydrate_workbench_session_unlocked(session_id)
        existing = workbench.WORKBENCH_SESSIONS.get(session_id)
        if existing:
            if int(existing.get("user_id") or 0) != int(user_id):
                raise PermissionError("production session belongs to another account")
            if (
                run_inline
                and existing.get("status") == "running"
                and session_id not in _ACTIVE_INLINE_SESSIONS
            ):
                existing.update(
                    status="error",
                    error="生产进程已中断，请在原工单返工；未重复执行旧任务",
                )
                workbench._persist_workbench_session_unlocked(session_id)
            return {
                "session_id": session_id,
                "status": str(existing.get("status") or "running"),
            }
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
            "source_scope": source_scope,
        }
        workbench._persist_workbench_session_unlocked(session_id)
        if run_inline:
            _ACTIVE_INLINE_SESSIONS.add(session_id)

    async def run_scoped_pipeline() -> None:
        from modstore_server.customer_delivery_sources import (
            private_source_context,
            seed_previous_delivery,
        )

        with private_source_context(source_scope) if source_scope else nullcontext():
            if source_scope and delivery_context:
                seed_previous_delivery(source_scope, delivery_context.get("evidence") or {})
            await workbench._run_pipeline(session_id, int(user_id), normalized)

    if run_inline:
        try:
            await run_scoped_pipeline()
        finally:
            _ACTIVE_INLINE_SESSIONS.discard(session_id)
        async with workbench._SESSION_LOCK:
            status = str(workbench.WORKBENCH_SESSIONS[session_id].get("status") or "error")
        return {"session_id": session_id, "status": status}

    async def run_delivery_pipeline() -> None:
        await run_scoped_pipeline()
        if not delivery_context:
            return
        snapshot = await get_workbench_session_snapshot(session_id, user_id)
        if not snapshot or snapshot.get("status") != "done":
            return
        from modstore_server.customer_delivery_build import prepare_private_artifact
        from modstore_server.operational_errors import BOUNDARY_ERRORS

        try:
            artifact = snapshot.get("artifact") or {}
            verified = [
                await asyncio.to_thread(
                    prepare_private_artifact,
                    int(delivery_context["ticket_id"]),
                    user_id,
                    {**delivery_context["evidence"], "delivery_generation": session_id},
                    snapshot,
                    artifact_kind=kind,
                )
                for key, kind in (("mod_id", "module"), ("pack_id", "employee"))
                if artifact.get(key)
            ]
            async with workbench._SESSION_LOCK:
                workbench.WORKBENCH_SESSIONS[session_id]["verified_artifacts"] = verified
                workbench._persist_workbench_session_unlocked(session_id)
        except BOUNDARY_ERRORS as exc:
            await workbench._fail_session(session_id, "mod_sandbox", f"正式交付构建未通过：{exc}")

    task = asyncio.create_task(run_delivery_pipeline())
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
        "verified_artifacts": session.get("verified_artifacts") or [],
        "source_scope": session.get("source_scope"),
        "six_dimension_report": session.get("six_dimension_report"),
        "script_result": (
            {
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
            }
            if session.get("script_result")
            else None
        ),
    }


__all__ = ["get_workbench_session_snapshot", "start_workbench_session_for_user"]
