"""独立 AI 客服平台 API。"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db, require_admin
from modstore_server.customer_service_orchestrator import (
    action_payload,
    audit,
    decision_payload,
    enqueue_customer_service_event,
    handle_customer_message,
    session_payload,
    ticket_payload,
)
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceDecision,
    CustomerServiceIntegration,
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customer-service", tags=["customer-service"])

_get_current_user = get_current_user
_require_admin = require_admin


def _publish_customer_ticket_incident(payload: Dict[str, Any]) -> None:
    """Fire-and-forget：工单事件派发可能跑员工编排/LLM，绝不能阻塞 /chat 响应。"""
    try:
        from modstore_server.duty_workforce_contracts import (
            enrich_customer_ticket_publish_payload,
        )
        from modstore_server.incident_bus import publish as publish_incident

        # Publish boundary: never send bare ticket_id/summary into bindings.
        enriched = enrich_customer_ticket_publish_payload(dict(payload or {}))
        publish_incident(
            "ops.intake.customer_ticket",
            enriched,
            source="customer-service-api",
            fingerprint=None,
        )
    except Exception:
        logger.exception("customer-service ticket incident publish failed")


def _schedule_customer_ticket_incident(payload: Dict[str, Any]) -> None:
    threading.Thread(
        target=_publish_customer_ticket_incident,
        args=(payload,),
        daemon=True,
        name="cs-ticket-incident",
    ).start()


class CustomerServiceChatBody(BaseModel):
    message: str = Field(default="", max_length=8000)
    session_id: Optional[int] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    # data:image/...;base64,... 压缩后截图，用于补充材料
    image_data_url: Optional[str] = Field(default=None, max_length=4_500_000)


class StandardBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scenario: str = Field(default="general", max_length=64)
    description: str = Field(default="", max_length=4000)
    rules: Dict[str, Any] = Field(default_factory=dict)
    action_policy: Dict[str, Any] = Field(default_factory=dict)
    auto_enabled: bool = True
    risk_level: str = Field(default="low", max_length=16)
    priority: int = 100


class IntegrationBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    integration_type: str = Field(default="openapi", max_length=32)
    connector_id: Optional[int] = None
    workflow_id: Optional[int] = None
    scenario: str = Field(default="general", max_length=64)
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class CustomDeliveryCreateBody(BaseModel):
    kind: str = Field(..., pattern="^(module|employee|bundle)$")
    title: str = Field(..., min_length=2, max_length=128)
    requirements: str = Field(..., min_length=8, max_length=12000)
    acceptance_criteria: str = Field(..., min_length=4, max_length=6000)
    suggested_id: Optional[str] = Field(None, max_length=64)


class CustomDeliveryDecisionBody(BaseModel):
    action: str = Field(..., pattern="^(accept|rework)$")
    note: str = Field(default="", max_length=4000)


class CustomDeliveryInstallReceiptBody(BaseModel):
    artifact_kind: str = Field(..., pattern="^(module|employee)$")
    artifact_id: str = Field(..., min_length=1, max_length=128)
    installed_version: str = Field(default="", max_length=64)
    host: str = Field(default="XCAGI", max_length=128)
    receipt_token: str = Field(..., min_length=16, max_length=128)


@router.post("/chat")
async def customer_service_chat(
    body: CustomerServiceChatBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    message = str(body.message or "").strip()
    image = str(body.image_data_url or "").strip()
    if not image:
        image = str((body.context or {}).get("image_data_url") or "").strip()
    if not message and not image:
        raise HTTPException(status_code=400, detail="请输入文字或上传图片")
    if image and not image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="图片格式无效，请上传 png/jpg/webp 等")
    if len(image) > 4_500_000:
        raise HTTPException(status_code=400, detail="图片过大，请压缩后再传")
    ctx = dict(body.context or {})
    if image:
        ctx["image_data_url"] = image
        ctx["has_image"] = True
    result = handle_customer_message(
        db,
        user=user,
        message=message or "[用户补充了图片资料]",
        session_id=body.session_id,
        context=ctx,
    )
    db.commit()
    t = result.get("ticket") if isinstance(result.get("ticket"), dict) else {}
    if t:
        evidence = t.get("evidence") if isinstance(t.get("evidence"), dict) else {}
        followups = evidence.get("followups") if isinstance(evidence, dict) else None
        last_followup = followups[-1] if isinstance(followups, list) and followups else None
        issue_domain = str(t.get("issue_domain") or "")[:32]
        summary_text = str(t.get("summary") or "")[:2000]
        title_text = str(t.get("title") or "")[:500]
        # 官网/首页类问题走 website scope，便于 unified orchestrator / website_runner 接单
        blob = f"{issue_domain} {title_text} {summary_text}".lower()
        if any(
            token in blob
            for token in (
                "website",
                "官网",
                "首页",
                "landing",
                "xiu-ci",
                "xiuci",
            )
        ):
            scope = "website"
        elif issue_domain in {"website", "官网"}:
            scope = "website"
        elif issue_domain in {"desktop", "android", "fhd", "modstore"}:
            scope = issue_domain
        else:
            scope = "global"
        _schedule_customer_ticket_incident(
            {
                "subject_id": str(t.get("ticket_no") or t.get("id") or ""),
                "ticket_id": int(t.get("id") or 0),
                "ticket_no": str(t.get("ticket_no") or "")[:128],
                "title": title_text,
                "intent": str(t.get("intent") or "")[:64],
                "issue_domain": issue_domain,
                "issue_domain_label": str(t.get("issue_domain_label") or "")[:32],
                "user_confirmed_domain": str(
                    (evidence or {}).get("user_confirmed_domain") or t.get("issue_domain") or ""
                )[:32],
                "user_followup": str(
                    (last_followup or {}).get("text") if isinstance(last_followup, dict) else ""
                )[:200],
                "status": str(t.get("status") or "")[:32],
                "summary": summary_text,
                "user_id": int(user.id or 0),
                "session_id": int((result.get("session") or {}).get("id") or 0),
                "scope": scope,
                # 供 intake-dispatcher skill-intake-normalize 识别为客服工单
                "source": "customer_ticket",
                "raw": {
                    "title": title_text,
                    "body": summary_text,
                    "issue_domain": issue_domain,
                    "ticket_no": str(t.get("ticket_no") or "")[:128],
                },
            }
        )
    return result


def _custom_delivery_evidence(ticket: CustomerServiceTicket) -> Dict[str, Any]:
    evidence = json_loads(ticket.evidence_json, {})
    return evidence if isinstance(evidence, dict) else {}


def _custom_delivery_brief(evidence: Dict[str, Any], rework_note: str = "") -> str:
    kind_labels = {"module": "定制业务模块", "employee": "定制 AI 员工", "bundle": "定制 Mod + AI 员工"}
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
    evidence: Dict[str, Any],
    attempt: int,
    rework_note: str = "",
) -> Dict[str, Any]:
    from modstore_server.workbench_api import start_workbench_session_for_user

    kind = str(evidence.get("kind") or "").strip()
    payload: Dict[str, Any] = {
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


def _custom_delivery_gate(snapshot: Dict[str, Any]) -> tuple[bool, str]:
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
    quality = snapshot.get("quality_report") if isinstance(snapshot.get("quality_report"), dict) else {}
    if not artifact.get("pack_id"):
        return False, "AI 员工生产完成但缺少员工包 ID"
    if quality.get("critical_failed") is True or quality.get("runnable") is not True:
        return False, "AI 员工可运行性或关键质量门未通过"
    return True, "AI 员工包、沙箱和关键质量门已通过"


async def _custom_delivery_payload(ticket: CustomerServiceTicket) -> Dict[str, Any]:
    from modstore_server.workbench_api import get_workbench_session_snapshot

    evidence = _custom_delivery_evidence(ticket)
    run_rows = [r for r in evidence.get("runs", []) if isinstance(r, dict)]
    runs: list[Dict[str, Any]] = []
    latest_snapshot: Dict[str, Any] = {}
    for row in run_rows:
        sid = str(row.get("session_id") or "")
        snapshot = await get_workbench_session_snapshot(sid, int(ticket.user_id or 0)) if sid else None
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
        stage, label = ("acceptance", "质量门通过，待您验收") if gate_ok else ("rework", "质量门未通过")
    else:
        stage, label = "production", "生产员工制作中"

    gate_ok, gate_message = (
        _custom_delivery_gate(latest_snapshot)
        if latest_snapshot
        else (False, str(evidence.get("start_error") or ""))
    )
    artifacts: list[Dict[str, str]] = []
    artifact = latest_snapshot.get("artifact") if isinstance(latest_snapshot.get("artifact"), dict) else {}
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
    evidence: Dict[str, Any] = {
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
        subject_type={"module": "custom_module", "employee": "custom_employee", "bundle": "custom_bundle"}[body.kind],
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
        run = await _start_custom_delivery_run(
            user_id=int(user.id), evidence=evidence, attempt=1
        )
        evidence["runs"] = [run]
    except Exception as exc:  # noqa: BLE001
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
    rows = q.order_by(CustomerServiceTicket.updated_at.desc(), CustomerServiceTicket.id.desc()).limit(limit).all()
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

        from modstore_server.employee_asset_pipeline import build_employee_pack_zip_for_library
        from modstore_server.mod_scaffold_runner import modstore_library_path

        artifact_path = modstore_library_path() / artifact_id
        manifest_path = artifact_path / "manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(404, "AI 员工产物已不在生产库")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw = build_employee_pack_zip_for_library(
            artifact_id, manifest, pack_dir=artifact_path
        )
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
        r.get("kind") == body.artifact_kind and r.get("id") == body.artifact_id
        for r in artifacts
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
    if not any(r.get("kind") == body.artifact_kind and r.get("id") == body.artifact_id for r in receipts):
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


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = (
        db.query(CustomerServiceSession)
        .filter(CustomerServiceSession.user_id == user.id)
        .order_by(CustomerServiceSession.updated_at.desc(), CustomerServiceSession.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [session_payload(r) for r in rows]}


@router.get("/sessions/{session_id}")
async def session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    session = _own_session_or_404(db, user, session_id)
    messages = (
        db.query(CustomerServiceMessage)
        .filter(CustomerServiceMessage.session_id == session.id)
        .order_by(CustomerServiceMessage.id.asc())
        .all()
    )
    return {
        "session": session_payload(session),
        "messages": [
            {
                "id": m.id,
                "ticket_id": m.ticket_id,
                "role": m.role,
                "content": m.content,
                "payload": json_loads(m.payload_json, {}),
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in messages
        ],
    }


@router.get("/tickets")
async def list_tickets(
    status: str = "",
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(CustomerServiceTicket)
    if not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    if status:
        q = q.filter(CustomerServiceTicket.status == status)
    rows = (
        q.order_by(CustomerServiceTicket.updated_at.desc(), CustomerServiceTicket.id.desc())
        .limit(limit)
        .all()
    )
    return {"items": [ticket_payload(r) for r in rows]}


@router.get("/tickets/{ticket_id}")
async def ticket_detail(
    ticket_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    decisions = (
        db.query(CustomerServiceDecision)
        .filter(CustomerServiceDecision.ticket_id == ticket.id)
        .order_by(CustomerServiceDecision.id.desc())
        .all()
    )
    actions = (
        db.query(CustomerServiceAction)
        .filter(CustomerServiceAction.ticket_id == ticket.id)
        .order_by(CustomerServiceAction.id.asc())
        .all()
    )
    audits = (
        db.query(CustomerServiceAuditLog)
        .filter(CustomerServiceAuditLog.ticket_id == ticket.id)
        .order_by(CustomerServiceAuditLog.id.asc())
        .all()
    )
    return {
        "ticket": ticket_payload(ticket),
        "decisions": [decision_payload(d) for d in decisions],
        "actions": [action_payload(a) for a in actions],
        "audit_logs": [_audit_payload(a) for a in audits],
    }


@router.get("/actions")
async def list_actions(
    ticket_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    q = db.query(CustomerServiceAction)
    if ticket_id:
        ticket = _visible_ticket_or_404(db, user, ticket_id)
        q = q.filter(CustomerServiceAction.ticket_id == ticket.id)
    elif not user.is_admin:
        q = q.join(
            CustomerServiceTicket, CustomerServiceAction.ticket_id == CustomerServiceTicket.id
        ).filter(CustomerServiceTicket.user_id == user.id)
    rows = q.order_by(CustomerServiceAction.id.desc()).limit(limit).all()
    return {"items": [action_payload(r) for r in rows]}


@router.get("/standards")
async def list_standards(
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    rows = db.query(CustomerServiceStandard).order_by(CustomerServiceStandard.priority.asc()).all()
    # SSOT 四种默认标准：库空时自愈补种（避免发布/迁库后后台空白）
    if not rows:
        try:
            from modstore_server.models_db import init_default_customer_service_standards

            init_default_customer_service_standards()
            rows = (
                db.query(CustomerServiceStandard)
                .order_by(CustomerServiceStandard.priority.asc())
                .all()
            )
        except Exception:
            rows = []
    return {"items": [_standard_payload(r, include_policy=user.is_admin) for r in rows]}


@router.post("/standards")
async def create_standard(
    body: StandardBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = CustomerServiceStandard(
        name=body.name.strip(),
        scenario=body.scenario.strip() or "general",
        description=body.description.strip(),
        rules_json=json_dumps(body.rules),
        action_policy_json=json_dumps(body.action_policy),
        auto_enabled=body.auto_enabled,
        risk_level=body.risk_level.strip() or "low",
        priority=body.priority,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _standard_payload(row, include_policy=True)


@router.put("/standards/{standard_id}")
async def update_standard(
    standard_id: int,
    body: StandardBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = (
        db.query(CustomerServiceStandard).filter(CustomerServiceStandard.id == standard_id).first()
    )
    if not row:
        raise HTTPException(404, "审核标准不存在")
    row.name = body.name.strip()
    row.scenario = body.scenario.strip() or "general"
    row.description = body.description.strip()
    row.rules_json = json_dumps(body.rules)
    row.action_policy_json = json_dumps(body.action_policy)
    row.auto_enabled = body.auto_enabled
    row.risk_level = body.risk_level.strip() or "low"
    row.priority = body.priority
    db.commit()
    db.refresh(row)
    return _standard_payload(row, include_policy=True)


@router.get("/integrations")
async def list_integrations(
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    rows = db.query(CustomerServiceIntegration).order_by(CustomerServiceIntegration.id.desc()).all()
    return {"items": [_integration_payload(r) for r in rows]}


@router.post("/integrations")
async def create_integration(
    body: IntegrationBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = CustomerServiceIntegration(
        name=body.name.strip(),
        integration_type=body.integration_type.strip() or "openapi",
        connector_id=body.connector_id,
        workflow_id=body.workflow_id,
        scenario=body.scenario.strip() or "general",
        config_json=json_dumps(body.config),
        enabled=body.enabled,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _integration_payload(row)


@router.put("/integrations/{integration_id}")
async def update_integration(
    integration_id: int,
    body: IntegrationBody,
    db: Session = Depends(get_db),
    user: User = Depends(_require_admin),
):
    row = (
        db.query(CustomerServiceIntegration)
        .filter(CustomerServiceIntegration.id == integration_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "集成配置不存在")
    row.name = body.name.strip()
    row.integration_type = body.integration_type.strip() or "openapi"
    row.connector_id = body.connector_id
    row.workflow_id = body.workflow_id
    row.scenario = body.scenario.strip() or "general"
    row.config_json = json_dumps(body.config)
    row.enabled = body.enabled
    db.commit()
    db.refresh(row)
    return _integration_payload(row)


def _own_session_or_404(db: Session, user: User, session_id: int) -> CustomerServiceSession:
    row = (
        db.query(CustomerServiceSession)
        .filter(CustomerServiceSession.id == session_id, CustomerServiceSession.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(404, "客服会话不存在")
    return row


def _visible_ticket_or_404(db: Session, user: User, ticket_id: int) -> CustomerServiceTicket:
    q = db.query(CustomerServiceTicket).filter(CustomerServiceTicket.id == ticket_id)
    if not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    row = q.first()
    if not row:
        raise HTTPException(404, "客服工单不存在")
    return row


def _standard_payload(
    row: CustomerServiceStandard, *, include_policy: bool = False
) -> Dict[str, Any]:
    payload = {
        "id": row.id,
        "name": row.name,
        "scenario": row.scenario,
        "description": row.description,
        "auto_enabled": row.auto_enabled,
        "risk_level": row.risk_level,
        "priority": row.priority,
        "rules": json_loads(row.rules_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
    if include_policy:
        payload["action_policy"] = json_loads(row.action_policy_json, {})
    return payload


def _integration_payload(row: CustomerServiceIntegration) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "integration_type": row.integration_type,
        "connector_id": row.connector_id,
        "workflow_id": row.workflow_id,
        "scenario": row.scenario,
        "config": json_loads(row.config_json, {}),
        "enabled": row.enabled,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _audit_payload(row: CustomerServiceAuditLog) -> Dict[str, Any]:
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "session_id": row.session_id,
        "actor_user_id": row.actor_user_id,
        "actor_type": row.actor_type,
        "event_type": row.event_type,
        "detail": json_loads(row.detail_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
