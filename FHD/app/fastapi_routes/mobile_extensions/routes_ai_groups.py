"""GroupRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.application.mobile_extensions.protocols import (
    AiGroupChatServiceFactory,
    MobileGroupModeCall,
    MobileGroupUidCall,
    MobilePrincipal,
    MobileRequestUserIdCall,
    MobileSessionMetaCall,
    RequireMobileAdminOrEnterpriseCall,
    UserDependency,
)
from app.fastapi_routes.mobile_extensions.mobile_git_branches import (
    branch_context_from_body as _mobile_branch_context_from_body,
)
from app.fastapi_routes.mobile_extensions.mobile_git_branches import (
    git_branches_from_remote as _mobile_git_branches_from_remote,
)
from app.fastapi_routes.mobile_extensions.mobile_git_branches import (
    git_branches_from_repo as _mobile_git_branches_from_repo,
)
from app.fastapi_routes.mobile_extensions.mobile_git_branches import (
    git_repo_root as _mobile_git_repo_root,
)
from app.fastapi_routes.mobile_extensions.models import (
    AiGroupCreateBody,
    AiGroupMemberBody,
    AiGroupMessageBody,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroupRoutesPorts:
    mobile_request_user_id: MobileRequestUserIdCall
    mobile_session_meta: MobileSessionMetaCall
    require_mobile_admin_or_enterprise: RequireMobileAdminOrEnterpriseCall
    ai_group_service: AiGroupChatServiceFactory
    mobile_group_mode: MobileGroupModeCall
    mobile_group_uid: MobileGroupUidCall


class GroupRoutes:
    def __init__(self, ports: GroupRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _mobile_group_uid(request: Request, user: object) -> int:
            return ports.mobile_request_user_id(request, user)

        self._mobile_group_uid = _mobile_group_uid

        def _mobile_group_mode(request: Request) -> str:
            meta = ports.mobile_session_meta(request) or {}
            return (
                "admin"
                if str(meta.get("account_kind") or "").strip().lower() == "admin"
                else "enterprise"
            )

        self._mobile_group_mode = _mobile_group_mode

        @router.get("/git/branches", response_model=None)
        async def mobile_git_branches(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """列出手机端可选工作分支：优先本地 repo，部署包无 .git 时退到远端 heads。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            try:
                repo = _mobile_git_repo_root()
                branches = _mobile_git_branches_from_repo(repo) if repo else []
                if not branches:
                    branches = _mobile_git_branches_from_remote()
                return format_mobile_response(data={"branches": branches})
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_git_branches")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_git_branches = mobile_git_branches

        @router.get("/ai-groups", response_model=None)
        async def mobile_ai_groups_list(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """列出当前用户的 AI 群聊（首次自动按 6 个部门种出 6 个群）。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            uid = ports.mobile_group_uid(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                groups = ports.ai_group_service(mode=ports.mobile_group_mode(request)).list_groups(
                    user_id=uid
                )
                return format_mobile_response(data={"groups": groups})
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_ai_groups_list")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_ai_groups_list = mobile_ai_groups_list

        @router.get("/ai-groups/candidates", response_model=None)
        async def mobile_ai_group_candidates(
            request: Request, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """可拉入群聊的 AI 员工候选（普通员工 + 超级员工）。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            uid = ports.mobile_group_uid(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                candidates = ports.ai_group_service(
                    mode=ports.mobile_group_mode(request)
                ).list_member_candidates()
                return format_mobile_response(
                    data={
                        "candidates": candidates,
                        "items": candidates,
                        "count": len(candidates),
                    }
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_ai_group_candidates")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_ai_group_candidates = mobile_ai_group_candidates

        @router.post("/ai-groups", response_model=None)
        async def mobile_ai_groups_create(
            request: Request,
            body: AiGroupCreateBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """创建自定义 AI 群聊。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            uid = ports.mobile_group_uid(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                group = ports.ai_group_service(mode=ports.mobile_group_mode(request)).create_group(
                    user_id=uid, name=body.name
                )
                return format_mobile_response(data={"group": group})
            except ValueError:
                return JSONResponse(
                    format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
                    status_code=400,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_ai_groups_create")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_ai_groups_create = mobile_ai_groups_create

        @router.get("/ai-groups/{group_id}/messages", response_model=None)
        async def mobile_ai_group_messages(
            request: Request,
            group_id: str,
            limit: int = Query(default=100, ge=1, le=300),
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """拉取某个 AI 群聊的历史消息。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            uid = ports.mobile_group_uid(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                messages = ports.ai_group_service(
                    mode=ports.mobile_group_mode(request)
                ).get_messages(user_id=uid, group_id=group_id, limit=limit)
                return format_mobile_response(data={"messages": messages})
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_ai_group_messages")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_ai_group_messages = mobile_ai_group_messages

        @router.post("/ai-groups/{group_id}/messages", response_model=None)
        async def mobile_ai_group_post(
            request: Request,
            group_id: str,
            body: AiGroupMessageBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """在 AI 群聊里发消息：群成员各回一条；@ 了具体成员则只有 TA 回复。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            uid = ports.mobile_group_uid(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                branch_context = _mobile_branch_context_from_body(body)
                result = await ports.ai_group_service(
                    mode=ports.mobile_group_mode(request)
                ).post_message(
                    user_id=uid,
                    group_id=group_id,
                    text=body.message,
                    sender_name=body.sender_name or "我",
                    mentions=body.mentions,
                    dispatch=bool(body.dispatch),
                    branch_context=branch_context,
                    context=body.context
                    if isinstance(getattr(body, "context", None), dict)
                    else {},
                )
                return format_mobile_response(data=result)
            except ValueError:
                return JSONResponse(
                    format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
                    status_code=400,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_ai_group_post")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_ai_group_post = mobile_ai_group_post

        @router.post("/ai-groups/{group_id}/members", response_model=None)
        async def mobile_ai_group_add_member(
            request: Request,
            group_id: str,
            body: AiGroupMemberBody,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """把一个 AI 员工拉进群。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            uid = ports.mobile_group_uid(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                group = ports.ai_group_service(mode=ports.mobile_group_mode(request)).add_member(
                    user_id=uid,
                    group_id=group_id,
                    member={
                        "employee_id": body.employee_id,
                        "mod_id": body.mod_id,
                        "name": body.name,
                        "avatar": body.avatar,
                        "summary": body.summary,
                    },
                )
                return format_mobile_response(data={"group": group})
            except ValueError:
                return JSONResponse(
                    format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
                    status_code=400,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_ai_group_add_member")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_ai_group_add_member = mobile_ai_group_add_member

        @router.delete("/ai-groups/{group_id}/members/{employee_id}", response_model=None)
        async def mobile_ai_group_remove_member(
            request: Request,
            group_id: str,
            employee_id: str,
            user: MobilePrincipal | None = Depends(get_user),
        ) -> object:
            """把一个 AI 员工移出群。"""
            _, err = ports.require_mobile_admin_or_enterprise(request, user)
            if err is not None:
                return err
            uid = ports.mobile_group_uid(request, user)
            if uid <= 0:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                group = ports.ai_group_service(mode=ports.mobile_group_mode(request)).remove_member(
                    user_id=uid, group_id=group_id, employee_id=employee_id
                )
                return format_mobile_response(data={"group": group})
            except ValueError:
                return JSONResponse(
                    format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
                    status_code=400,
                )
            except RECOVERABLE_ERRORS:
                logger.exception("mobile_ai_group_remove_member")
                return JSONResponse(
                    format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_ai_group_remove_member = mobile_ai_group_remove_member

        @router.put("/ai-groups/{group_id}/pin", response_model=None)
        async def mobile_ai_group_toggle_pin(
            request: Request, group_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """切换群聊置顶状态。"""
            return self._change_state(
                request, group_id, user, "toggle_pinned", "mobile_ai_group_toggle_pin"
            )

        self.mobile_ai_group_toggle_pin = mobile_ai_group_toggle_pin

        @router.post("/ai-groups/{group_id}/mark-unread", response_model=None)
        async def mobile_ai_group_mark_unread(
            request: Request, group_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """标为未读（显示小红点）。"""
            return self._change_state(
                request, group_id, user, "mark_unread", "mobile_ai_group_mark_unread"
            )

        self.mobile_ai_group_mark_unread = mobile_ai_group_mark_unread

        @router.post("/ai-groups/{group_id}/mark-read", response_model=None)
        async def mobile_ai_group_mark_read(
            request: Request, group_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """清除未读标记。"""
            return self._change_state(
                request, group_id, user, "mark_read", "mobile_ai_group_mark_read"
            )

        self.mobile_ai_group_mark_read = mobile_ai_group_mark_read

        @router.put("/ai-groups/{group_id}/followed", response_model=None)
        async def mobile_ai_group_toggle_followed(
            request: Request, group_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """切换是否关注（不再关注则不显示未读）。"""
            return self._change_state(
                request, group_id, user, "toggle_followed", "mobile_ai_group_toggle_followed"
            )

        self.mobile_ai_group_toggle_followed = mobile_ai_group_toggle_followed

        @router.put("/ai-groups/{group_id}/hidden", response_model=None)
        async def mobile_ai_group_toggle_hidden(
            request: Request, group_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """切换是否隐藏（不显示/恢复显示该聊天）。"""
            return self._change_state(
                request, group_id, user, "toggle_hidden", "mobile_ai_group_toggle_hidden"
            )

        self.mobile_ai_group_toggle_hidden = mobile_ai_group_toggle_hidden

        @router.delete("/ai-groups/{group_id}", response_model=None)
        async def mobile_ai_group_delete(
            request: Request, group_id: str, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            """删除群聊。"""
            return self._change_state(
                request, group_id, user, "delete_group", "mobile_ai_group_delete"
            )

        self.mobile_ai_group_delete = mobile_ai_group_delete

    def _change_state(
        self,
        request: Request,
        group_id: str,
        user: object,
        action: Literal[
            "toggle_pinned",
            "mark_unread",
            "mark_read",
            "toggle_followed",
            "toggle_hidden",
            "delete_group",
        ],
        operation: str,
    ) -> object:
        _, error = self.ports.require_mobile_admin_or_enterprise(request, user)
        if error is not None:
            return error
        uid = self.ports.mobile_group_uid(request, user)
        if uid <= 0:
            return JSONResponse(
                format_mobile_response(None, "未授权", success=False, code=401), status_code=401
            )
        try:
            service = self.ports.ai_group_service(mode=self.ports.mobile_group_mode(request))
            if action == "toggle_pinned":
                result = service.toggle_pinned(user_id=uid, group_id=group_id)
            elif action == "mark_unread":
                result = service.mark_unread(user_id=uid, group_id=group_id)
            elif action == "mark_read":
                result = service.mark_read(user_id=uid, group_id=group_id)
            elif action == "toggle_followed":
                result = service.toggle_followed(user_id=uid, group_id=group_id)
            elif action == "toggle_hidden":
                result = service.toggle_hidden(user_id=uid, group_id=group_id)
            elif action == "delete_group":
                result = service.delete_group(user_id=uid, group_id=group_id)
            return format_mobile_response(
                data=result if action == "delete_group" else {"group": result}
            )
        except ValueError:
            return JSONResponse(
                format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
                status_code=400,
            )
        except RECOVERABLE_ERRORS:
            logger.exception(operation)
            return JSONResponse(
                format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
                status_code=500,
            )
