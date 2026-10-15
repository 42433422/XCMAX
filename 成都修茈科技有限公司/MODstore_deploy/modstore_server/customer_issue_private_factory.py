# mypy: disable-error-code="arg-type, assignment"
"""Durable private rework enters the existing owner-scoped production center."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any

from modstore_server.customer_issue_delivery_contract import issue_resolution
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import UserMod, get_session_factory
from modstore_server.models_cs import CustomerServiceTicket
from modstore_server.operational_errors import BOUNDARY_ERRORS


def dispatch_private_rework(event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.customer_service_delivery_models import custom_delivery_brief
    from modstore_server.workbench_delivery_bridge import (
        get_workbench_session_snapshot,
        start_workbench_session_for_user,
    )

    ticket_id, owner = int(payload["ticket_id"]), int(payload["user_id"])
    sid = hashlib.sha256(f"private-rework:{event_id}".encode()).hexdigest()[:24]
    with get_session_factory()() as db:
        ticket = db.query(CustomerServiceTicket).filter_by(id=ticket_id, user_id=owner).first()
        if ticket is None or ticket.intent != "custom_delivery":
            return {
                "ok": False,
                "message": "original private delivery ticket is missing",
            }
        evidence = json_loads(ticket.evidence_json, {})
        if (
            not db.query(UserMod)
            .filter_by(user_id=owner, mod_id=evidence.get("target_mod_id"))
            .first()
        ):
            return {"ok": False, "message": "private delivery entitlement was revoked"}
        runs = evidence.get("runs") or []
        prior = next((row for row in runs if row.get("session_id") == sid), None)
        if prior and prior.get("status") in {"done", "error"}:
            return {"ok": True, "replayed": True, "production_status": prior["status"]}
        target = str(evidence.get("runtime_mod_id") or evidence.get("target_mod_id") or "")
        source_kind = (
            "employee"
            if evidence.get("kind") == "employee"
            or evidence.get("rework_artifact_kind") == "employee"
            else "module"
        )
        brief = custom_delivery_brief(evidence)
        brief += f"\n原工单 {ticket.ticket_no}；账号 {owner}；修复现有运行包 {target}。"
        brief += f"\n已安装版本 {evidence.get('installed_version', '')}，必须提升版本，不得覆盖同版或改包身份。"
        brief += (
            "\n前端必须生成 frontend/src/index.js，export mount(container,sdk)，使用宿主参数 sdk.version=1、sdk.modId、sdk.route、sdk.signal、sdk.request(path,init)、sdk.navigate(path)，返回卸载函数；不得外部 import；manifest.frontend.runtime={sdk_version:1,source:'frontend/src/index.js',entry:'frontend/runtime/index.js'}。后端固定 verify_delivery(request) 返回真实隔离业务样例 observations；manifest.delivery_verification={handler:'verify_delivery',case_id:'customer-issue-"
            + str(ticket_id)
            + "-v1'}，不得使用占位成功或写客户业务数据。"
        )
        if evidence.get("shared_core_prerequisite") and not evidence.get(
            "shared_core_prerequisite_release"
        ):
            resolution = issue_resolution(ticket, evidence)
            resolution.update(
                state="awaiting_shared_core",
                last_error="共享宿主前置能力须先合入主线并正式发布",
            )
            evidence["resolution"] = resolution
            ticket.evidence_json = json_dumps(evidence)
            db.commit()
            return {"ok": False, "message": resolution["last_error"]}
        run = {
            "session_id": sid,
            "attempt": len(runs) + 1,
            "kind": source_kind,
            "status": "running",
            "created_at": datetime.now(UTC).isoformat(),
            "event_id": event_id,
        }
        if not prior:
            evidence["runs"] = [*runs, run]
        evidence["delivery_generation"] = sid
        resolution = issue_resolution(ticket, evidence)
        resolution.update(state="producing", production_session_id=sid)
        evidence["resolution"] = resolution
        ticket.evidence_json = json_dumps(evidence)
        db.commit()
    artifact = None
    try:
        result = asyncio.run(
            start_workbench_session_for_user(
                owner,
                {
                    "intent": "employee" if source_kind == "employee" else "mod",
                    "brief": brief,
                    "suggested_mod_id": target,
                    "replace": True,
                    "generate_frontend": source_kind == "module",
                    "employee_target": "pack_only",
                },
                session_id=sid,
                run_inline=True,
                delivery_context={"ticket_id": ticket_id, "evidence": evidence},
            )
        )
        status = str(result.get("status") or "error")
        if status == "running":
            return {"ok": False, "message": "同一生产会话仍在运行，稍后重试回收结果"}
        error = "" if status == "done" else "私有生产尚未完成或失败，原工单继续保留"
        if status == "done":
            from modstore_server.customer_delivery_build import prepare_private_artifact

            snapshot = asyncio.run(get_workbench_session_snapshot(sid, owner)) or {}
            artifact = prepare_private_artifact(
                ticket_id, owner, evidence, snapshot, artifact_kind=source_kind
            )
    except BOUNDARY_ERRORS as exc:
        status, error = "error", str(exc)[:1000]
    with get_session_factory()() as db:
        ticket = db.query(CustomerServiceTicket).filter_by(id=ticket_id, user_id=owner).one()
        evidence = json_loads(ticket.evidence_json, {})
        for row in evidence.get("runs", []):
            if row.get("session_id") == sid:
                row.update(status=status, error=error)
                if artifact:
                    row["verified_artifacts"] = [artifact]
        if artifact:
            evidence["delivery_artifacts"] = [artifact]
        resolution = issue_resolution(ticket, evidence)
        resolution.update(
            state="awaiting_delivery" if status == "done" else "repair_failed",
            last_error=error,
        )
        evidence["resolution"] = resolution
        ticket.evidence_json = json_dumps(evidence)
        ticket.status = "processing"
        ticket.closed_at = None
        db.commit()
    return {"ok": True, "production_status": status, "session_id": sid}
