# mypy: disable-error-code="arg-type"
"""Account bootstrap API for wallet, auth, membership, and BYOK status."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modstore_server import account_level_service
from modstore_server.account_license_plans import PERSONAL_PLAN_ID
from modstore_server.account_lifecycle import (
    ACCOUNT_SUSPENDED,
    active_membership_plan,
    lifecycle_for_user,
    lifecycle_for_user_id,
    mark_active_after_plan,
)
from modstore_server.api.deps import _get_current_user
from modstore_server.auth_service import (
    create_access_token,
    create_refresh_token,
    register_user,
)
from modstore_server.llm_api import _membership_meta, _provider_labels
from modstore_server.llm_crypto import fernet_configured
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, credential_status
from modstore_server.models import Transaction, User, UserPlan, Wallet, get_session_factory
from modstore_server.personal_plan_allowance import (
    allowance_status,
    confirm_java_allowance,
    reserve_allowance,
    verify_allowance_email,
)

router = APIRouter(prefix="/api/account", tags=["auth"])
open_router = APIRouter(prefix="/api/market/open", tags=["auth"])


class OpenRegisterDTO(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    email: str = Field(default="", max_length=128)


class PersonalPlanDTO(BaseModel):
    email: str = Field(..., max_length=128)
    verification_code: str = Field(..., min_length=4, max_length=16)


def _load_default_llm(raw: str | None) -> Dict[str, str]:
    try:
        data = json.loads((raw or "").strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "provider": str(data.get("provider") or "openai"),
        "model": str(data.get("model") or ""),
    }


def _open_registration_enabled() -> bool:
    raw = (os.environ.get("MODSTORE_OPEN_REGISTER_API") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@open_router.post("/register")
def api_market_open_register(body: OpenRegisterDTO):
    """Server-side account creation API for trusted integrations such as XCAGI."""
    if not _open_registration_enabled():
        raise HTTPException(404, "open registration API is disabled")
    email = (body.email or "").strip().lower()
    if email and "@" not in email:
        raise HTTPException(400, "邮箱格式不正确")
    try:
        user = register_user(body.username.strip(), body.password, email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
    lifecycle = lifecycle_for_user_id(int(user.id)).to_dict()
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            **lifecycle,
        },
        **lifecycle,
    }


@router.post("/personal-plan")
def activate_personal_plan(
    body: PersonalPlanDTO | None = None, user: User = Depends(_get_current_user)
):
    """Enable the free desktop license without creating a payment order."""
    with get_session_factory()() as session:
        account = session.query(User).filter(User.id == user.id)
        # Acquire the account write lock before reading grants, including on SQLite.
        account.update({User.account_state: User.account_state}, synchronize_session=False)
        db_user = account.one()
        if db_user.account_state == ACCOUNT_SUSPENDED or db_user.deleted_at is not None:
            raise HTTPException(403, "当前账号已暂停")
        current = lifecycle_for_user(session, db_user)
        if current.active_plan_id != PERSONAL_PLAN_ID:
            if current.desktop_access:
                raise HTTPException(409, "当前账号已有桌面端方案")
            session.add(UserPlan(user_id=db_user.id, plan_id=PERSONAL_PLAN_ID, auto_renew=False))
            mark_active_after_plan(db_user, plan_id=PERSONAL_PLAN_ID, session=session)
        if body is not None:
            verify_allowance_email(session, db_user, body.email, body.verification_code)
        allowance = reserve_allowance(session, db_user)
        session.commit()
        lifecycle = lifecycle_for_user(session, db_user).to_dict()
    if allowance["status"] == "pending":
        allowance = confirm_java_allowance(int(user.id))
    return {"ok": True, **lifecycle, "allowance": allowance}


@router.get("/bootstrap")
def api_account_bootstrap(user: User = Depends(_get_current_user)):
    """Return the high-frequency account state needed by the wallet/account UI."""
    sf = get_session_factory()
    with sf() as session:
        db_user = session.query(User).filter(User.id == user.id).first() or user
        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
        recent_transactions = (
            session.query(Transaction)
            .filter(Transaction.user_id == user.id)
            .order_by(Transaction.created_at.desc())
            .limit(5)
            .all()
        )
        labels = _provider_labels()
        provider_status = []
        for provider in KNOWN_PROVIDERS:
            row = credential_status(session, int(user.id), provider)
            row["label"] = labels.get(provider, provider)
            provider_status.append(row)
        default_llm = _load_default_llm(getattr(db_user, "default_llm_json", ""))
        lifecycle = lifecycle_for_user(session, db_user).to_dict()
        lifecycle["allowance"] = allowance_status(session, db_user)
        membership_row = active_membership_plan(session, int(user.id))
        membership = _membership_meta(membership_row.plan_id if membership_row else None)
        level_profile: Dict[str, Any] = account_level_service.build_level_profile(
            int(getattr(db_user, "experience", 0) or 0)
        ).to_dict()
        balance = float(wallet.balance if wallet else 0.0)
        return {
            "ok": True,
            "user": {
                "id": db_user.id,
                "username": db_user.username,
                "email": db_user.email,
                "is_admin": bool(db_user.is_admin),
                "experience": int(getattr(db_user, "experience", 0) or 0),
                "level_profile": level_profile,
            },
            "wallet": {
                "balance": balance,
                "updated_at": wallet.updated_at.isoformat() if wallet and wallet.updated_at else "",
                "recent_transactions": [
                    {
                        "id": r.id,
                        "amount": float(r.amount or 0),
                        "type": r.txn_type,
                        "status": r.status,
                        "description": r.description,
                        "created_at": r.created_at.isoformat() if r.created_at else "",
                    }
                    for r in recent_transactions
                ],
            },
            "membership": membership,
            "account": lifecycle,
            "llm": {
                "default": default_llm,
                "fernet_configured": fernet_configured(),
                "providers": provider_status,
                "byok_configured_count": len(
                    [p for p in provider_status if p.get("has_user_override")]
                ),
            },
        }
