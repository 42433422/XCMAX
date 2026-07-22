"""Read-only administrative customer value evidence API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from modstore_server.api.deps import require_admin
from modstore_server.customer_value_evidence import build_customer_value_evidence
from modstore_server.models import User

router = APIRouter(prefix="/api/admin/customer-value", tags=["admin-customer-value"])


@router.get("/evidence")
def customer_value_evidence(
    window_days: int = Query(90, ge=1, le=3650),
    _admin_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Return aggregate proof only; no customer, order or payment identifiers."""

    _ = _admin_user
    return {
        "ok": True,
        "data": build_customer_value_evidence(window_days=window_days),
    }


__all__ = ["router"]
