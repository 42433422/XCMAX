"""Administrator HTTP surface for the audited entitlement fast lane."""

from __future__ import annotations

from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.entitlement_fast_lane import (
    FastLaneConflict,
    FastLaneError,
    FastLaneForbidden,
    FastLaneNotFound,
    account_fast_lane_status,
    apply_fast_lane_action,
    list_fast_lane_plans,
)
from modstore_server.models import User

router = APIRouter(prefix="/api/admin/entitlement-fast-lane", tags=["admin-entitlements"])


class FastLaneActionBody(BaseModel):
    account: str = Field(..., min_length=1, max_length=256)
    action: Literal["assign", "grant", "revoke"]
    plan_id: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(..., min_length=4, max_length=2000)
    idempotency_key: str = Field(..., min_length=12, max_length=192)
    duration_days: int | None = Field(default=None, ge=1, le=3650)


def _raise_http(exc: FastLaneError) -> NoReturn:
    if isinstance(exc, FastLaneForbidden):
        raise HTTPException(403, str(exc)) from exc
    if isinstance(exc, FastLaneNotFound):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, FastLaneConflict):
        raise HTTPException(409, str(exc)) from exc
    raise HTTPException(422, str(exc)) from exc


@router.get("/plans")
def list_entitlement_fast_lane_plans(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return {
        "items": list_fast_lane_plans(db),
        "ssot": "plan_templates+account_license_plans",
        "commerce": {
            "order_generated": False,
            "payment_generated": False,
            "transaction_generated": False,
        },
    }


@router.get("/accounts/{account}")
def get_entitlement_fast_lane_account(
    account: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        return account_fast_lane_status(db, account)
    except FastLaneError as exc:
        _raise_http(exc)


@router.post("/actions")
def mutate_entitlement_fast_lane(
    body: FastLaneActionBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        return apply_fast_lane_action(
            db,
            actor=admin,
            account=body.account,
            action=body.action,
            plan_id=body.plan_id,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            duration_days=body.duration_days,
        )
    except FastLaneError as exc:
        _raise_http(exc)


__all__ = ["FastLaneActionBody", "router"]
