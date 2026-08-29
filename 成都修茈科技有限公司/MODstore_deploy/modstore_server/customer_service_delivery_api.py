# mypy: disable-error-code="arg-type, assignment, index, union-attr"
"""客户定制生产、验收、产物下载与安装回执 API。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from modstore_server.account_license_plans import account_license_plan
from modstore_server.api.deps import get_current_user, get_db
from modstore_server.customer_service_api import (
    _schedule_customer_ticket_incident,
    _visible_ticket_or_404,
)
from modstore_server.customer_service_delivery_completion import (
    complete_delivery_if_ready,
)
from modstore_server.customer_service_delivery_models import (
    CustomDeliveryCreateBody,
    CustomDeliveryDecisionBody,
    CustomDeliveryInstallReceiptBody,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_brief as _custom_delivery_brief,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_commerce_blockers,
    custom_delivery_crm,
    custom_delivery_pricing_mode,
)
from modstore_server.customer_service_delivery_models import (
    custom_delivery_evidence as _custom_delivery_evidence,
)
from modstore_server.customer_service_delivery_quality import custom_delivery_gate
from modstore_server.customer_service_orchestrator import (
    audit,
    enqueue_customer_service_event,
    ticket_payload,
)
from modstore_server.customer_service_tools import json_dumps
from modstore_server.models import Entitlement, User, UserPlan
from modstore_server.models_cs import (
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router = APIRouter()
_get_current_user = get_current_user


def _active_permanent_purchase(db: Session, user_id: int) -> dict[str, Any] | None:
    plan_rows = (
        db.query(UserPlan)
        .filter(UserPlan.user_id == int(user_id), UserPlan.is_active.is_(True))
        .order_by(UserPlan.id.desc())
        .all()
    )
    for plan_row in plan_rows:
        plan_id = str(plan_row.plan_id or "")
        plan = account_license_plan(plan_id) or {}
        if str(plan.get("license_type") or "") != "permanent":
            continue
        entitlements = (
            db.query(Entitlement)
            .filter(
                Entitlement.user_id == int(user_id),
                Entitlement.entitlement_type == "plan",
                Entitlement.is_active.is_(True),
            )
            .order_by(Entitlement.id.desc())
            .all()
        )
        entitlement = next(
            (
                row
                for row in entitlements
                if str(row.source_order_id or "").strip()
                and _entitlement_matches_plan(row, plan_id)
            ),
            None,
        )
        purchase_key = (
            f"entitlement:{int(entitlement.id)}"
            if entitlement is not None
            else f"user-plan:{int(plan_row.id)}"
        )
        return {
            "purchase_key": purchase_key,
            "user_plan_id": int(plan_row.id),
            "entitlement_id": int(entitlement.id) if entitlement is not None else None,
            "source_order_id": (
                str(entitlement.source_order_id or "")
                if entitlement is not None
                else ""
            ),
            "plan_id": plan_id,
            "plan_title": str(plan.get("title") or plan_id),
            "account_tier": str(plan.get("account_tier") or "normal"),
        }
    return None


def _entitlement_matches_plan(entitlement: Entitlement, plan_id: str) -> bool:
    try:
        metadata = json.loads(str(entitlement.metadata_json or "{}"))
    except (TypeError, ValueError):
        return False
    return isinstance(metadata, dict) and str(metadata.get("plan_id") or "") == plan_id


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
            await get_workbench_session_snapshot(sid, int(ticket.user_id or 0))
            if sid
            else None
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

    acceptance_status = str(evidence.get("acceptance_status") or "")
    accepted = acceptance_status == "accepted"
    pricing_mode = custom_delivery_pricing_mode(evidence)
    commerce_blockers = custom_delivery_commerce_blockers(evidence)
    if str(ticket.status or "") in {"resolved", "closed", "done"}:
        stage, label = "delivered", "已交付并上岗"
    elif pricing_mode == "post_delivery_addon" and not run_rows and commerce_blockers:
        stage, label = "commerce", "交付后新增，待报价付款"
    elif accepted and commerce_blockers:
        stage, label = "commerce", "商务条件待完成"
    elif accepted:
        stage, label = "delivering", "验收通过，待安装回执"
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
            ("acceptance", "质量门通过，待您验收")
            if gate_ok
            else ("rework", "质量门未通过")
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
        latest_snapshot.get("artifact")
        if isinstance(latest_snapshot.get("artifact"), dict)
        else {}
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
            "pricing_mode": pricing_mode,
            "pricing_label": (
                "首次交付内含，交付前开发免费"
                if pricing_mode == "initial_included"
                else "交付后新增，报价付款后生产"
                if pricing_mode == "post_delivery_addon"
                else "历史交付规则"
            ),
            "included_in_purchase": pricing_mode == "initial_included",
            "delivery_terms": evidence.get("delivery_terms") or {},
            "install_receipts": evidence.get("install_receipts") or [],
            "crm": custom_delivery_crm(evidence),
            "commerce_ready": not commerce_blockers,
            "commerce_blockers": commerce_blockers,
        },
    }


@router.post("/custom-deliveries")
async def create_custom_delivery(
    body: CustomDeliveryCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    purchase = _active_permanent_purchase(db, int(user.id))
    if purchase is None:
        raise HTTPException(403, "定制交付仅对已购买四个永久账户档位的客户开放")
    prior_tickets = (
        db.query(CustomerServiceTicket)
        .filter(
            CustomerServiceTicket.user_id == int(user.id),
            CustomerServiceTicket.intent == "custom_delivery",
        )
        .order_by(CustomerServiceTicket.id.asc())
        .all()
    )
    purchase_key = str(purchase["purchase_key"])
    purchase_initial_tickets: list[CustomerServiceTicket] = []
    legacy_delivered = False
    for prior_ticket in prior_tickets:
        prior_evidence = _custom_delivery_evidence(prior_ticket)
        prior_terms = prior_evidence.get("delivery_terms")
        prior_terms = prior_terms if isinstance(prior_terms, dict) else {}
        if (
            str(prior_terms.get("pricing_mode") or "") == "initial_included"
            and str(prior_terms.get("purchase_key") or "") == purchase_key
        ):
            purchase_initial_tickets.append(prior_ticket)
        if str(prior_ticket.status or "") in {"resolved", "closed", "done"} and not str(
            prior_terms.get("purchase_key") or ""
        ):
            legacy_delivered = True

    active_initial = next(
        (
            ticket
            for ticket in purchase_initial_tickets
            if str(ticket.status or "") not in {"resolved", "closed", "done"}
        ),
        None,
    )
    now_iso = datetime.now(UTC).isoformat()
    if active_initial is not None:
        evidence = _custom_delivery_evidence(active_initial)
        previous_kind = str(evidence.get("kind") or "")
        if previous_kind and previous_kind != body.kind:
            evidence["kind"] = "bundle"
        change = {
            "title": body.title.strip(),
            "requirements": body.requirements.strip(),
            "acceptance_criteria": body.acceptance_criteria.strip(),
            "suggested_id": str(body.suggested_id or "").strip(),
            "submitted_at": now_iso,
            "included_in_purchase": True,
        }
        changes = [
            row
            for row in evidence.get("pre_delivery_changes", [])
            if isinstance(row, dict)
        ]
        changes.append(change)
        evidence["pre_delivery_changes"] = changes[-50:]
        evidence["requirements"] = (
            f"{str(evidence.get('requirements') or '').strip()}\n\n"
            f"【交付前免费追加】{change['title']}\n{change['requirements']}"
        ).strip()
        evidence["acceptance_criteria"] = (
            f"{str(evidence.get('acceptance_criteria') or '').strip()}\n\n"
            f"【追加验收标准】{change['acceptance_criteria']}"
        ).strip()
        evidence["acceptance_status"] = "pending"
        for key in (
            "accepted_at",
            "accepted_by_user_id",
            "acceptance_actor",
            "internal_approved_at",
            "delivery_artifacts",
            "download_grants",
        ):
            evidence.pop(key, None)
        runs = [row for row in evidence.get("runs", []) if isinstance(row, dict)]
        try:
            run = await _start_custom_delivery_run(
                user_id=int(user.id),
                evidence=evidence,
                attempt=len(runs) + 1,
                rework_note=(
                    f"交付前免费追加需求：{change['title']}\n"
                    f"{change['requirements']}\n追加验收：{change['acceptance_criteria']}"
                ),
            )
            evidence["runs"] = [*runs, run]
            evidence.pop("start_error", None)
        except RECOVERABLE_ERRORS as exc:
            logger.exception(
                "pre-delivery included revision start failed ticket=%s",
                active_initial.ticket_no,
            )
            evidence["start_error"] = str(exc)[:1000]
        active_initial.evidence_json = json_dumps(evidence)
        active_initial.status = "processing"
        active_initial.decision_status = "pending"
        active_initial.closed_at = None
        active_initial.updated_at = datetime.now(UTC)
        db.add(
            CustomerServiceMessage(
                session_id=int(active_initial.session_id),
                ticket_id=int(active_initial.id),
                user_id=int(user.id),
                role="user",
                content=(
                    f"【交付前免费追加需求】{change['title']}\n"
                    f"{change['requirements']}\n验收标准：{change['acceptance_criteria']}"
                ),
                payload_json=json_dumps(
                    {"delivery_change": change, "included_in_purchase": True}
                ),
            )
        )
        audit(
            db,
            event_type="custom_delivery_pre_delivery_change_added",
            session_id=int(active_initial.session_id),
            ticket_id=int(active_initial.id),
            actor=user,
            actor_type="user",
            detail={
                "included_in_purchase": True,
                "source": "desktop_private_delivery",
                "change": change,
            },
        )
        enqueue_customer_service_event(
            db,
            event_type="customer_service.custom_delivery_pre_delivery_change_added",
            aggregate_id=str(active_initial.ticket_no),
            payload={
                "ticket_id": int(active_initial.id),
                "ticket_no": str(active_initial.ticket_no),
                "user_id": int(user.id),
                "included_in_purchase": True,
            },
        )
        db.commit()
        db.refresh(active_initial)
        return await _custom_delivery_payload(active_initial)
    purchase_consumed = any(
        str(ticket.status or "") in {"resolved", "closed", "done"}
        for ticket in purchase_initial_tickets
    )
    pricing_mode = (
        "post_delivery_addon"
        if purchase_consumed or legacy_delivered
        else "initial_included"
    )
    crm = custom_delivery_crm({})
    crm["assignment"] = {
        "status": "assigned",
        "owner_name": "生产员工",
        "assigned_at": now_iso,
        "note": "按购买账户交付规则自动指派",
    }
    crm["contract"] = {
        "status": "waived",
        "note": "沿用购买账户与原项目约定",
        "updated_at": now_iso,
    }
    if pricing_mode == "initial_included":
        crm["quote"] = {
            "status": "waived",
            "amount": 0,
            "currency": "CNY",
            "note": "首次交付前开发已包含在购买账户内",
            "updated_at": now_iso,
        }
        crm["payment"] = {
            "status": "waived",
            "amount_paid": 0,
            "currency": "CNY",
            "note": "首次交付沿用永久账户购买款",
            "updated_at": now_iso,
        }
    evidence: dict[str, Any] = {
        "schema_version": 3,
        "delivery_managed_by": "custom_delivery",
        "kind": body.kind,
        "title": body.title.strip(),
        "requirements": body.requirements.strip(),
        "acceptance_criteria": body.acceptance_criteria.strip(),
        "suggested_id": str(body.suggested_id or "").strip(),
        "acceptance_status": "pending",
        "runs": [],
        "install_receipts": [],
        "crm": crm,
        "delivery_terms": {
            "pricing_mode": pricing_mode,
            "initial_development_free": pricing_mode == "initial_included",
            "requires_new_quote_and_payment": pricing_mode == "post_delivery_addon",
            "classified_at": now_iso,
            **purchase,
        },
    }
    session = CustomerServiceSession(
        user_id=int(user.id),
        channel="desktop_private_delivery",
        status="open",
        title=body.title.strip(),
        intent="custom_delivery",
        context_json=json_dumps(
            {"source": "desktop_private_delivery", "kind": body.kind}
        ),
        last_message=body.requirements.strip()[:2000],
    )
    db.add(session)
    db.flush()
    ticket = CustomerServiceTicket(
        session_id=int(session.id),
        user_id=int(user.id),
        ticket_no=(
            f"CD{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
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
            payload_json=json_dumps(
                {"acceptance_criteria": body.acceptance_criteria.strip()}
            ),
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

    if pricing_mode == "initial_included":
        try:
            run = await _start_custom_delivery_run(
                user_id=int(user.id), evidence=evidence, attempt=1
            )
            evidence["runs"] = [run]
        except RECOVERABLE_ERRORS as exc:
            logger.exception(
                "custom delivery production start failed ticket=%s", ticket.ticket_no
            )
            evidence["start_error"] = str(exc)[:1000]
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
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
    from modstore_server.customer_service_delivery_payment_api import reconcile_custom_delivery_payment
    q = db.query(CustomerServiceTicket).filter(
        CustomerServiceTicket.intent == "custom_delivery"
    )
    if not user.is_admin:
        q = q.filter(CustomerServiceTicket.user_id == user.id)
    rows = (
        q.order_by(
            CustomerServiceTicket.updated_at.desc(), CustomerServiceTicket.id.desc()
        )
        .limit(limit)
        .all()
    )
    changed = False
    for row in rows:
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
        evidence["acceptance_status"] = "internal_approved" if is_admin else "accepted"
        evidence["accepted_at"] = datetime.now(UTC).isoformat() if not is_admin else ""
        evidence["internal_approved_at"] = (
            datetime.now(UTC).isoformat() if is_admin else ""
        )
        evidence["acceptance_actor"] = "admin_internal" if is_admin else "customer"
        evidence["accepted_by_user_id"] = int(user.id)
        evidence["acceptance_note"] = body.note.strip()[:4000]
        ticket.decision_status = "reviewed" if is_admin else "approved"
        ticket.status = "processing"
        decision_event = (
            "custom_delivery_internal_approved"
            if is_admin
            else "custom_delivery_accepted"
        )
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
):
    ticket = _visible_ticket_or_404(db, user, ticket_id)
    if ticket.intent != "custom_delivery":
        raise HTTPException(404, "定制交付工单不存在")
    evidence = _custom_delivery_evidence(ticket)
    if str(evidence.get("acceptance_status") or "") != "accepted":
        raise HTTPException(409, "请先在生产员工页确认验收")
    blockers = custom_delivery_commerce_blockers(evidence)
    if blockers:
        raise HTTPException(409, f"商务交付条件未完成：{'、'.join(blockers)}")
    payload = await _custom_delivery_payload(ticket)
    artifacts = payload.get("custom_delivery", {}).get("artifacts", [])
    evidence["delivery_artifacts"] = artifacts
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
            "issued_at": datetime.now(UTC).isoformat(),
            "used": False,
        }
    )
    evidence["download_grants"] = grants[-20:]
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
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
    evidence["delivery_artifacts"] = artifacts
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
    grant["used_at"] = datetime.now(UTC).isoformat()
    evidence["download_grants"] = grants
    receipts = [r for r in evidence.get("install_receipts", []) if isinstance(r, dict)]
    if not any(
        r.get("kind") == body.artifact_kind and r.get("id") == body.artifact_id
        for r in receipts
    ):
        receipts.append(
            {
                "kind": body.artifact_kind,
                "id": body.artifact_id,
                "version": body.installed_version,
                "host": body.host,
                "installed_at": datetime.now(UTC).isoformat(),
            }
        )
    evidence["install_receipts"] = receipts
    complete_delivery_if_ready(ticket, evidence)
    ticket.evidence_json = json_dumps(evidence)
    ticket.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(ticket)
    return await _custom_delivery_payload(ticket)
