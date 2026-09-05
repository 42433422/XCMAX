# mypy: disable-error-code="arg-type, assignment, index, union-attr"
"""客户定制生产、验收、产物下载与安装回执 API。"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_api import (
    _visible_ticket_or_404,
)
from modstore_server.customer_service_delivery_completion import (
    complete_delivery_if_ready,
)
from modstore_server.customer_service_delivery_models import (
    CustomDeliveryDecisionBody,
    CustomDeliveryInstallReceiptBody,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_brief as _custom_delivery_brief,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_commerce_blockers,
    custom_delivery_crm,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_evidence as _custom_delivery_evidence,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_pricing_mode,
)
from modstore_server.customer_service_delivery_quality import custom_delivery_gate
from modstore_server.customer_service_orchestrator import (
    audit,
    ticket_payload,
)
from modstore_server.customer_service_tools import json_dumps
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceTicket,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_get_current_user = get_current_user


async def _start_custom_delivery_run(
    *,
    user_id: int,
    evidence: dict[str, Any],
    attempt: int,
    rework_note: str = "",
    ticket_id: int = 0,
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
    started = await start_workbench_session_for_user(
        int(user_id),
        payload,
        delivery_context={"ticket_id": ticket_id, "evidence": evidence} if ticket_id else None,
    )
    return {
        "kind": kind,
        "attempt": int(attempt),
        "session_id": str(started.get("session_id") or ""),
        "status": str(started.get("status") or "running"),
        "created_at": datetime.now(UTC).isoformat(),
    }


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
            item["verified_artifacts"] = (
                snapshot.get("verified_artifacts") or item.get("verified_artifacts") or []
            )
            snapshot["verified_artifacts"] = item["verified_artifacts"]
            latest_snapshot = snapshot
        runs.append(item)

    acceptance_status = str(evidence.get("acceptance_status") or "")
    accepted = acceptance_status == "accepted"
    pricing_mode = custom_delivery_pricing_mode(evidence)
    commerce_blockers = custom_delivery_commerce_blockers(evidence)
    if str(ticket.status or "") in {"resolved", "closed", "done"}:
        stage, label = "delivered", "已交付并上岗"
    elif (evidence.get("resolution") or {}).get("runtime_failure") and (
        evidence.get("resolution") or {}
    ).get("state") in {"queued_rework", "repair_failed"}:
        stage, label = "rework", str(
            (evidence.get("resolution") or {}).get("last_error") or "业务验证未通过，原单返工中"
        )
    elif (evidence.get("resolution") or {}).get("state") == "awaiting_runtime":
        stage, label = "delivering", "业务验证失败，等待宿主发行身份核验"
    elif pricing_mode == "post_delivery_addon" and not run_rows and commerce_blockers:
        stage, label = "commerce", "交付后新增，待报价付款"
    elif accepted and commerce_blockers:
        stage, label = "commerce", "商务条件待完成"
    elif accepted:
        stage, label = (
            "delivering",
            (
                "已安装，等待客户宿主运行与业务验证"
                if evidence.get("install_receipts")
                else "验收通过，待安装回执"
            ),
        )
    elif evidence.get("start_error") and not latest_snapshot:
        stage, label = "rework", "生产未启动，待返工"
    elif acceptance_status == "internal_approved" and latest_snapshot:
        stage, label = "acceptance", "内部确认完成，待客户本人验收"
    elif not latest_snapshot:
        stage, label = "queued", "已受理"
    elif str(latest_snapshot.get("status") or "") == "error":
        stage, label = "rework", "生产失败，待返工"
    elif str(latest_snapshot.get("status") or "") == "done":
        gate_ok, _ = custom_delivery_gate(latest_snapshot)
        stage, label = (
            ("acceptance", "质量门通过，待您验收") if gate_ok else ("rework", "质量门未通过")
        )
    else:
        stage, label = "production", "生产员工制作中"

    gate_ok, gate_message = (
        custom_delivery_gate(latest_snapshot)
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
    verified = latest_snapshot.get("verified_artifacts", []) if latest_snapshot else []
    if verified:
        artifacts = [
            {
                "kind": row["kind"],
                "id": row["id"],
                **(
                    {"source_artifact_kind": "employee"}
                    if row.get("source_employee_pack_id")
                    else {}
                ),
            }
            for row in verified
        ]
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
            "pricing_mode": pricing_mode,
            "pricing_label": (
                "首次交付内含，交付前开发免费"
                if pricing_mode == "initial_included"
                else (
                    "交付后新增，报价付款后生产"
                    if pricing_mode == "post_delivery_addon"
                    else "历史交付规则"
                )
            ),
            "included_in_purchase": pricing_mode == "initial_included",
            "delivery_terms": evidence.get("delivery_terms") or {},
            "install_receipts": evidence.get("install_receipts") or [],
            "receipt_events": evidence.get("receipt_events") or [],
            "crm": custom_delivery_crm(evidence),
            "commerce_ready": not commerce_blockers,
            "commerce_blockers": commerce_blockers,
        },
    }


@router.get("/custom-deliveries")
async def list_custom_deliveries(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    from modstore_server.customer_service_delivery_payment_api import (
        reconcile_custom_delivery_payment,
    )

    q = db.query(CustomerServiceTicket).filter(CustomerServiceTicket.intent == "custom_delivery")
    if not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    rows = (
        q.order_by(CustomerServiceTicket.updated_at.desc(), CustomerServiceTicket.id.desc())
        .limit(limit)
        .all()
    )
    changed = False
    for row in rows:
        from modstore_server.customer_delivery_failure import reconcile_runtime_failures

        if reconcile_runtime_failures(db, row):
            db.commit()
        if await reconcile_custom_delivery_payment(db, row):
            changed = True
    if changed:
        db.commit()
        for row in rows:
            db.refresh(row)
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
        is_admin = bool(getattr(user, "is_admin", False))
        verified_runs = custom.get("runs") or []
        if verified_runs and verified_runs[-1].get("verified_artifacts"):
            evidence["runs"] = verified_runs
            evidence["delivery_generation"] = str(verified_runs[-1].get("session_id") or "")
            evidence["delivery_artifacts"] = verified_runs[-1]["verified_artifacts"]
        evidence["acceptance_status"] = "internal_approved" if is_admin else "accepted"
        evidence["accepted_at"] = datetime.now(UTC).isoformat() if not is_admin else ""
        evidence["internal_approved_at"] = datetime.now(UTC).isoformat() if is_admin else ""
        evidence["acceptance_actor"] = "admin_internal" if is_admin else "customer"
        evidence["accepted_by_user_id"] = int(user.id)
        evidence["acceptance_note"] = body.note.strip()[:4000]
        ticket.decision_status = "reviewed" if is_admin else "approved"
        ticket.status = "processing"
        decision_event = (
            "custom_delivery_internal_approved" if is_admin else "custom_delivery_accepted"
        )
    else:
        note = body.note.strip()
        if len(note) < 4:
            raise HTTPException(400, "返工意见至少 4 个字")
        runs = [r for r in evidence.get("runs", []) if isinstance(r, dict)]
        run = await _start_custom_delivery_run(
            ticket_id=int(ticket.id),
            user_id=int(ticket.user_id),
            evidence=evidence,
            attempt=len(runs) + 1,
            rework_note=note,
        )
        evidence["runs"] = [*runs, run]
        evidence["delivery_generation"] = str(run.get("session_id") or "")
        evidence["delivery_artifacts"] = []
        evidence["download_grants"] = []
        evidence.pop("start_error", None)
        notes = [r for r in evidence.get("rework_notes", []) if isinstance(r, dict)]
        notes.append({"note": note, "at": datetime.now(UTC).isoformat()})
        evidence["rework_notes"] = notes[-20:]
        evidence["acceptance_status"] = "pending"
        ticket.decision_status = "pending"
        ticket.status = "processing"
        ticket.closed_at = None
        decision_event = "custom_delivery_rework_requested"
    audit(
        db,
        event_type=decision_event,
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        actor=user,
        actor_type="admin" if bool(getattr(user, "is_admin", False)) else "user",
        detail={
            "action": body.action,
            "note": body.note.strip()[:4000],
            "source": (
                "admin_delivery_center"
                if bool(getattr(user, "is_admin", False))
                else "desktop_private_delivery"
            ),
        },
    )
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(ticket)
    return await _custom_delivery_payload(ticket)


@router.get("/custom-deliveries/{ticket_id}/artifacts/{artifact_kind}/download")
async def download_custom_delivery_artifact(
    ticket_id: int,
    artifact_kind: str,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
    artifact_id: str = Query(default="", max_length=128),
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if ticket.intent != "custom_delivery":
        raise HTTPException(404, "定制交付工单不存在")
    if int(ticket.user_id) != int(user.id):
        raise HTTPException(403, "只有原工单账号可以下载私有交付")
    evidence = _custom_delivery_evidence(ticket)
    if str(evidence.get("acceptance_status") or "") != "accepted":
        raise HTTPException(409, "请先在生产员工页确认验收")
    blockers = custom_delivery_commerce_blockers(evidence)
    if blockers:
        raise HTTPException(409, f"商务交付条件未完成：{'、'.join(blockers)}")
    payload = await _custom_delivery_payload(ticket)
    artifacts = payload.get("custom_delivery", {}).get("artifacts", [])
    candidates = [
        row
        for row in artifacts
        if row.get("kind") == artifact_kind and (not artifact_id or row.get("id") == artifact_id)
    ]
    if len(candidates) > 1:
        raise HTTPException(409, "组合交付包含多个同类产物，请指定 artifact_id")
    target = candidates[0] if candidates else None
    if not target:
        raise HTTPException(404, "定制产物不存在")
    artifact_id = str(target.get("id") or "").strip()
    from modstore_server.customer_delivery_build import read_verified_artifact
    from modstore_server.customer_delivery_receipts import canonical_sha256

    runs = payload.get("custom_delivery", {}).get("runs", [])
    records = runs[-1].get("verified_artifacts", []) if runs else []
    record = next(
        (
            row
            for row in records
            if row.get("kind") == artifact_kind and row.get("id") == artifact_id
        ),
        None,
    )
    if not record:
        raise HTTPException(409, "产物尚未完成正式编译与签包")
    try:
        raw, signed = read_verified_artifact(
            record, owner_id=int(ticket.user_id), ticket_id=int(ticket.id)
        )
    except (ValueError, RuntimeError, ImportError, OSError) as exc:
        raise HTTPException(409, f"交付产物尚未通过可信签名校验：{exc}") from exc
    manifest = signed["manifest"]
    stream = BytesIO(raw)
    filename = f"{artifact_id}.xcmod" if artifact_kind == "module" else f"{artifact_id}.xcemp"
    runtime_files_sha256 = canonical_sha256(signed["files_sha256"])
    package_sha256 = hashlib.sha256(raw).hexdigest()
    version = str(manifest.get("version") or "").strip()
    verification = manifest.get("delivery_verification") or {}
    case_id = (
        str(verification.get("case_id") or "")
        if verification.get("handler") == "verify_delivery"
        else ""
    )
    if not version or not case_id:
        raise HTTPException(409, "交付产物缺少版本或固定业务验证探针，须重新生产")
    runs = [r for r in evidence.get("runs", []) if isinstance(r, dict)]
    generation = str(runs[-1].get("session_id") or "") if runs else ""
    if not generation or manifest.get("delivery_generation") != generation:
        raise HTTPException(409, "签名产物与工单当前生产轮次不匹配")
    if str(evidence.get("delivery_generation") or "") != generation:
        evidence["delivery_artifacts"] = []
        evidence["download_grants"] = []
        evidence["delivery_generation"] = generation
    evidence["delivery_artifacts"] = [
        {
            key: row[key]
            for key in (
                "kind",
                "id",
                "version",
                "package_sha256",
                "verification_case_id",
            )
        }
        | (
            {"source_employee_pack_id": row["source_employee_pack_id"]}
            if row.get("source_employee_pack_id")
            else {}
        )
        for row in records
    ]
    receipt_token = uuid.uuid4().hex
    grants = [r for r in evidence.get("download_grants", []) if isinstance(r, dict)]
    grants.append(
        {
            "token": receipt_token,
            "kind": artifact_kind,
            "id": artifact_id,
            "issued_at": datetime.now(UTC).isoformat(),
            "owner_user_id": int(ticket.user_id),
            "version": version,
            "package_sha256": package_sha256,
            "verification_case_id": case_id,
            "generation": generation,
            "runtime_files_sha256": runtime_files_sha256,
            "used": False,
        }
    )
    evidence["download_grants"] = grants[-20:]
    from modstore_server.customer_delivery_entitlements import grant_verified_delivery_access

    grant_verified_delivery_access(db, ticket, evidence, manifest, owner_id=int(user.id))
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
    db.commit()
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Delivery-Receipt-Token": receipt_token,
            "X-Delivery-Artifact-SHA256": package_sha256,
            "X-Delivery-Artifact-Version": version,
            "X-Delivery-Verification-Case": case_id,
            "X-Delivery-Entitlements-Refresh": "1",
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
    known = any(
        row.get("receipt_id") == body.receipt_id
        for row in evidence.get("receipt_events", [])
        if isinstance(row, dict)
    )
    if str(evidence.get("acceptance_status") or "") != "accepted" and not known:
        raise HTTPException(409, "定制产物尚未验收")
    from modstore_server.customer_delivery_receipts import record_receipt

    outcome = record_receipt(ticket, evidence, body.model_dump(), owner_id=int(user.id))
    if outcome["replayed"]:
        payload = await _custom_delivery_payload(ticket)
        payload["receipt"] = outcome
        return payload
    if body.stage == "verification_failed":
        from modstore_server.customer_delivery_failure import apply_runtime_failure

        apply_runtime_failure(db, ticket, evidence, outcome["record"])
    else:
        complete_delivery_if_ready(ticket, evidence)
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(ticket)
    payload = await _custom_delivery_payload(ticket)
    payload["receipt"] = outcome
    return payload
