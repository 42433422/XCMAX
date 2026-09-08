"""Grant accepted private delivery access inside the download transaction."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from modstore_server.customer_service_delivery_models import custom_delivery_commerce_blockers
from modstore_server.models import User, UserMod


def grant_verified_delivery_access(
    db: Any, ticket: Any, evidence: dict[str, Any], manifest: dict[str, Any], *, owner_id: int
) -> list[str]:
    if int(ticket.user_id) != owner_id or manifest.get("delivery_owner_user_id") != owner_id:
        raise HTTPException(403, "只有原工单账号可以获取私有交付权益")
    if (
        evidence.get("acceptance_status") != "accepted"
        or custom_delivery_commerce_blockers(evidence)
        or manifest.get("delivery_ticket_id") != int(ticket.id)
        or manifest.get("delivery_generation") != evidence.get("delivery_generation")
    ):
        raise HTTPException(409, "私有交付尚未满足验收、商务或生产轮次条件")
    ids = sorted(
        {
            str(manifest.get("id") or ""),
            str(manifest.get("entitlement_mod_id") or manifest.get("id") or ""),
        }
    )
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", mid) for mid in ids):
        raise HTTPException(409, "正式交付权益身份无效")
    # Serialize grants for this account on the production database; do not open
    # another session or commit before the signed download/grant transaction.
    db.query(User).filter_by(id=owner_id).with_for_update().one()
    existing = {
        row.mod_id
        for row in db.query(UserMod)
        .filter(UserMod.user_id == owner_id, UserMod.mod_id.in_(ids))
        .all()
    }
    for mid in ids:
        if mid not in existing:
            db.add(UserMod(user_id=owner_id, mod_id=mid))
    db.flush()
    return ids
