"""Administrative release convergence endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db, require_admin
from modstore_server.models import User
from modstore_server.release_convergence import build_release_convergence

router = APIRouter(prefix="/api/admin", tags=["admin-release-convergence"])


@router.get("/release-convergence")
def release_convergence(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Return aggregate identities and anonymized device blockers only."""

    _ = _admin
    return {"ok": True, "data": build_release_convergence(db)}


__all__ = ["router"]
