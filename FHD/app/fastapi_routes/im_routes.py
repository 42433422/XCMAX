"""IM V0 REST + WebSocket。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.application.ai_group_chat_service import AiGroupChatService
from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.application.cursor_super_employee_service import CursorSuperEmployeeService
from app.application.execution_scope import factory_context
from app.application.im_app_service import ImApplicationService, ensure_im_tables
from app.application.trae_super_employee_service import TraeSuperEmployeeService
from app.application.workspaces import get_workspace_registry
from app.config import Config
from app.db import HostSessionLocal, get_host_engine
from app.infrastructure.auth.dependencies import (
    CurrentUser,
    require_identified_user,
)
from app.infrastructure.im.ws_hub import im_ws_hub
from app.mod_sdk import assistant_ssot
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["im-v0"])

_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    ensure_im_tables(get_host_engine())
    _schema_ready = True


def _uid(user: CurrentUser) -> int:
    if user.user_id is None:
        raise ValueError("user_id required")
    return int(user.user_id)


def _is_admin_customer_service_session(request: Request, db) -> bool:
    try:
        from app.db.models.user import Session as UserSession
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
        if not sid:
            return False
        row = db.query(UserSession).filter(UserSession.session_id == sid).first()
    except Exception:  # noqa: BLE001
        return False
    return bool(
        row is not None
        and str(getattr(row, "account_kind", "") or "").strip() == "admin"
        and bool(getattr(row, "market_is_admin", False))
    )


def _include_enterprise_dedicated_cs(request: Request, db) -> bool:
    return not _is_admin_customer_service_session(request, db)


def _require_admin_customer_service_session(request: Request, db) -> JSONResponse | None:
    if _is_admin_customer_service_session(request, db):
        return None
    return JSONResponse(
        {"success": False, "message": "仅管理端可调用 Codex 超级员工"}, status_code=403
    )


def _resolve_ws_user_id(ws: WebSocket) -> int | None:
    from app.infrastructure.auth.dependencies import _allow_x_user_id_header

    if _allow_x_user_id_header():
        q_uid = ws.query_params.get("user_id")
        if q_uid and str(q_uid).strip().isdigit():
            return int(str(q_uid).strip())

    cookie_name = getattr(Config, "SESSION_COOKIE_NAME", "session_id")
    sid = ws.cookies.get(cookie_name) or ws.query_params.get("session_id")
    if not sid:
        return None
    from app.application.facades.session_facade import get_session_service

    user = get_session_service().validate_session(str(sid).strip())
    if user is None:
        return None
    return int(user.id)


async def _notify_offline_im_members(member_ids: list[int], sender_id: int, body: str) -> None:
    try:
        from app.infrastructure.im import ws_hub as ws_hub_module

        source_hub = ws_hub_module.im_ws_hub
    except (ImportError, AttributeError):
        source_hub = im_ws_hub
    local_is_mock = hasattr(im_ws_hub, "mock_calls")
    source_is_mock = hasattr(source_hub, "mock_calls")
    hub = im_ws_hub if local_is_mock or not source_is_mock else source_hub
    online = set(hub.connected_user_ids())
    offline = [int(mid) for mid in member_ids if int(mid) != sender_id and int(mid) not in online]
    if not offline:
        return
    try:
        from app.application.mobile_push_app_service import notify_mobile_user

        preview = (body or "").strip()[:120] or "新消息"
        for uid in offline:
            try:
                notify_mobile_user(
                    uid,
                    title="新消息",
                    body=preview,
                    data={"channel": "xcagi_im", "type": "im_message"},
                )
            except Exception:
                logger.exception("im offline push user %s failed", uid)
    except Exception:
        logger.exception("im offline push failed")


@router.get("/api/im/conversations")
def im_list_conversations(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        items = ImApplicationService(db).list_conversations(
            uid,
            include_enterprise_dedicated_cs=_include_enterprise_dedicated_cs(request, db),
        )
        return {"success": True, "user_id": uid, "conversations": items}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_list_conversations")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/contacts")
def im_list_contacts(
    request: Request,
    q: str | None = Query(default=None),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        contacts = ImApplicationService(db).list_contacts(
            uid,
            include_enterprise_dedicated_cs=_include_enterprise_dedicated_cs(request, db),
        )
        keyword = (q or "").strip().lower()
        if keyword:
            contacts = [
                c
                for c in contacts
                if keyword in str(c.get("display_name", "")).lower()
                or keyword in str(c.get("username", "")).lower()
            ]
        return {"success": True, "contacts": contacts}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_list_contacts")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/unread-total")
def im_unread_total(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        items = ImApplicationService(db).list_conversations(
            uid,
            include_enterprise_dedicated_cs=_include_enterprise_dedicated_cs(request, db),
        )
        total = sum(int(c.get("unread_count") or 0) for c in items)
        return {"success": True, "unread_total": total}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_unread_total")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/cs/inbox")
def im_cs_inbox(request: Request, user: CurrentUser = Depends(require_identified_user)):
    """运营者(管理端)客服收件箱:所有企业客户↔企业专属客服会话(手机端+桌面端同源)。"""
    _ensure_schema()
    db = HostSessionLocal()
    try:
        if not _is_admin_customer_service_session(request, db):
            return JSONResponse({"success": False, "message": "需要管理端客服会话"}, status_code=403)
        items = ImApplicationService(db).list_cs_inbox()
        return {"success": True, "conversations": items}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_cs_inbox")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/cs/inbox/{conversation_id}/messages")
def im_cs_inbox_messages(
    conversation_id: int,
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
):
    """运营者读某客服会话历史。"""
    _ensure_schema()
    db = HostSessionLocal()
    try:
        if not _is_admin_customer_service_session(request, db):
            return JSONResponse({"success": False, "message": "需要管理端客服会话"}, status_code=403)
        messages = ImApplicationService(db).cs_inbox_messages(conversation_id)
        return {"success": True, "messages": messages}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_cs_inbox_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/cs/inbox/{conversation_id}/reply")
def im_cs_inbox_reply(
    conversation_id: int,
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    """运营者以「企业专属客服」身份回复客户(客户端轮询取回)。"""
    _ensure_schema()
    db = HostSessionLocal()
    try:
        if not _is_admin_customer_service_session(request, db):
            return JSONResponse({"success": False, "message": "需要管理端客服会话"}, status_code=403)
        text = str(body.get("body") or "").strip()
        if not text:
            return JSONResponse({"success": False, "message": "消息不能为空"}, status_code=400)
        result = ImApplicationService(db).cs_reply(conversation_id, text)
        return {"success": True, **result}
    except (ValueError, PermissionError) as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_cs_inbox_reply")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/direct")
def im_create_direct(
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    peer = int(body.get("peer_user_id") or 0)
    if peer <= 0:
        return JSONResponse({"success": False, "message": "peer_user_id 无效"}, status_code=400)
    db = HostSessionLocal()
    try:
        conv = ImApplicationService(db).get_or_create_direct(uid, peer)
        return {"success": True, "conversation": conv}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_create_direct")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/conversations/{conversation_id}/messages")
def im_list_messages(
    conversation_id: int,
    user: CurrentUser = Depends(require_identified_user),
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None),
):
    _ensure_schema()
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        messages = ImApplicationService(db).list_messages(
            conversation_id, uid, limit=limit, before_id=before_id
        )
        return {"success": True, "messages": messages}
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_list_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/{conversation_id}/messages")
async def im_send_message(
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        svc = ImApplicationService(db)
        text = str(body.get("body") or "")
        result = svc.send_message(conversation_id, uid, text)
        legacy_payload = {
            "type": "message",
            "conversation_id": conversation_id,
            "message": result["message"],
        }
        sync_payload = {
            "type": "im.message",
            "conversation_id": conversation_id,
            "message": result["message"],
            "updated_at_ms": result.get("updated_at_ms"),
        }
        member_ids = [int(mid) for mid in (result.get("member_user_ids") or [])]
        for member_id in member_ids:
            if member_id != uid:
                await im_ws_hub.send_to_user(member_id, legacy_payload)
                await im_ws_hub.send_to_user(member_id, sync_payload)
        await _notify_offline_im_members(member_ids, uid, text)
        # 入站回流：若老板是在「某员工」的聊天页回复，把回复回流为该员工最新 pending 问题的答案，
        # 让阻塞中的员工解阻塞继续（无 pending 问题时静默忽略，普通闲聊不受影响）。
        try:
            emp_id = svc.employee_id_for_conversation(conversation_id, uid)
            if emp_id:
                _relay_employee_answer(uid, emp_id, text)
        except RECOVERABLE_ERRORS:
            logger.debug("employee answer relay skipped", exc_info=True)
        return {"success": True, **result}
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_send_message")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


def _im_internal_api_key() -> str:
    import os

    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def _modstore_internal_base() -> str:
    import os

    return (
        (
            os.environ.get("XCAGI_MODSTORE_INTERNAL_URL")
            or os.environ.get("MODSTORE_INTERNAL_BASE_URL")
            or os.environ.get("MODSTORE_PUBLIC_API_BASE")
            or "http://127.0.0.1:9999"
        )
        .strip()
        .rstrip("/")
    )


def _relay_employee_answer(boss_user_id: int, employee_id: str, answer: str) -> None:
    """入站回流：老板在某员工 IM 聊天页回复 → 回流成该员工最新 pending 问题的答案（best-effort）。

    调 MODstore 内部端点 ``/api/admin/employee-autonomy/internal/answer-latest``，使阻塞中的
    ``ask_human_blocking`` 轮询到 answered 后解阻塞继续。无 pending 问题时静默忽略（普通闲聊不触发）。
    """
    key = _im_internal_api_key()
    text = (answer or "").strip()
    if not key or int(boss_user_id or 0) <= 0 or not str(employee_id or "").strip() or not text:
        return
    try:
        import httpx

        with httpx.Client(timeout=5) as client:
            client.post(
                f"{_modstore_internal_base()}/api/admin/employee-autonomy/internal/answer-latest",
                headers={"X-Internal-Api-Key": key},
                json={
                    "user_id": int(boss_user_id),
                    "employee_id": str(employee_id),
                    "answer": text,
                },
            )
    except Exception as exc:  # noqa: BLE001 - 回流失败不影响 IM 主流程
        logger.warning("relay_employee_answer failed: %s", exc)


@router.post("/api/internal/im/employee-message")
async def im_internal_employee_message(
    request: Request,
    body: dict = Body(default_factory=dict),
):
    """内部端点：以某 AI 员工身份，把一条消息投递进老板的 1:1 IM 会话。

    打通「员工→IM 聊天页」出站半边：phase-D 员工不确定性提问（MODstore）经此让问题作为
    该员工发来的 IM 消息出现在其聊天页，并实时推送给老板。仅限内部服务经 ``X-Internal-Api-Key``
    调用。Body: ``{boss_user_id, employee_id, body, display_name?, question_id?}``。
    """
    expected = _im_internal_api_key()
    provided = (request.headers.get("X-Internal-Api-Key") or "").strip()
    if not expected or provided != expected:
        return JSONResponse({"success": False, "message": "unauthorized"}, status_code=401)
    try:
        boss_user_id = int(body.get("boss_user_id") or body.get("user_id") or 0)
    except (TypeError, ValueError):
        boss_user_id = 0
    employee_id = str(body.get("employee_id") or "").strip()
    text = str(body.get("body") or body.get("text") or "").strip()
    display_name = str(body.get("display_name") or "").strip()
    if boss_user_id <= 0 or not employee_id or not text:
        return JSONResponse(
            {"success": False, "message": "boss_user_id/employee_id/body required"},
            status_code=400,
        )
    _ensure_schema()
    db = HostSessionLocal()
    try:
        result = ImApplicationService(db).post_employee_message(
            boss_user_id=boss_user_id,
            employee_id=employee_id,
            body=text,
            display_name=display_name,
        )
        if not result:
            return JSONResponse({"success": False, "message": "post failed"}, status_code=400)
        conversation_id = int(result["conversation_id"])
        legacy_payload = {
            "type": "message",
            "conversation_id": conversation_id,
            "message": result["message"],
        }
        sync_payload = {
            "type": "im.message",
            "conversation_id": conversation_id,
            "message": result["message"],
            "updated_at_ms": result.get("updated_at_ms"),
        }
        await im_ws_hub.send_to_user(int(boss_user_id), legacy_payload)
        await im_ws_hub.send_to_user(int(boss_user_id), sync_payload)
        try:
            await _notify_offline_im_members(
                [int(boss_user_id)], int(result["employee_user_id"]), text
            )
        except RECOVERABLE_ERRORS:
            logger.debug("employee im offline push skipped", exc_info=True)
        return {"success": True, **result}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_internal_employee_message")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/{conversation_id}/read")
async def im_mark_read(
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    last_id = int(body.get("last_message_id") or 0)
    db = HostSessionLocal()
    try:
        result = ImApplicationService(db).mark_read(conversation_id, uid, last_id)
        read_payload = {
            "type": "im.read",
            "conversation_id": conversation_id,
            "user_id": uid,
            "last_message_id": result["last_read_message_id"],
            "updated_at_ms": result.get("updated_at_ms"),
        }
        for member_id in result.get("member_user_ids") or []:
            if int(member_id) != uid:
                await im_ws_hub.send_to_user(int(member_id), read_payload)
        return {"success": True, **result}
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_mark_read")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/admin/codex-super-employee/messages")
def codex_super_employee_messages(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
    limit: int = Query(default=80, ge=1, le=200),
):
    """管理端 Codex 超级员工软件内对话记录。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = CodexSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {"success": True, "messages": messages}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("codex_super_employee_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/admin/codex-super-employee/messages")
def codex_super_employee_invoke(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    """管理端 Codex 超级员工软件内调用入口。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get("message") or body.get("body") or "").strip()
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        # 管理端=平台操作者：铸造工厂授权（受 XCMAX_FACTORY_CAPABILITY_TOKEN 门控，未配则降产品域）。
        # workspace_id 可来自顶层 body 或前端 context（项目选择器）；缺省=自举项目 xcmax。
        workspace_id = str(body.get("workspace_id") or context.get("workspace_id") or "xcmax")
        context = factory_context(workspace_id=workspace_id, base=context)
        result = CodexSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {"success": True, **result}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("codex_super_employee_invoke")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/admin/claude-super-employee/messages")
def claude_super_employee_messages(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
    limit: int = Query(default=80, ge=1, le=200),
):
    """管理端 Claude 超级员工软件内对话记录。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = ClaudeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {"success": True, "messages": messages}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("claude_super_employee_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/admin/claude-super-employee/messages")
def claude_super_employee_invoke(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    """管理端 Claude 超级员工软件内调用入口。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get("message") or body.get("body") or "").strip()
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        # 管理端=平台操作者：铸造工厂授权（受 XCMAX_FACTORY_CAPABILITY_TOKEN 门控，未配则降产品域）。
        # workspace_id 可来自顶层 body 或前端 context（项目选择器）；缺省=自举项目 xcmax。
        workspace_id = str(body.get("workspace_id") or context.get("workspace_id") or "xcmax")
        context = factory_context(workspace_id=workspace_id, base=context)
        result = ClaudeSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {"success": True, **result}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("claude_super_employee_invoke")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


# ── 顶层管理端「项目工厂」控制台（闭环：选项目 → 选工厂员工 → 派工）──


@router.get("/api/admin/factory/workspaces")
def admin_factory_workspaces(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
):
    """列出工厂可派工的项目 Workspace（仅平台管理端可见）。"""
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        items = [
            {
                "id": ws.id,
                "label": ws.label,
                "isolation": ws.isolation,
                "default_branch": ws.default_branch,
                "vcs_kind": ws.vcs_kind,
            }
            for ws in get_workspace_registry().list()
        ]
        return {"success": True, "workspaces": items}
    except RECOVERABLE_ERRORS:
        logger.exception("admin_factory_workspaces")
        return JSONResponse({"success": False, "message": "加载项目列表失败"}, status_code=500)
    finally:
        db.close()


@router.get("/api/admin/factory/employees")
def admin_factory_employees(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
):
    """列出工厂版超级员工身份（仅平台管理端可见；绝不进客户选人器）。

    每个工厂员工映射到底层工具的现有超级员工对话端点——管理端发消息时带
    ``context.workspace_id`` 选项目，路由侧自动铸造工厂授权并对该 Workspace 派工。
    """
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        tool_endpoint = {
            "Claude": "/api/admin/claude-super-employee/messages",
            "Codex": "/api/admin/codex-super-employee/messages",
            "Cursor": "/api/admin/cursor-super-employee/messages",
            "Trae": "/api/admin/trae-super-employee/messages",
        }
        items = [
            {
                "id": meta.get("id"),
                "display_name": meta.get("display_name"),
                "display_tool": meta.get("display_tool"),
                "avatar_letter": meta.get("avatar_letter"),
                "summary": meta.get("summary"),
                "scope": meta.get("scope"),
                "endpoint": tool_endpoint.get(str(meta.get("display_tool") or "")),
            }
            for meta in assistant_ssot.factory_employees().values()
        ]
        return {"success": True, "employees": items}
    except RECOVERABLE_ERRORS:
        logger.exception("admin_factory_employees")
        return JSONResponse({"success": False, "message": "加载工厂员工失败"}, status_code=500)
    finally:
        db.close()


@router.get("/api/admin/cursor-super-employee/messages")
def cursor_super_employee_messages(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
    limit: int = Query(default=80, ge=1, le=200),
):
    """管理端 Cursor 超级员工软件内对话记录。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = CursorSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {"success": True, "messages": messages}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("cursor_super_employee_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/admin/cursor-super-employee/messages")
def cursor_super_employee_invoke(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    """管理端 Cursor 超级员工软件内调用入口。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get("message") or body.get("body") or "").strip()
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        result = CursorSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {"success": True, **result}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("cursor_super_employee_invoke")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/admin/trae-super-employee/messages")
def trae_super_employee_messages(
    request: Request,
    user: CurrentUser = Depends(require_identified_user),
    limit: int = Query(default=80, ge=1, le=200),
):
    """管理端 Trae 超级员工软件内对话记录。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        messages = TraeSuperEmployeeService().list_messages(user_id=uid, limit=limit)
        return {"success": True, "messages": messages}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("trae_super_employee_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/admin/trae-super-employee/messages")
def trae_super_employee_invoke(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    """管理端 Trae 超级员工软件内调用入口。"""
    uid = _uid(user)
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        if denied is not None:
            return denied
        text = str(body.get("message") or body.get("body") or "").strip()
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        result = TraeSuperEmployeeService().invoke(user_id=uid, message=text, context=context)
        return {"success": True, **result}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("trae_super_employee_invoke")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


# ── AI 群聊（管理端/桌面）──


def _ai_group_guard(request: Request):
    """复用 Codex 的管理端会话校验；通过返回 uid，否则返回 (None, denied)。"""
    db = HostSessionLocal()
    try:
        denied = _require_admin_customer_service_session(request, db)
        return denied
    finally:
        db.close()


@router.get("/api/admin/ai-groups")
def admin_ai_groups_list(request: Request, user: CurrentUser = Depends(require_identified_user)):
    denied = _ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        groups = AiGroupChatService().list_groups(user_id=_uid(user))
        return {"success": True, "groups": groups}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("admin_ai_groups_list")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/api/admin/ai-groups/candidates")
def admin_ai_group_candidates(
    request: Request, user: CurrentUser = Depends(require_identified_user)
):
    """可拉入群聊的 AI 员工候选（普通员工 + 超级员工）。

    供手机端建群/加成员的选人列表使用，覆盖全部 AI 员工。
    """
    denied = _ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        candidates = AiGroupChatService().list_member_candidates()
        return {"success": True, "candidates": candidates}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("admin_ai_group_candidates")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/api/admin/ai-groups")
def admin_ai_groups_create(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    denied = _ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        group = AiGroupChatService().create_group(
            user_id=_uid(user), name=str(body.get("name") or "")
        )
        return {"success": True, "group": group}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("admin_ai_groups_create")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/api/admin/ai-groups/{group_id}/messages")
def admin_ai_group_messages(
    request: Request,
    group_id: str,
    limit: int = Query(default=100, ge=1, le=300),
    user: CurrentUser = Depends(require_identified_user),
):
    denied = _ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        messages = AiGroupChatService().get_messages(
            user_id=_uid(user), group_id=group_id, limit=limit
        )
        return {"success": True, "messages": messages}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("admin_ai_group_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/api/admin/ai-groups/{group_id}/messages")
async def admin_ai_group_post(
    request: Request,
    group_id: str,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    denied = _ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        mentions = body.get("mentions")
        result = await AiGroupChatService().post_message(
            user_id=_uid(user),
            group_id=group_id,
            text=str(body.get("message") or ""),
            sender_name=str(body.get("sender_name") or "我"),
            mentions=mentions if isinstance(mentions, list) else None,
            dispatch=bool(body.get("dispatch")),
        )
        return {"success": True, **result}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("admin_ai_group_post")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/api/admin/ai-groups/{group_id}/members")
def admin_ai_group_add_member(
    request: Request,
    group_id: str,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    denied = _ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        group = AiGroupChatService().add_member(
            user_id=_uid(user),
            group_id=group_id,
            member={
                "employee_id": str(body.get("employee_id") or ""),
                "mod_id": str(body.get("mod_id") or ""),
                "name": str(body.get("name") or ""),
                "avatar": str(body.get("avatar") or ""),
                "summary": str(body.get("summary") or ""),
            },
        )
        return {"success": True, "group": group}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("admin_ai_group_add_member")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.delete("/api/admin/ai-groups/{group_id}/members/{employee_id}")
def admin_ai_group_remove_member(
    request: Request,
    group_id: str,
    employee_id: str,
    user: CurrentUser = Depends(require_identified_user),
):
    denied = _ai_group_guard(request)
    if denied is not None:
        return denied
    try:
        group = AiGroupChatService().remove_member(
            user_id=_uid(user), group_id=group_id, employee_id=employee_id
        )
        return {"success": True, "group": group}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("admin_ai_group_remove_member")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.websocket("/ws/im")
async def im_websocket(ws: WebSocket):
    _ensure_schema()
    await ws.accept()
    uid = _resolve_ws_user_id(ws)
    if uid is None:
        await ws.close(code=4401, reason="unauthorized")
        return
    await im_ws_hub.connect(uid, ws)
    try:
        while True:
            raw = await ws.receive_text()
            if raw.strip().lower() in {"ping", '{"type":"ping"}'}:
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        await im_ws_hub.disconnect(uid, ws)
