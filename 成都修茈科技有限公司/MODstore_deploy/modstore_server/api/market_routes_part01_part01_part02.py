# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib
from modstore_server.api.market_routes_part01_part01_part01 import (
    AdminResetUserPasswordDTO,
)
from modstore_server.api.market_routes_part01_part01_part01 import PasswordChangeDTO
from modstore_server.api.market_routes_part01_part01_part01 import ProfileUpdateDTO
from modstore_server.api.market_routes_part01_part01_part01 import RefreshTokenDTO


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


@_facade().router.put("/auth/profile")
def api_update_profile(
    body: ProfileUpdateDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    un = (body.username or "").strip() if body.username is not None else ""
    company = (body.company or "").strip() if body.company is not None else None
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        if un:
            taken = (
                session.query(_facade().User)
                .filter(_facade().User.username == un, _facade().User.id != user.id)
                .first()
            )
            if taken:
                raise _facade().HTTPException(409, "用户名已被占用")
            row.username = un
        if company is not None:
            row.company = company[:256]
        session.commit()
    return {
        "ok": True,
        "username": row.username,
        "company": getattr(row, "company", "") or "",
    }


@_facade().router.post("/auth/change-password")
def api_change_password(
    body: PasswordChangeDTO,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.id == user.id).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        if not _facade().verify_password(body.current_password, row.password_hash):
            raise _facade().HTTPException(400, "当前密码不正确")
        row.password_hash = _facade().hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@_facade().router.post("/admin/reset-user-password")
def api_admin_reset_user_password(body: AdminResetUserPasswordDTO, request: _facade().Request):
    """凭 ``MODSTORE_ADMIN_RECHARGE_TOKEN`` 重置用户密码；请求头 ``X-Modstore-Recharge-Token`` 与钱包直充一致。"""
    admin_token = (_facade().os.environ.get("MODSTORE_ADMIN_RECHARGE_TOKEN") or "").strip()
    if not admin_token:
        raise _facade().HTTPException(
            503, "未配置 MODSTORE_ADMIN_RECHARGE_TOKEN，无法执行管理员密码重置"
        )
    client_token = (request.headers.get("X-Modstore-Recharge-Token") or "").strip()
    if client_token != admin_token:
        raise _facade().HTTPException(403, "无效的管理员授权")
    un = (body.username or "").strip()
    if not un:
        raise _facade().HTTPException(400, "请填写用户名")
    sf = _facade().get_session_factory()
    with sf() as session:
        row = session.query(_facade().User).filter(_facade().User.username == un).first()
        if not row:
            raise _facade().HTTPException(404, "用户不存在")
        row.password_hash = _facade().hash_password(body.new_password)
        session.commit()
    return {"ok": True}


@_facade().router.post("/auth/refresh")
def api_refresh_token(body: RefreshTokenDTO):
    """使用刷新令牌获取新的访问令牌"""
    refresh_token = body.refresh_token
    if not refresh_token:
        raise _facade().HTTPException(400, "缺少刷新令牌")
    payload = _facade().decode_refresh_token(refresh_token)
    if not payload:
        raise _facade().HTTPException(401, "刷新令牌无效或已过期")
    user_id = int(payload["sub"])
    username = payload["username"]
    user = _facade().get_user_by_id(user_id)
    if not user:
        raise _facade().HTTPException(401, "用户不存在")
    new_access_token = _facade().create_access_token(
        user_id, username, is_admin=bool(user.is_admin)
    )
    new_refresh_token = _facade().create_refresh_token(user_id, username)
    return _facade().auth_token_response(user, new_access_token, new_refresh_token)


@_facade().router.get("/admin/status")
def api_admin_status(
    user: _facade().User = _facade().Depends(_facade()._require_admin),
):
    """管理员状态检查。"""
    sf = _facade().get_session_factory()
    with sf() as session:
        total_items = session.query(_facade().CatalogItem).count()
        total_users = session.query(_facade().User).count()
        return {
            "ok": True,
            "is_admin": True,
            "total_catalog_items": total_items,
            "total_users": total_users,
        }
