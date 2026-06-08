"""xiu-ci.com 管理端身份码 · 公网自签发 API（方案 A）。"""
from __future__ import annotations

import os

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from modstore_server.admin_digest_identity import digest_identity_payload, verify_digest_identity_code

router = APIRouter(tags=["xcmax-admin-digest"])


def _public_api_base() -> str:
    return (
        os.environ.get("MODSTORE_PUBLIC_API_BASE")
        or os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL")
        or "https://xiu-ci.com"
    ).strip().rstrip("/")


@router.get("/api/xcmax/admin/digest-identity")
def get_digest_identity():
    return digest_identity_payload(digest_api_base=_public_api_base())


@router.post("/api/auth/verify-admin-digest-code")
def verify_admin_digest_code(body: dict = Body(default_factory=dict)):
    code = str(body.get("code") or "").strip()
    if not code:
        return JSONResponse(
            {"success": False, "message": "请输入 6 位身份校验码"},
            status_code=400,
        )
    if not verify_digest_identity_code(code):
        return JSONResponse(
            {"success": False, "message": "身份校验码无效或已过期"},
            status_code=403,
        )
    return {"success": True, "message": "管理端已解锁"}
