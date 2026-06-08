"""Account bootstrap API for wallet, auth, membership, and BYOK status."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modstore_server import account_level_service
from modstore_server.api.deps import _get_current_user
from modstore_server.auth_service import create_access_token, create_refresh_token, register_user
from modstore_server.llm_api import _membership_meta, _provider_labels
from modstore_server.llm_crypto import fernet_configured
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, credential_status
from modstore_server.models import Transaction, User, UserPlan, Wallet, get_session_factory

router = APIRouter(prefix="/api/account", tags=["auth"])
open_router = APIRouter(prefix="/api/market/open", tags=["auth"])


class OpenRegisterDTO(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    email: str = Field(..., min_length=5, max_length=128)


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
    if "@" not in email:
        raise HTTPException(400, "邮箱格式不正确")
    try:
        user = register_user(body.username.strip(), body.password, email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    access_token = create_access_token(user.id, user.username, is_admin=bool(user.is_admin))
    refresh_token = create_refresh_token(user.id, user.username)
    return {
        "ok": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": user.id, "username": user.username, "email": user.email},
    }


@router.get("/bootstrap")
def api_account_bootstrap(user: User = Depends(_get_current_user)):
    """Return the high-frequency account state needed by the wallet/account UI."""
    sf = get_session_factory()
    with sf() as session:
        db_user = session.query(User).filter(User.id == user.id).first() or user
        wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
        plan = (
            session.query(UserPlan)
            .filter(UserPlan.user_id == user.id, UserPlan.is_active == True)
            .order_by(UserPlan.id.desc())
            .first()
        )
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
        membership = _membership_meta(plan.plan_id if plan else None)
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
            "llm": {
                "default": default_llm,
                "fernet_configured": fernet_configured(),
                "providers": provider_status,
                "byok_configured_count": len(
                    [p for p in provider_status if p.get("has_user_override")]
                ),
            },
        }
