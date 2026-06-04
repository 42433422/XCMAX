"""SCIM 2.0 Users 供应 API（企业签约）。"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/scim/v2", tags=["scim"])


def _scim_token() -> str:
    return os.environ.get("XCAGI_SCIM_TOKEN", "").strip()


def require_scim_bearer(
    authorization: str | None = Header(default=None),
) -> None:
    token = _scim_token()
    if not token:
        raise HTTPException(status_code=503, detail="SCIM not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    if authorization[7:].strip() != token:
        raise HTTPException(status_code=403, detail="Invalid SCIM token")


def _user_to_scim(user: Any) -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": str(user.id),
        "userName": user.username,
        "displayName": getattr(user, "display_name", None) or user.username,
        "active": bool(getattr(user, "is_active", True)),
        "emails": [{"value": getattr(user, "email", "") or "", "primary": True}],
    }


@router.get("/Users")
def scim_list_users(
    request: Request,
    startIndex: int = 1,
    count: int = 100,
    _: None = Depends(require_scim_bearer),
):
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        q = db.query(User).order_by(User.id.asc())
        total = q.count()
        rows = q.offset(max(0, startIndex - 1)).limit(min(count, 200)).all()
    resources = [_user_to_scim(u) for u in rows]
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.post("/Users")
def scim_create_user(body: dict, _: None = Depends(require_scim_bearer)):
    from app.db.models.user import User
    from app.db.session import get_db
    from app.infrastructure.auth.enterprise_roles import normalize_enterprise_role

    username = (body.get("userName") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="userName required")
    with get_db() as db:
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=409, detail="user exists")
        user = User(
            username=username,
            display_name=(body.get("displayName") or username),
            email=(body.get("emails") or [{}])[0].get("value", ""),
            role=normalize_enterprise_role(body.get("role") or "viewer"),
            is_active=bool(body.get("active", True)),
        )
        from app.utils.password_hash import generate_password_hash

        user.password = generate_password_hash(os.urandom(24).hex())
        db.add(user)
        db.commit()
        db.refresh(user)
    return JSONResponse(_user_to_scim(user), status_code=201)


@router.patch("/Users/{user_id}")
def scim_patch_user(user_id: str, body: dict, _: None = Depends(require_scim_bearer)):
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="not found")
        for op in body.get("Operations") or []:
            val = op.get("value") or {}
            if "active" in val:
                user.is_active = bool(val["active"])
            if "displayName" in val:
                user.display_name = str(val["displayName"])
        db.commit()
    return _user_to_scim(user)


@router.delete("/Users/{user_id}")
def scim_delete_user(user_id: str, _: None = Depends(require_scim_bearer)):
    from app.db.models.user import User
    from app.db.session import get_db

    with get_db() as db:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="not found")
        user.is_active = False
        db.commit()
    from starlette.responses import Response

    return Response(status_code=204)
