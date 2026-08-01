"""客户定制生产、验收、产物下载与安装回执 API。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_api import (
    _schedule_customer_ticket_incident,
    _visible_ticket_or_404,
)
from modstore_server.customer_service_orchestrator import (
    audit,
    enqueue_customer_service_event,
    ticket_payload,
)
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_get_current_user = get_current_user


class CustomDeliveryCreateBody(BaseModel):
    kind: str = Field(..., pattern="^(module|employee|bundle)$")
    title: str = Field(..., min_length=2, max_length=128)
    requirements: str = Field(..., min_length=8, max_length=12000)
    acceptance_criteria: str = Field(..., min_length=4, max_length=6000)
    suggested_id: str | None = Field(None, max_length=64)


class CustomDeliveryDecisionBody(BaseModel):
    action: str = Field(..., pattern="^(accept|rework)$")
    note: str = Field(default="", max_length=4000)


class CustomDeliveryInstallReceiptBody(BaseModel):
    artifact_kind: str = Field(..., pattern="^(module|employee)$")
    artifact_id: str = Field(..., min_length=1, max_length=128)
    installed_version: str = Field(default="", max_length=64)
    host: str = Field(default="XCAGI", max_length=128)
    receipt_token: str = Field(..., min_length=16, max_length=128)


def _custom_delivery_evidence(ticket: CustomerServiceTicket) -> dict[str, Any]:
    evidence = json_loads(ticket.evidence_json, {})
    return evidence if isinstance(evidence, dict) else {}


def _custom_delivery_brief(evidence: dict[str, Any], rework_note: str = "") -> str:
    kind_labels = {
        "module": "定制业务模块",
        "employee": "定制 AI 员工",
        "bundle": "定制 Mod + AI 员工",
    }
    parts = [
        f"交付类型：{kind_labels.get(str(evidence.get('kind') or ''), '客户定制')}",
        f"需求名称：{str(evidence.get('title') or '').strip()}",
        f"需求说明：{str(evidence.get('requirements') or '').strip()}",
        f"验收标准：{str(evidence.get('acceptance_criteria') or '').strip()}",
        "产物必须通过工作台内置的沙箱、工作流和质量门，不得用占位实现冒充交付。",
    ]
    if rework_note:
        parts.append(f"本轮返工意见：{rework_note.strip()}")
    return "\n\n".join(parts)


async def _start_custom_delivery_run(
    *,
    user_id: int,
    evidence: dict[str, Any],
    attempt: int,
    rework_note: str = "",
) -> dict[str, Any]:
    from modstore_server.workbench_api import start_workbench_session_for_user

    kind = str(evidence.get("kind") or "").strip()
    payload: dict[str, Any] = {
        "intent": "employee" if kind == "employee" else "mod",
        "brief": _custom_delivery_brief(evidence, rework_note),
        "suggested_mod_id": str(evidence.get("suggested_id") or "").strip() or None,
        "replace": False,
        "generate_full_suite": kind == "bundle",
        "generate_frontend": kind in {"module", "bundle"},
        "employee_target": "pack_plus_workflow",
        "embed_script_workflow": kind == "employee",
    }
    started = await start_workbench_session_for_user(int(user_id), payload)
    return {
        "kind": kind,
        "attempt": int(attempt),
        "session_id": str(started.get("session_id") or ""),
        "status": str(started.get("status") or "running"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _custom_delivery_gate(snapshot: dict[str, Any]) -> tuple[bool, str]:
    if str(snapshot.get("status") or "") != "done":
        return False, str(snapshot.get("error") or "生产尚未完成")
    artifact = snapshot.get("artifact") if isinstance(snapshot.get("artifact"), dict) else {}
    intent = str(snapshot.get("intent") or "")
    if intent == "mod":
        validation = (
            artifact.get("validation_summary")
            if isinstance(artifact.get("validation_summary"), dict)
            else {}
        )
        if not artifact.get("mod_id"):
            return False, "Mod 生产完成但缺少产物 ID"
        if validation.get("ok") is not True:
            return False, "Mod 沙箱或员工可用性门未通过"
        return True, "Mod 产物和质量门已通过"
    quality = (
        snapshot.get("quality_report") if isinstance(snapshot.get("quality_report"), dict) else {}
    )
    if not artifact.get("pack_id"):
        return False, "AI 员工生产完成但缺少员工包 ID"
    if quality.get("critical_failed") is True or quality.get("runnable") is not True:
        return False, "AI 员工可运行性或关键质量门未通过"
    return True, "AI 员工包、沙箱和关键质量门已通过"


async def _custom_delivery_payload(ticket: CustomerServiceTicket) -> dict[str, Any]:
    from modstore_server.workbench_api import get_workbench_session_snapshot

    evidence = _custom_delivery_evidence(ticket)
    run_rows = [r for r in evidence.get("runs", []) if isinstance(r, dict)]
    runs: list[dict[str, Any]] = []
    latest_snapshot: dict[str, Any] = {}
    for row in run_rows:
        sid = str(row.get("session_id") or "")
        snapshot = (
            await get_workbench_session_snapshot(sid, int(ticket.user_id or 0)) if sid else None
        )
        item = dict(row)
        if snapshot:
            item["status"] = str(snapshot.get("status") or item.get("status") or "")
            item["steps"] = snapshot.get("steps") or []
            item["artifact"] = snapshot.get("artifact")
            item["error"] = snapshot.get("error")
            item["quality_report"] = snapshot.get("quality_report")
            item["sandbox_report"] = snapshot.get("sandbox_report")
            latest_snapshot = snapshot
        runs.append(item)

    accepted = str(evidence.get("acceptance_status") or "") == "accepted"
    if str(ticket.status or "") in {"resolved", "closed", "done"}:
        stage, label = "delivered", "已交付并上岗"
    elif accepted:
        stage, label = "delivering", "验收通过，待安装回执"
    elif evidence.get("start_error") and not latest_snapshot:
        stage, label = "rework", "生产未启动，待返工"
    elif not latest_snapshot:
        stage, label = "queued", "已受理"
    elif str(latest_snapshot.get("status") or "") == "error":
        stage, label = "rework", "生产失败，待返工"
    elif str(latest_snapshot.get("status") or "") == "done":
        gate_ok, _ = _custom_delivery_gate(latest_snapshot)
        stage, label = (
            ("acceptance", "质量门通过，待您验收") if gate_ok else ("rework", "质量门未通过")
        )
    else:
        stage, label = "production", "生产员工制作中"

    gate_ok, gate_message = (
        _custom_delivery_gate(latest_snapshot)
        if latest_snapshot
        else (False, str(evidence.get("start_error") or ""))
    )
    artifacts: list[dict[str, str]] = []
    artifact = (
        latest_snapshot.get("artifact") if isinstance(latest_snapshot.get("artifact"), dict) else {}
    )
    if artifact.get("mod_id"):
        artifacts.append({"kind": "module", "id": str(artifact["mod_id"])})
    if artifact.get("pack_id"):
        artifacts.append({"kind": "employee", "id": str(artifact["pack_id"])})
    return {
        **ticket_payload(ticket),
        "custom_delivery": {
            "kind": str(evidence.get("kind") or ""),
            "requirements": str(evidence.get("requirements") or ""),
            "acceptance_criteria": str(evidence.get("acceptance_criteria") or ""),
            "stage": stage,
            "stage_label": label,
            "gate_ok": gate_ok,
            "gate_message": gate_message,
            "runs": runs,
            "artifacts": artifacts,
            "acceptance_status": str(evidence.get("acceptance_status") or "pending"),
            "install_receipts": evidence.get("install_receipts") or [],
        },
    }


@router.post("/custom-deliveries")
async def create_custom_delivery(
    body: CustomDeliveryCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "delivery_managed_by": "custom_delivery",
        "kind": body.kind,
        "title": body.title.strip(),
        "requirements": body.requirements.strip(),
        "acceptance_criteria": body.acceptance_criteria.strip(),
        "suggested_id": str(body.suggested_id or "").strip(),
        "acceptance_status": "pending",
        "runs": [],
        "install_receipts": [],
    }
    session = CustomerServiceSession(
        user_id=int(user.id),
        channel="desktop_private_delivery",
        status="open",
        title=body.title.strip(),
        intent="custom_delivery",
        context_json=json_dumps({"source": "desktop_private_delivery", "kind": body.kind}),
        last_message=body.requirements.strip()[:2000],
    )
    db.add(session)
    db.flush()
    ticket = CustomerServiceTicket(
        session_id=int(session.id),
        user_id=int(user.id),
        ticket_no=(
            f"CD{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            f"{int(user.id):04d}{uuid.uuid4().hex[:6].upper()}"
        ),
        title=body.title.strip(),
        intent="custom_delivery",
        subject_type={
            "module": "custom_module",
            "employee": "custom_employee",
            "bundle": "custom_bundle",
        }[body.kind],
        status="processing",
        priority="normal",
        evidence_json=json_dumps(evidence),
        summary=body.requirements.strip()[:2000],
        decision_status="pending",
        automation_level="assisted",
    )
    db.add(ticket)
    db.flush()
    db.add(
        CustomerServiceMessage(
            session_id=int(session.id),
            ticket_id=int(ticket.id),
            user_id=int(user.id),
            role="user",
            content=body.requirements.strip(),
            payload_json=json_dumps({"acceptance_criteria": body.acceptance_criteria.strip()}),
        )
    )
    audit(
        db,
        event_type="custom_delivery_created",
        session_id=int(session.id),
        ticket_id=int(ticket.id),
        actor=user,
        detail={"kind": body.kind, "source": "desktop_private_delivery"},
    )
    enqueue_customer_service_event(
        db,
        "customer_service.custom_delivery_created",
        ticket.ticket_no,
        {"ticket_id": int(ticket.id), "ticket_no": ticket.ticket_no, "kind": body.kind},
    )
    db.commit()

    try:
        run = await _start_custom_delivery_run(user_id=int(user.id), evidence=evidence, attempt=1)
        evidence["runs"] = [run]
    except Exception as exc:
        logger.exception("custom delivery production start failed ticket=%s", ticket.ticket_no)
        evidence["start_error"] = str(exc)[:1000]
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)

    _schedule_customer_ticket_incident(
        {
            "subject_id": ticket.ticket_no,
            "ticket_id": int(ticket.id),
            "ticket_no": ticket.ticket_no,
            "title": ticket.title,
            "intent": "custom_delivery",
            "issue_domain": "custom",
            "status": ticket.status,
            "summary": ticket.summary,
            "user_id": int(user.id),
            "session_id": int(session.id),
            "scope": "modstore",
            "source": "customer_ticket",
            "delivery_managed_by": "custom_delivery",
            "raw": {"title": ticket.title, "body": ticket.summary, "kind": body.kind},
        }
    )
    return await _custom_delivery_payload(ticket)


@router.get("/custom-deliveries")
async def list_custom_deliveries(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(CustomerServiceTicket).filter(CustomerServiceTicket.intent == "custom_delivery")
    if not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    rows = (
        q.order_by(CustomerServiceTicket.updated_at.desc(), CustomerServiceTicket.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [await _custom_delivery_payload(row) for row in rows]}


@router.post("/custom-deliveries/{ticket_id}/decision")
async def decide_custom_delivery(
    ticket_id: int,
    body: CustomDeliveryDecisionBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if ticket.intent != "custom_delivery":
        raise HTTPException(404, "定制交付工单不存在")
    evidence = _custom_delivery_evidence(ticket)
    payload = await _custom_delivery_payload(ticket)
    custom = payload.get("custom_delivery") or {}
    if body.action == "accept":
        if custom.get("stage") != "acceptance" or custom.get("gate_ok") is not True:
            raise HTTPException(409, "产物尚未通过生产质量门，不能验收")
        evidence["acceptance_status"] = "accepted"
        evidence["accepted_at"] = datetime.now(timezone.utc).isoformat()
        evidence["acceptance_note"] = body.note.strip()[:4000]
        ticket.decision_status = "approved"
        ticket.status = "processing"
    else:
        note = body.note.strip()
        if len(note) < 4:
            raise HTTPException(400, "返工意见至少 4 个字")
        runs = [r for r in evidence.get("runs", []) if isinstance(r, dict)]
        run = await _start_custom_delivery_run(
            user_id=int(ticket.user_id),
            evidence=evidence,
            attempt=len(runs) + 1,
            rework_note=note,
        )
        evidence["runs"] = [*runs, run]
        evidence.pop("start_error", None)
        notes = [r for r in evidence.get("rework_notes", []) if isinstance(r, dict)]
        notes.append({"note": note, "at": datetime.now(timezone.utc).isoformat()})
        evidence["rework_notes"] = notes[-20:]
        evidence["acceptance_status"] = "pending"
        ticket.decision_status = "pending"
        ticket.status = "processing"
        ticket.closed_at = None
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return await _custom_delivery_payload(ticket)


@router.get("/custom-deliveries/{ticket_id}/artifacts/{artifact_kind}/download")
async def download_custom_delivery_artifact(
    ticket_id: int,
    artifact_kind: str,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if ticket.intent != "custom_delivery":
        raise HTTPException(404, "定制交付工单不存在")
    evidence = _custom_delivery_evidence(ticket)
    if str(evidence.get("acceptance_status") or "") != "accepted":
        raise HTTPException(409, "请先在生产员工页确认验收")
    payload = await _custom_delivery_payload(ticket)
    artifacts = payload.get("custom_delivery", {}).get("artifacts", [])
    target = next((r for r in artifacts if r.get("kind") == artifact_kind), None)
    if not target:
        raise HTTPException(404, "定制产物不存在")
    artifact_id = str(target.get("id") or "").strip()
    if artifact_kind == "module":
        from modman.store import build_mod_zip_bytes
        from modstore_server.mod_scaffold_runner import modstore_library_path

        artifact_path = modstore_library_path() / artifact_id
        if not artifact_path.is_dir():
            raise HTTPException(404, "Mod 产物已不在生产库")
        stream = build_mod_zip_bytes(artifact_path)
        filename = f"{artifact_id}.zip"
    elif artifact_kind == "employee":
        import json

        from modstore_server.employee_asset_pipeline import (
            build_employee_pack_zip_for_library,
        )
        from modstore_server.mod_scaffold_runner import modstore_library_path

        artifact_path = modstore_library_path() / artifact_id
        manifest_path = artifact_path / "manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(404, "AI 员工产物已不在生产库")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw = build_employee_pack_zip_for_library(artifact_id, manifest, pack_dir=artifact_path)
        stream = BytesIO(raw)
        filename = f"{artifact_id}.xcemp"
    else:
        raise HTTPException(400, "artifact_kind 必须是 module 或 employee")
    receipt_token = uuid.uuid4().hex
    grants = [r for r in evidence.get("download_grants", []) if isinstance(r, dict)]
    grants.append(
        {
            "token": receipt_token,
            "kind": artifact_kind,
            "id": artifact_id,
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "used": False,
        }
    )
    evidence["download_grants"] = grants[-20:]
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Delivery-Receipt-Token": receipt_token,
        },
    )


@router.post("/custom-deliveries/{ticket_id}/installed")
async def record_custom_delivery_install(
    ticket_id: int,
    body: CustomDeliveryInstallReceiptBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if ticket.intent != "custom_delivery":
        raise HTTPException(404, "定制交付工单不存在")
    evidence = _custom_delivery_evidence(ticket)
    if str(evidence.get("acceptance_status") or "") != "accepted":
        raise HTTPException(409, "定制产物尚未验收")
    payload = await _custom_delivery_payload(ticket)
    artifacts = payload.get("custom_delivery", {}).get("artifacts", [])
    if not any(
        r.get("kind") == body.artifact_kind and r.get("id") == body.artifact_id for r in artifacts
    ):
        raise HTTPException(409, "安装回执与本工单产物不匹配")
    grants = [r for r in evidence.get("download_grants", []) if isinstance(r, dict)]
    grant = next(
        (
            r
            for r in grants
            if r.get("token") == body.receipt_token
            and r.get("kind") == body.artifact_kind
            and r.get("id") == body.artifact_id
            and r.get("used") is not True
        ),
        None,
    )
    if not grant:
        raise HTTPException(409, "安装回执凭证无效或已使用，请重新下载定制产物")
    grant["used"] = True
    grant["used_at"] = datetime.now(timezone.utc).isoformat()
    evidence["download_grants"] = grants
    receipts = [r for r in evidence.get("install_receipts", []) if isinstance(r, dict)]
    if not any(
        r.get("kind") == body.artifact_kind and r.get("id") == body.artifact_id for r in receipts
    ):
        receipts.append(
            {
                "kind": body.artifact_kind,
                "id": body.artifact_id,
                "version": body.installed_version,
                "host": body.host,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    evidence["install_receipts"] = receipts
    required = {(str(r.get("kind")), str(r.get("id"))) for r in artifacts}
    installed = {(str(r.get("kind")), str(r.get("id"))) for r in receipts}
    if required and required.issubset(installed):
        ticket.status = "resolved"
        ticket.decision_status = "approved"
        ticket.closed_at = datetime.now(timezone.utc)
        evidence["delivered_at"] = ticket.closed_at.isoformat()
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return await _custom_delivery_payload(ticket)
