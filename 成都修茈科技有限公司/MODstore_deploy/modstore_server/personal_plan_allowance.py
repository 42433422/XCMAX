"""Reserve one verified-identity promotion before touching the selected wallet."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server import java_wallet_admin
from modstore_server.account_license_plans import PERSONAL_PLAN_ID, account_license_plan
from modstore_server.auth_service import verified_email_digest
from modstore_server.models import (
    PersonalPlanAllowanceClaim,
    PlanTemplate,
    Transaction,
    User,
    VerificationCode,
    get_session_factory,
)
from modstore_server.payment_fulfilment import credit_plan_allowance

_MESSAGES = {
    "verification_required": "免费方案可用；验证当前账号邮箱后可申请 AI 额度。",
    "available": "邮箱已验证，可申请本次活动的 AI 额度。",
    "unavailable": "免费方案可用；当前活动额度暂不可领取。",
    "already_claimed": "该邮箱已领取过本次活动额度；免费方案仍可使用。",
    "pending": "免费方案已开通；AI 额度入账尚待确认，请稍后重试。",
    "granted": "AI 额度已入账。",
}


def _result(status: str, amount_cents: int | None = None) -> dict[str, Any]:
    plan = account_license_plan(PERSONAL_PLAN_ID) or {}
    return {
        "status": status,
        "amount_cents": amount_cents if amount_cents is not None else int(plan["quota_cents"]),
        "message": _MESSAGES[status],
    }


def verify_allowance_email(session: Session, user: User, email: str, code: str) -> None:
    """Consume a fresh code and bind ownership in the caller's account transaction."""
    email = email.strip().lower()
    if not email or "@" not in email or not code.strip():
        raise HTTPException(400, "请填写有效邮箱和验证码")
    current_email = str(user.email or "").strip().lower()
    if current_email and current_email != email:
        raise HTTPException(409, "请验证当前账号邮箱，不能通过领取额度更换邮箱")
    if session.query(User.id).filter(func.lower(User.email) == email, User.id != user.id).first():
        raise HTTPException(409, "该邮箱已被其他账号使用")
    # UPDATE locks and consumes the proof atomically on PostgreSQL and SQLite.
    codes = session.query(VerificationCode).filter(
        VerificationCode.email == email,
        VerificationCode.code == code.strip(),
        VerificationCode.used.is_(False),
        VerificationCode.expires_at > datetime.now(UTC),
    )
    if not codes.update({VerificationCode.used: True}, synchronize_session=False):
        raise HTTPException(400, "验证码无效或已过期")
    setattr(user, "email", email)
    setattr(user, "verified_email_sha256", verified_email_digest(email))
    try:
        session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "该邮箱已被其他账号使用") from exc


def _legacy_grant(session: Session, user_id: int) -> bool:
    # Existing activations must not credit again after a deployment/backend switch.
    return (
        session.query(Transaction.id)
        .filter_by(
            user_id=user_id,
            idempotency_key=f"{PERSONAL_PLAN_ID}:{user_id}",
            txn_type="account_license_quota",
            status="completed",
        )
        .first()
        is not None
    )


def _budget_available(session: Session, amount_cents: int) -> bool:
    raw = os.environ.get("MODSTORE_PERSONAL_ALLOWANCE_BUDGET_CENTS", "").strip()
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 18:
        return False
    budget = int(raw)
    reserved = (
        session.query(func.coalesce(func.sum(PersonalPlanAllowanceClaim.amount_cents), 0))
        .filter(PersonalPlanAllowanceClaim.plan_id == PERSONAL_PLAN_ID)
        .scalar()
    )
    # Count earlier releases too, but never double-count a shared Java ledger row.
    claimed_keys = select(PersonalPlanAllowanceClaim.idempotency_key)
    legacy = (
        session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.idempotency_key.like(f"{PERSONAL_PLAN_ID}:%"),
            Transaction.idempotency_key.notin_(claimed_keys),
            Transaction.status == "completed",
            Transaction.amount > 0,
        )
        .scalar()
    )
    return int(reserved or 0) + int(Decimal(legacy or 0) * 100) + amount_cents <= budget


def allowance_status(session: Session, user: User) -> dict[str, Any]:
    claim = session.get(PersonalPlanAllowanceClaim, (PERSONAL_PLAN_ID, int(user.id)))
    if claim is not None:
        return _result(
            "granted" if claim.status == "confirmed" else "pending", int(claim.amount_cents)
        )
    if _legacy_grant(session, int(user.id)):
        return _result("granted")
    email = str(user.email or "").strip().lower()
    identity = verified_email_digest(email) if email else ""
    if not identity or identity != user.verified_email_sha256:
        return _result("verification_required")
    if (
        session.query(PersonalPlanAllowanceClaim.user_id)
        .filter_by(plan_id=PERSONAL_PLAN_ID, identity_sha256=identity)
        .first()
    ):
        return _result("already_claimed")
    amount = int((account_license_plan(PERSONAL_PLAN_ID) or {})["quota_cents"])
    return _result("available" if _budget_available(session, amount) else "unavailable", amount)


def reserve_allowance(session: Session, user: User) -> dict[str, Any]:
    # A shared campaign lock serializes budget/identity checks across different users.
    locked = (
        session.query(PlanTemplate)
        .filter(PlanTemplate.id == PERSONAL_PLAN_ID)
        .update({PlanTemplate.updated_at: PlanTemplate.updated_at}, synchronize_session=False)
    )
    if locked != 1:
        return _result("unavailable")
    status = allowance_status(session, user)
    if status["status"] != "available":
        return status
    now = datetime.now(UTC)
    backend = "java" if java_wallet_admin.payment_backend_is_java() else "python"
    claim = PersonalPlanAllowanceClaim(
        plan_id=PERSONAL_PLAN_ID,
        user_id=user.id,
        identity_sha256=user.verified_email_sha256,
        backend=backend,
        amount_cents=status["amount_cents"],
        idempotency_key=f"{PERSONAL_PLAN_ID}:{user.id}:{uuid.uuid4().hex}",
        status="pending",
        created_at=now,
    )
    session.add(claim)
    if backend == "python":
        credit_plan_allowance(
            session,
            user_id=int(user.id),
            amount=Decimal(claim.amount_cents) / 100,
            txn_type="account_license_quota",
            description="个人使用版赠送 AI 使用额度",
            now=now,
            idempotency_key=str(claim.idempotency_key),
        )
        claim.status = "confirmed"
        claim.confirmed_at = now
    session.flush()
    return _result("granted" if backend == "python" else "pending", int(claim.amount_cents))


def confirm_java_allowance(user_id: int) -> dict[str, Any]:
    """The reservation is already durable; unknown remote outcomes remain reserved."""
    with get_session_factory()() as session:
        rows = session.query(PersonalPlanAllowanceClaim).filter_by(
            plan_id=PERSONAL_PLAN_ID, user_id=user_id
        )
        # Serialize retries without holding the shared campaign/User/Wallet lock.
        rows.update(
            {PersonalPlanAllowanceClaim.status: PersonalPlanAllowanceClaim.status},
            synchronize_session=False,
        )
        claim = rows.one()
        if claim.status == "confirmed":
            return _result("granted", int(claim.amount_cents))
        if claim.backend != "java":
            return _result("pending", int(claim.amount_cents))
        try:
            java_wallet_admin.credit_user(
                int(claim.user_id),
                Decimal(claim.amount_cents) / 100,
                "个人使用版赠送 AI 使用额度",
                idempotency_key=str(claim.idempotency_key),
            )
        except HTTPException as exc:
            logging.getLogger(__name__).warning(
                "Personal allowance confirmation pending user_id=%s status=%s",
                user_id,
                exc.status_code,
            )
            return _result("pending", int(claim.amount_cents))
        claim.status = "confirmed"
        claim.confirmed_at = datetime.now(UTC)
        session.commit()
        return _result("granted", int(claim.amount_cents))
