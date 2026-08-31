"""IM V0 REST + WebSocket。"""

import asyncio
import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
)
from fastapi.responses import JSONResponse

from app.application.ai_group_chat_service import (
    AiGroupChatService as AiGroupChatService,
)
from app.application.claude_super_employee_service import (
    ClaudeSuperEmployeeService as ClaudeSuperEmployeeService,
)
from app.application.codex_super_employee_service import (
    CodexSuperEmployeeService as CodexSuperEmployeeService,
)
from app.application.cursor_super_employee_service import (
    CursorSuperEmployeeService as CursorSuperEmployeeService,
)
from app.application.execution_scope import factory_context as factory_context
from app.application.im_app_service import ImApplicationService, ensure_im_tables
from app.application.trae_super_employee_service import (
    TraeSuperEmployeeService as TraeSuperEmployeeService,
)
from app.application.workspaces import get_workspace_registry as get_workspace_registry
from app.config import Config
from app.db import HostSessionLocal, get_host_engine
from app.fastapi_routes.im_cs_admin_routes import router as im_cs_admin_router
from app.infrastructure.auth.dependencies import (
    CurrentUser,
    get_current_user,
    require_identified_user,
)
from app.infrastructure.im.ws_hub import im_ws_hub
from app.mod_sdk import assistant_ssot as assistant_ssot
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["im-v0"])
# FastAPI 0.138 wraps nested include_router calls; the route registry and golden
# snapshot inspect one level, so keep extracted admin routes flat on this router.
router.routes.extend(im_cs_admin_router.routes)

_schema_ready = False
_IM_UNAVAILABLE = "即时通信服务暂时不可用，请稍后重试"


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


def _uid_for_request(request: Request, user: CurrentUser) -> int:
    """从 session 用户或手机 JWT Bearer 解析当前 uid。

    IM 端点同时被管理端(session 鉴权)和手机端(手机 JWT Bearer)调用，而
    require_identified_user 只认 session，手机 Bearer 会回落到匿名(uid 0)→
    会话成员校验 403。手机 Bearer 存在时优先用它解出的真实 uid。无硬编码。
    """
    try:
        from app.security.mobile_jwt import user_id_from_mobile_bearer

        bearer_uid = user_id_from_mobile_bearer(request.headers.get("Authorization"))
        if bearer_uid:
            return int(bearer_uid)
    except (ImportError, ValueError, TypeError):
        pass
    if user is not None and user.user_id is not None:
        return int(user.user_id)
    raise HTTPException(
        status_code=401,
        detail={"error": "user_id_required", "message": "请先登录后再执行此操作。"},
    )


def _is_admin_customer_service_session(request: Request, db) -> bool:
    try:
        from app.db.models.user import Session as UserSession
        from app.infrastructure.auth.dependencies import session_id_from_request

        sid = session_id_from_request(request)
        if not sid:
            return False
        row = db.query(UserSession).filter(UserSession.session_id == sid).first()
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        return False
    return bool(
        row is not None
        and str(getattr(row, "account_kind", "") or "").strip() == "admin"
        and bool(getattr(row, "market_is_admin", False))
    )


def _include_enterprise_dedicated_cs(request: Request, db) -> bool:
    return not _is_admin_customer_service_session(request, db)


def _require_admin_customer_service_session(request: Request, db) -> JSONResponse | None:
    from app.application.desktop_admin_gate import forbidden_payload, is_desktop_runtime

    if is_desktop_runtime():
        return JSONResponse(forbidden_payload(), status_code=403)
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


async def _notify_offline_im_members(
    member_ids: list[int], sender_id: int, body: str, *, title: str = "新消息"
) -> None:
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
                    title=title,
                    body=preview,
                    # channel 必须是 App 已注册渠道 xcagi_chat/sync/approval/system；原值未注册，
                    # Android O+ 会直接丢弃整条通知(所有 IM 离线通知都不弹的真因之一)。
                    data={
                        "channel": "xcagi_chat",
                        "type": "im_message",
                        "route": "xcagi://chat",
                    },
                )
            except RECOVERABLE_ERRORS:
                logger.exception("im offline push user %s failed", uid)
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
        logger.exception("im_list_conversations")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
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
    except RECOVERABLE_ERRORS:
        logger.exception("im_list_contacts")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
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
    except ValueError:
        return JSONResponse({"success": False, "message": "会话参数无效"}, status_code=400)
    except RECOVERABLE_ERRORS:
        logger.exception("im_create_direct")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/conversations/{conversation_id}/messages")
def im_list_messages(
    request: Request,
    conversation_id: int,
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None),
):
    uid = _uid_for_request(request, user)  # 先鉴权再碰库:匿名请求必须 401,不能因 DB 不可用变 500
    _ensure_schema()
    db = HostSessionLocal()
    try:
        svc = ImApplicationService(db)
        messages = svc.list_messages(conversation_id, uid, limit=limit, before_id=before_id)
        # 打开会话(首屏,非分页上拉)即视为已读:推进当前用户的已读游标,清未读角标。
        # 安卓 FhdApi 没有独立 /read 端点,IM 会话(员工/普通)的未读全靠这里清。
        if before_id is None and messages:
            try:
                last_id = int(messages[-1].get("id") or 0)
                if last_id > 0:
                    svc.mark_read(conversation_id, uid, last_id)
            except RECOVERABLE_ERRORS:  # noqa: BLE001 - 标已读失败不应影响读消息本身
                logger.debug("im_list_messages auto mark_read skipped", exc_info=True)
        return {"success": True, "messages": messages}
    except PermissionError:
        return JSONResponse({"success": False, "message": "无权访问该会话"}, status_code=403)
    except RECOVERABLE_ERRORS:
        logger.exception("im_list_messages")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/{conversation_id}/messages")
async def im_send_message(
    request: Request,
    conversation_id: int,
    background_tasks: BackgroundTasks,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(get_current_user),
):
    uid = _uid_for_request(request, user)  # 先鉴权再碰库:匿名请求必须 401,不能因 DB 不可用变 500
    _ensure_schema()
    db = HostSessionLocal()
    try:
        svc = ImApplicationService(db)
        text = str(body.get("body") or "")
        from app.application.enterprise_cs_automation import (
            EnterpriseCsAutomationService,
            process_enterprise_cs_customer_message,
        )

        is_enterprise_cs = EnterpriseCsAutomationService(db).is_enterprise_cs_conversation(
            conversation_id, uid
        )
        result = svc.send_message(
            conversation_id,
            uid,
            text,
            origin="customer" if is_enterprise_cs else "user",
        )
        emp_peer_id = svc.employee_id_for_conversation(conversation_id, uid)
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
        # 入站回流（与手机端 internal_im.im_post_message 对齐）：老板在桌面/Web 给某 AI 员工
        # 发消息 → 回流 MODstore（答 pending 问题或转 boss_im 新任务），员工才有下文。
        if emp_peer_id:
            try:
                from app.infrastructure.im.employee_reply_relay import (
                    relay_boss_reply_to_employee,
                )

                await asyncio.to_thread(relay_boss_reply_to_employee, uid, emp_peer_id, text)
            except RECOVERABLE_ERRORS:
                logger.debug("im_send_message employee relay skipped", exc_info=True)
        if is_enterprise_cs and background_tasks is not None:
            background_tasks.add_task(
                process_enterprise_cs_customer_message,
                conversation_id,
                uid,
                int((result.get("message") or {}).get("id") or 0),
                text,
            )
        return {"success": True, **result}
    except PermissionError:
        return JSONResponse({"success": False, "message": "无权访问该会话"}, status_code=403)
    except ValueError:
        return JSONResponse({"success": False, "message": "消息参数无效"}, status_code=400)
    except RECOVERABLE_ERRORS:
        logger.exception("im_send_message")
        return JSONResponse({"success": False, "message": _IM_UNAVAILABLE}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/{conversation_id}/read")
async def im_mark_read(
    request: Request,
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(get_current_user),
):
    uid = _uid_for_request(request, user)  # 先鉴权再碰库:匿名请求必须 401,不能因 DB 不可用变 500
    _ensure_schema()
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
    except PermissionError:
        return JSONResponse({"success": False, "message": "无权执行该操作"}, status_code=403)
    except RECOVERABLE_ERRORS:
        logger.exception("im_mark_read")
        return JSONResponse(
            {"success": False, "message": "消息服务暂时不可用，请稍后重试"},
            status_code=500,
        )
    finally:
        db.close()


from app.fastapi_routes import im_ai_group_routes as _ai_group_routes
from app.fastapi_routes import im_super_employee_routes as _super_employee_routes
from app.fastapi_routes import im_websocket_route as _websocket_route

router.routes.extend(_super_employee_routes.router.routes)
router.routes.extend(_ai_group_routes.router.routes)
router.routes.extend(_websocket_route.router.routes)

codex_super_employee_messages = _super_employee_routes.codex_super_employee_messages
codex_super_employee_invoke = _super_employee_routes.codex_super_employee_invoke
claude_super_employee_messages = _super_employee_routes.claude_super_employee_messages
claude_super_employee_invoke = _super_employee_routes.claude_super_employee_invoke
admin_factory_workspaces = _super_employee_routes.admin_factory_workspaces
admin_factory_employees = _super_employee_routes.admin_factory_employees
cursor_super_employee_messages = _super_employee_routes.cursor_super_employee_messages
cursor_super_employee_invoke = _super_employee_routes.cursor_super_employee_invoke
trae_super_employee_messages = _super_employee_routes.trae_super_employee_messages
trae_super_employee_invoke = _super_employee_routes.trae_super_employee_invoke
_ai_group_guard = _ai_group_routes._ai_group_guard
admin_ai_groups_list = _ai_group_routes.admin_ai_groups_list
admin_ai_group_candidates = _ai_group_routes.admin_ai_group_candidates
admin_ai_groups_create = _ai_group_routes.admin_ai_groups_create
admin_ai_group_messages = _ai_group_routes.admin_ai_group_messages
admin_ai_group_post = _ai_group_routes.admin_ai_group_post
admin_ai_group_add_member = _ai_group_routes.admin_ai_group_add_member
admin_ai_group_remove_member = _ai_group_routes.admin_ai_group_remove_member

im_websocket = _websocket_route.im_websocket
