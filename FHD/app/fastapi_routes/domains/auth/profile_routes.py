"""Authenticated personal profile, avatar and organization branding."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Body, Depends, File, Request, UploadFile

from app.db.models.user import User

from .account_profile import AccountProfile
from .port_contracts import JsonObject


class ProfileRoutes:
    """Authenticated personal profile, avatar and organization branding."""

    def __init__(
        self,
        *,
        profile: Callable[[], AccountProfile],
        authenticated_user: Callable[[Request], User],
    ) -> None:
        router = self.router = APIRouter()

        @router.get("/api/auth/profile", response_model=None)
        def auth_profile_get(user: User = Depends(authenticated_user)) -> object:
            """当前用户个人资料（展示名、邮箱、头像）。"""
            return profile().get(user)

        self.auth_profile_get = auth_profile_get

        @router.patch("/api/auth/profile", response_model=None)
        def auth_profile_patch(
            body: JsonObject = Body(default_factory=dict), user: User = Depends(authenticated_user)
        ) -> object:
            """更新当前用户展示名与邮箱。"""
            return profile().update(body, user)

        self.auth_profile_patch = auth_profile_patch

        @router.post("/api/auth/profile/avatar", response_model=None)
        async def auth_profile_avatar_upload(
            file: UploadFile | None = File(default=None), user: User = Depends(authenticated_user)
        ) -> object:
            """上传并替换当前用户头像（png/jpg/gif/webp，≤4MB）。"""
            return await profile().upload_avatar(file, user)

        self.auth_profile_avatar_upload = auth_profile_avatar_upload

        @router.get("/api/auth/avatar", response_model=None)
        def auth_profile_avatar_get(user: User = Depends(authenticated_user)) -> object:
            """返回当前登录用户的头像文件（依赖会话 Cookie 或 Bearer）。"""
            return profile().get_avatar(user)

        self.auth_profile_avatar_get = auth_profile_avatar_get

        @router.post("/api/auth/company-brand", response_model=None)
        async def auth_update_company_brand(
            request: Request,
            body: JsonObject = Body(default_factory=dict),
            user: User = Depends(authenticated_user),
        ) -> object:
            """保存当前账号的公司名，确认市场写入后再更新宿主工作区。"""
            return await profile().update_company_brand(request, body, user)

        self.auth_update_company_brand = auth_update_company_brand
