"""AI group-chat mobile routes (strangler extract)."""

from __future__ import annotations

import importlib
import logging
from typing import cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
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
router: APIRouter = APIRouter()


def _parent():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


def _require_mobile_admin_or_enterprise(request: Request, user):
    return _parent()._require_mobile_admin_or_enterprise(request, user)


def AiGroupChatService(*args, **kwargs):
    """Resolve through the parent compatibility surface so legacy patches apply."""
    return _parent().AiGroupChatService(*args, **kwargs)


# ── AI 群聊（微信式多 AI 群组）──


def _mobile_group_uid(request: Request, user) -> int:
    parent = _parent()
    override = getattr(parent, "_mobile_group_uid", None)
    if override is not None and override is not _mobile_group_uid:
        return cast("int", override(request, user))
    return cast("int", parent._mobile_request_user_id(request, user))


def _mobile_group_mode(request: Request) -> str:
    """从 session 判定群聊模式：admin（6 部门 + 上岗员工）或 enterprise（4 部门 + 上架/未上架）。"""
    parent = _parent()
    override = getattr(parent, "_mobile_group_mode", None)
    if override is not None and override is not _mobile_group_mode:
        return cast("str", override(request))
    meta = parent._mobile_session_meta(request) or {}
    return (
        "admin" if str(meta.get("account_kind") or "").strip().lower() == "admin" else "enterprise"
    )


@router.get("/git/branches")
async def mobile_git_branches(request: Request, user=Depends(get_mobile_user)):
    """列出手机端可选工作分支：优先本地 repo，部署包无 .git 时退到远端 heads。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
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


@router.get("/ai-groups")
async def mobile_ai_groups_list(request: Request, user=Depends(get_mobile_user)):
    """列出当前用户的 AI 群聊（首次自动按 6 个部门种出 6 个群）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        groups = AiGroupChatService(mode=_mobile_group_mode(request)).list_groups(user_id=uid)
        return format_mobile_response(data={"groups": groups})
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_groups_list")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.get("/ai-groups/candidates")
async def mobile_ai_group_candidates(request: Request, user=Depends(get_mobile_user)):
    """可拉入群聊的 AI 员工候选（普通员工 + 超级员工）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        candidates = AiGroupChatService(mode=_mobile_group_mode(request)).list_member_candidates()
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


@router.post("/ai-groups")
async def mobile_ai_groups_create(
    request: Request, body: AiGroupCreateBody, user=Depends(get_mobile_user)
):
    """创建自定义 AI 群聊。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).create_group(
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


@router.get("/ai-groups/{group_id}/messages")
async def mobile_ai_group_messages(
    request: Request,
    group_id: str,
    limit: int = Query(default=100, ge=1, le=300),
    user=Depends(get_mobile_user),
):
    """拉取某个 AI 群聊的历史消息。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        messages = AiGroupChatService(mode=_mobile_group_mode(request)).get_messages(
            user_id=uid, group_id=group_id, limit=limit
        )
        return format_mobile_response(data={"messages": messages})
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_group_messages")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/ai-groups/{group_id}/messages")
async def mobile_ai_group_post(
    request: Request, group_id: str, body: AiGroupMessageBody, user=Depends(get_mobile_user)
):
    """在 AI 群聊里发消息：群成员各回一条；@ 了具体成员则只有 TA 回复。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        branch_context = _mobile_branch_context_from_body(body)
        result = await AiGroupChatService(mode=_mobile_group_mode(request)).post_message(
            user_id=uid,
            group_id=group_id,
            text=body.message,
            sender_name=body.sender_name or "我",
            mentions=body.mentions,
            dispatch=bool(body.dispatch),
            branch_context=branch_context,
            context=body.context if isinstance(getattr(body, "context", None), dict) else {},
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


@router.post("/ai-groups/{group_id}/members")
async def mobile_ai_group_add_member(
    request: Request, group_id: str, body: AiGroupMemberBody, user=Depends(get_mobile_user)
):
    """把一个 AI 员工拉进群。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).add_member(
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


@router.delete("/ai-groups/{group_id}/members/{employee_id}")
async def mobile_ai_group_remove_member(
    request: Request, group_id: str, employee_id: str, user=Depends(get_mobile_user)
):
    """把一个 AI 员工移出群。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).remove_member(
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


@router.put("/ai-groups/{group_id}/pin")
async def mobile_ai_group_toggle_pin(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """切换群聊置顶状态。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).toggle_pinned(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_group_toggle_pin")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/ai-groups/{group_id}/mark-unread")
async def mobile_ai_group_mark_unread(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """标为未读（显示小红点）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).mark_unread(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_group_mark_unread")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/ai-groups/{group_id}/mark-read")
async def mobile_ai_group_mark_read(request: Request, group_id: str, user=Depends(get_mobile_user)):
    """清除未读标记。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).mark_read(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_group_mark_read")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.put("/ai-groups/{group_id}/followed")
async def mobile_ai_group_toggle_followed(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """切换是否关注（不再关注则不显示未读）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).toggle_followed(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_group_toggle_followed")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.put("/ai-groups/{group_id}/hidden")
async def mobile_ai_group_toggle_hidden(
    request: Request, group_id: str, user=Depends(get_mobile_user)
):
    """切换是否隐藏（不显示/恢复显示该聊天）。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        group = AiGroupChatService(mode=_mobile_group_mode(request)).toggle_hidden(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data={"group": group})
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_group_toggle_hidden")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.delete("/ai-groups/{group_id}")
async def mobile_ai_group_delete(request: Request, group_id: str, user=Depends(get_mobile_user)):
    """删除群聊。"""
    _, err = _require_mobile_admin_or_enterprise(request, user)
    if err is not None:
        return err
    uid = _mobile_group_uid(request, user)
    if uid <= 0:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        result = AiGroupChatService(mode=_mobile_group_mode(request)).delete_group(
            user_id=uid, group_id=group_id
        )
        return format_mobile_response(data=result)
    except ValueError:
        return JSONResponse(
            format_mobile_response(None, "AI 群组请求无效", success=False, code=400),
            status_code=400,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("mobile_ai_group_delete")
        return JSONResponse(
            format_mobile_response(None, "AI 群组服务暂不可用", success=False, code=500),
            status_code=500,
        )
