"""Explicit operator-authorized company budget proposals and controls."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from modstore_server.api.actor_identity import authenticated_admin_actor
from modstore_server.api.deps import require_admin
from modstore_server.models import User
from modstore_server.strategic_company_resources import (
    CompanyLimits,
    authorize_company,
    company_status,
    create_company_proposal,
    revoke_company,
)
from modstore_server.strategic_portfolio import PortfolioError

router = APIRouter(prefix="/company-budgets", tags=["strategic-company-budget"])


class CompanyProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = Field(min_length=1, max_length=64)
    limits: CompanyLimits
    member_owner_ids: list[int] = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=100)


class CompanyApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_notes: str = Field(default="", max_length=4000)


class CompanyStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


def _call(function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        result: dict[str, Any] = function(*args, **kwargs)
        return result
    except PortfolioError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 409, str(exc)) from exc


@router.post("")
def propose(body: CompanyProposalRequest, admin: User = Depends(require_admin)) -> dict[str, Any]:
    return _call(create_company_proposal, authorizer_user_id=int(admin.id), **body.model_dump())


@router.get("/{decision_id}")
def status(decision_id: str, admin: User = Depends(require_admin)) -> dict[str, Any]:
    return _call(company_status, decision_id, owner_user_id=int(admin.id))


@router.post("/{decision_id}/approve")
def approve(
    decision_id: str, body: CompanyApprovalRequest, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    return _call(
        authorize_company,
        decision_id,
        authorizer_user_id=int(admin.id),
        actor=authenticated_admin_actor(admin),
        **body.model_dump(),
    )


@router.post("/{decision_id}/stop")
def stop(
    decision_id: str, body: CompanyStopRequest, admin: User = Depends(require_admin)
) -> dict[str, Any]:
    return _call(
        revoke_company,
        decision_id,
        authorizer_user_id=int(admin.id),
        actor=authenticated_admin_actor(admin),
        reason=body.reason,
    )
