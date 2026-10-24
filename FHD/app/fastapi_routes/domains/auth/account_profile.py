"""Authenticated profile, bounded avatar IO, and market-confirmed company changes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Any

from fastapi import Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session as DatabaseSession

from app.db.models.user import Session, User
from app.http.error_codes import (
    INVALID_FILE,
    INVALID_INPUT,
    MARKET_NOT_BOUND,
    NO_SESSION,
    NOT_FOUND,
    SAVE_FAILED,
    UPDATE_FAILED,
    error_envelope,
)

from .ports import (
    Database,
    ErrorTypes,
    JsonObject,
    PublicUser,
    RouteResult,
    UserDirectory,
)


@dataclass(frozen=True)
class AccountProfile:
    directory: Callable[[], UserDirectory]
    database: Database
    host_database: Database
    session_id: Callable[[Request], str | None]
    public_user: Callable[[User], JsonObject]
    load_meta: Callable[[str], JsonObject | None]
    market_token: Callable[[str], Awaitable[str | None]]
    write_market_brand: Callable[[str, str], Awaitable[object]]
    sync_tenant_name: Callable[[int, str, DatabaseSession], str]
    safe_filename: Callable[[str], str]
    save_avatar: Callable[[int, bytes, str], Path]
    avatar_file: Callable[[int], Path | None]
    avatar_media_type: Callable[[Path], str]
    avatar_api_path: str
    max_avatar_bytes: int
    recoverable_errors: ErrorTypes
    logger: Logger

    def get(self, user: User) -> RouteResult:
        """当前用户个人资料（展示名、邮箱、头像）。"""
        return {"success": True, "data": {"user": self.public_user(user)}}

    def update(self, body: JsonObject, user: User) -> RouteResult:
        """更新当前用户展示名与邮箱。"""
        display_name = body.get("display_name")
        email = body.get("email")
        kwargs: dict[str, Any] = {}
        if display_name is not None:
            kwargs["display_name"] = str(display_name).strip()[:64]
        if email is not None:
            kwargs["email"] = str(email).strip()[:128]
        if not kwargs:
            return JSONResponse(error_envelope(INVALID_INPUT, "无有效字段"), status_code=400)
        result = self.directory().update_user(user.id, **kwargs)
        if not result.get("success"):
            return JSONResponse(
                error_envelope(UPDATE_FAILED, result.get("message", "更新失败")), status_code=400
            )
        with self.database() as db:
            row = db.query(User).filter(User.id == user.id).first()
            if row is None:
                return JSONResponse(error_envelope(NOT_FOUND, "用户不存在"), status_code=404)
            payload = self.public_user(row)
        return {"success": True, "data": {"user": payload}}

    async def upload_avatar(self, file: UploadFile | None, user: User) -> RouteResult:
        """上传并替换当前用户头像（png/jpg/gif/webp，≤4MB）。"""
        if file is None or not file.filename:
            return JSONResponse(error_envelope(INVALID_INPUT, "请选择图片文件"), status_code=400)
        safe_name = self.safe_filename(file.filename) or "avatar.png"
        ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else "png"
        content = await file.read(self.max_avatar_bytes + 1)
        try:
            self.save_avatar(user.id, content, ext)
        except ValueError as exc:
            return JSONResponse(error_envelope(INVALID_FILE, str(exc)), status_code=400)
        except OSError as exc:
            self.logger.exception("avatar save failed user_id=%s", user.id)
            return JSONResponse(
                error_envelope(SAVE_FAILED, f"头像保存失败：{exc}"), status_code=500
            )
        with self.database() as db:
            row = db.query(User).filter(User.id == user.id).first()
            if row is not None:
                row.wx_avatar_url = self.avatar_api_path
        return {"success": True, "data": {"avatar_url": self.avatar_api_path}}

    def get_avatar(self, user: User) -> RouteResult:
        """返回当前登录用户的头像文件（依赖会话 Cookie 或 Bearer）。"""
        path = self.avatar_file(user.id)
        if path is None:
            return JSONResponse(
                status_code=404, content={"success": False, "message": "未设置头像"}
            )
        return FileResponse(str(path), media_type=self.avatar_media_type(path))

    async def update_company_brand(
        self, request: Request, body: JsonObject, user: User
    ) -> RouteResult:
        """保存当前账号的公司名，确认市场写入后再更新宿主工作区。"""
        brand = str(body.get("company_brand") or body.get("company") or "").strip()[:256]
        if not brand:
            return JSONResponse(
                error_envelope(INVALID_INPUT, "请输入公司或团队名称"), status_code=400
            )
        sid = self.session_id(request)
        if not sid:
            return JSONResponse(error_envelope(NO_SESSION, "无会话"), status_code=400)
        meta = self.load_meta(sid) or {}
        market_bound = bool(
            meta.get("market_user_id")
            or getattr(user, "market_user_id", None)
            or meta.get("market_is_enterprise")
            or meta.get("market_is_admin")
        )
        try:
            tok = await self.market_token(sid)
        except self.recoverable_errors():
            tok = None
            market_bound = True
        if market_bound and (not tok):
            return JSONResponse(
                error_envelope(MARKET_NOT_BOUND, "企业账号登录已失效，请重新登录后保存公司名称"),
                status_code=409,
            )
        if tok:
            auth = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
            try:
                result = await self.write_market_brand(auth, brand)
            except self.recoverable_errors():
                result = None
            if not (
                isinstance(result, dict)
                and (not result.get("__proxy_error__"))
                and (result.get("ok") is True or result.get("success") is True)
                and (str(result.get("company") or "").strip() == brand)
            ):
                return JSONResponse(
                    error_envelope(UPDATE_FAILED, "公司名称未能同步到企业账号，请稍后重试"),
                    status_code=502,
                )
        try:
            with self.host_database() as db:
                db_user = db.query(User).filter(User.id == user.id).first()
                session = (
                    db.query(Session)
                    .filter(Session.session_id == sid, Session.user_id == user.id)
                    .first()
                )
                if db_user is None or session is None:
                    raise ValueError("登录会话已失效")
                tenant_name = self.sync_tenant_name(user.id, brand, db)
                session.company_brand = brand
                session.tenant_id = db_user.tenant_id
        except self.recoverable_errors():
            self.logger.exception("company brand local persistence failed")
            message = (
                "企业账号名称已同步，但当前工作区保存失败，请重试保存"
                if tok
                else "当前工作区名称保存失败，请重新登录后重试"
            )
            return JSONResponse(error_envelope(SAVE_FAILED, message), status_code=500)
        return {
            "success": True,
            "company_brand": brand,
            "tenant_name": tenant_name,
            "persistence_scope": "account" if tok else "local",
        }


def public_user(user: PublicUser) -> JsonObject:
    from app.utils.no_email import email_display, is_no_email_address
    from app.utils.path_io.user_avatar_storage import public_avatar_url

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "email_display": email_display(user.email),
        "no_email": is_no_email_address(user.email),
        "role": user.role,
        "is_active": user.is_active,
        "avatar_url": public_avatar_url(getattr(user, "wx_avatar_url", None)),
    }
