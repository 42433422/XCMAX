"""CircleRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.models import (
    AiCircleCommentBody,
    AiCirclePostBody,
)
from app.application.mobile_extensions.protocols import (
    AddCommentCall,
    AiCircleEmployeeProfilesCall,
    AiCircleUserCall,
    CreatePostCall,
    ListPostsCall,
    MobilePrincipal,
    SyncCircleCall,
    ToggleLikeCall,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CircleRoutesPorts:
    ai_circle_employee_profiles: AiCircleEmployeeProfilesCall
    ai_circle_user: AiCircleUserCall
    list_posts: ListPostsCall
    sync_circle: SyncCircleCall
    create_post: CreatePostCall
    toggle_like: ToggleLikeCall
    add_comment: AddCommentCall


class CircleRoutes:
    def __init__(self, ports: CircleRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        @router.get("/circle/posts", response_model=None)
        async def mobile_ai_circle_posts(
            limit: int = Query(default=50, ge=1, le=100),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            try:
                await ports.sync_circle()
            except RECOVERABLE_ERRORS:
                logger.warning("circle: modstore report sync skipped", exc_info=True)
            uid, _, _ = ports.ai_circle_user(user)
            posts = ports.list_posts(user_id=uid, limit=limit)
            profiles = ports.ai_circle_employee_profiles()
            for post in posts:
                profile = profiles.get(str(post.get("employee_id") or ""))
                if profile:
                    post["author_name"] = profile["name"]
                    post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
            return format_mobile_response(data={"items": posts, "count": len(posts)})

        self.mobile_ai_circle_posts = mobile_ai_circle_posts

        @router.post("/circle/posts", response_model=None)
        async def mobile_ai_circle_create_post(
            body: AiCirclePostBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            uid, name, avatar = ports.ai_circle_user(user)
            try:
                post_id = ports.create_post(
                    user_id=uid, author_name=name, avatar=avatar, body=body.body
                )
                return format_mobile_response(data={"id": post_id}, message="发布成功")
            except ValueError:
                return JSONResponse(
                    format_mobile_response(None, "动态内容无效", success=False, code=400),
                    status_code=400,
                )

        self.mobile_ai_circle_create_post = mobile_ai_circle_create_post

        @router.post("/circle/posts/{post_id}/like", response_model=None)
        async def mobile_ai_circle_toggle_like(
            post_id: int, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            uid, _, _ = ports.ai_circle_user(user)
            try:
                liked = ports.toggle_like(post_id=post_id, user_id=uid)
                return format_mobile_response(data={"liked": liked})
            except LookupError:
                return JSONResponse(
                    format_mobile_response(None, "动态不存在", success=False, code=404),
                    status_code=404,
                )

        self.mobile_ai_circle_toggle_like = mobile_ai_circle_toggle_like

        @router.post("/circle/posts/{post_id}/comments", response_model=None)
        async def mobile_ai_circle_add_comment(
            post_id: int,
            body: AiCircleCommentBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401),
                    status_code=401,
                )

            uid, name, _ = ports.ai_circle_user(user)
            try:
                comment_id = ports.add_comment(
                    post_id=post_id, user_id=uid, author_name=name, body=body.body
                )
                return format_mobile_response(data={"id": comment_id}, message="评论成功")
            except ValueError:
                return JSONResponse(
                    format_mobile_response(None, "评论内容无效", success=False, code=400),
                    status_code=400,
                )
            except LookupError:
                return JSONResponse(
                    format_mobile_response(None, "动态不存在", success=False, code=404),
                    status_code=404,
                )

        self.mobile_ai_circle_add_comment = mobile_ai_circle_add_comment
