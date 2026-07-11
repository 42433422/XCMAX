"""内部 IM 投递端点（员工→老板 1:1 IM 聊天页）。

独立精简 router：仅依赖 ``ImApplicationService``（只 import IM 模型 + User），避开 im_routes
那条较重的依赖链（execution_scope/workspaces/super_employee 等），确保在精简/陈旧部署上也能挂载。

供 MODstore（phase-D 不确定性问答 / 员工主动汇报）经 ``X-Internal-Api-Key`` 服务端调用：
让员工的话作为「该员工发来的 IM 消息」出现在老板与其的 1:1 会话里（员工真正长出嘴）。
"""

from __future__ import annotations

import logging
import os
import secrets
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.application.im_app_service import ImApplicationService, ensure_im_tables
from app.application.mobile_push_app_service import notify_mobile_user
from app.db import HostSessionLocal, get_host_engine
from app.fastapi_routes.mobile_api import get_mobile_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["internal-im"])


def _mobile_uid(user: Any) -> int:
    for attr in ("id", "user_id"):
        try:
            v = int(getattr(user, attr, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            return v
    return 0


def _modstore_internal_candidates() -> list[str]:
    raw = [
        os.environ.get("XCAGI_MODSTORE_INTERNAL_URL"),
        os.environ.get("MODSTORE_INTERNAL_BASE_URL"),
        os.environ.get("MODSTORE_PLATFORM_URL"),
        os.environ.get("MODSTORE_LOCAL_BASE_URL"),
        "http://127.0.0.1:8788",
        "http://127.0.0.1:8765",
        "http://127.0.0.1:9999",
    ]
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip().rstrip("/")
        if value and _private_internal_url(value) and value not in out:
            out.append(value)
    return out


def _private_internal_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        hostname = str(parsed.hostname or "").strip().lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if hostname == "localhost":
            return True
        address = ip_address(hostname)
        return bool(address.is_loopback or address.is_private)
    except ValueError:
        return False


def _relay_employee_answer(boss_user_id: int, employee_id: str, answer: str) -> None:
    """入站回流：老板在员工聊天页回复 → 回流成该员工最新 pending 问题的答案，解阻塞员工（best-effort）。"""
    key = _internal_api_key()
    text = (answer or "").strip()
    if not key or int(boss_user_id or 0) <= 0 or not str(employee_id or "").strip() or not text:
        return
    try:
        import httpx

        payload = {
            "user_id": int(boss_user_id),
            "employee_id": str(employee_id),
            "answer": text,
        }
        with httpx.Client(timeout=5, trust_env=False) as client:
            for base in _modstore_internal_candidates():
                try:
                    resp = client.post(
                        f"{base}/api/admin/employee-autonomy/internal/answer-latest",
                        headers={"X-Internal-Api-Key": key},
                        json=payload,
                    )
                    if 200 <= resp.status_code < 300:
                        return
                except Exception:  # noqa: BLE001 - probe next known local endpoint
                    continue
    except Exception:  # noqa: BLE001 - 回流失败不影响 IM 主流程
        logger.debug("relay_employee_answer failed", exc_info=True)


def _internal_api_key() -> str:
    from app.security.local_runtime_secret import local_runtime_secret

    return local_runtime_secret(
        "MODSTORE_INTERNAL_API_KEY",
        "XCAGI_MARKET_INTERNAL_API_KEY",
    )


def _resolve_management_owner_principal(
    requested_user_id: int,
    recipient_kind: str,
    recipient_ref: str = "",
) -> tuple[int, int | None]:
    """Translate a cross-database owner reference into a local FHD scope.

    MODstore and FHD intentionally keep separate user tables, so a MODstore
    numeric user id must never be used as an FHD foreign key.  Only the
    explicit management-owner recipient kind is translated; ordinary IM calls
    retain their exact local recipient id.
    """
    requested = int(requested_user_id or 0)
    if str(recipient_kind or "").strip() != "management_owner":
        return requested, None
    ref = str(recipient_ref or "").strip()
    parts = ref.split(":")
    if len(parts) != 5 or parts[0:2] != ["fhd", "user"] or parts[3] != "tenant":
        return 0, None
    try:
        exact_user_id = int(parts[2])
        bound_tenant_id = int(parts[4])
    except (TypeError, ValueError):
        return 0, None
    if (
        exact_user_id <= 0
        or bound_tenant_id < 0
        or ref != f"fhd:user:{exact_user_id}:tenant:{bound_tenant_id}"
    ):
        return 0, None
    try:
        from sqlalchemy import or_

        from app.db.models import User

        db = HostSessionLocal()
        try:
            current_admin = or_(
                User.role.in_(("admin", "super_admin", "owner")),
                User.tier == "admin",
            )
            exact = (
                db.query(User)
                .filter(
                    User.id == exact_user_id,
                    User.is_active.is_(True),
                    current_admin,
                )
                .order_by(User.id.asc())
                .first()
            )
            if exact is not None and int(getattr(exact, "id", 0) or 0) == exact_user_id:
                tenant = getattr(exact, "tenant_id", None)
                current_tenant_id = int(tenant) if tenant is not None else 0
                if current_tenant_id == bound_tenant_id:
                    return exact_user_id, current_tenant_id
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - internal delivery fails closed below
        logger.exception("management owner recipient resolution failed")
    return 0, None


def _resolve_management_owner_user_id(
    requested_user_id: int,
    recipient_kind: str,
    recipient_ref: str = "",
) -> int:
    """Compatibility wrapper used by non-delivery callers and focused tests."""

    return _resolve_management_owner_principal(
        requested_user_id,
        recipient_kind,
        recipient_ref,
    )[0]


@router.post("/api/internal/im/employee-message")
async def internal_employee_message(
    request: Request,
    body: dict = Body(default_factory=dict),
) -> Any:
    """以某 AI 员工身份，把一条消息投进老板的 1:1 IM 会话。

    Body: ``{boss_user_id, employee_id, body, display_name?}``。需 ``X-Internal-Api-Key``。
    """
    expected = _internal_api_key()
    provided = (request.headers.get("X-Internal-Api-Key") or "").strip()
    if not expected or not secrets.compare_digest(provided, expected):
        return JSONResponse({"success": False, "message": "unauthorized"}, status_code=401)
    try:
        requested_boss_user_id = int(body.get("boss_user_id") or body.get("user_id") or 0)
    except (TypeError, ValueError):
        requested_boss_user_id = 0
    employee_id = str(body.get("employee_id") or "").strip()
    text = str(body.get("body") or body.get("text") or "").strip()
    display_name = str(body.get("display_name") or "").strip()
    notification = body.get("notification") if isinstance(body.get("notification"), dict) else {}
    recipient_kind = str(
        notification.get("recipient_kind") or body.get("recipient_kind") or ""
    ).strip()
    recipient_ref = str(
        notification.get("recipient_ref") or body.get("recipient_ref") or ""
    ).strip()
    boss_user_id, management_tenant_id = _resolve_management_owner_principal(
        requested_boss_user_id,
        recipient_kind,
        recipient_ref,
    )
    if boss_user_id <= 0 or not employee_id or not text:
        return JSONResponse(
            {"success": False, "message": "boss_user_id/employee_id/body required"},
            status_code=400,
        )
    if recipient_kind == "management_owner":
        # Management task content is deliberately not an IM message.  The
        # issuer's enterprise pairing has the same numeric FHD user id and can
        # therefore subscribe to the ordinary IM REST/WS surface.  Persist the
        # event only in the management-audience outbox instead.
        try:
            push_result = notify_mobile_user(
                int(boss_user_id),
                title=str(notification.get("title") or display_name or employee_id),
                body=text,
                data={
                    **notification,
                    "route": str(
                        notification.get("route")
                        or f"management_work/{notification.get('task_id') or ''}"
                    ),
                    "channel": str(notification.get("channel") or "management_work"),
                    "recipient_kind": "management_owner",
                },
                audience="management",
                tenant_id=management_tenant_id,
            )
        except Exception:  # noqa: BLE001 - report delivery failure to the caller
            logger.exception("management work outbox delivery failed")
            return JSONResponse(
                {"success": False, "message": "management notification delivery failed"},
                status_code=503,
            )
        if not bool(push_result.get("outbox")):
            return JSONResponse(
                {"success": False, "message": "management notification outbox unavailable"},
                status_code=503,
            )
        return {
            "success": True,
            "delivery_channel": "management_outbox",
            "mobile_push": push_result,
            "resolved_boss_user_id": int(boss_user_id),
            "tenant_id": management_tenant_id,
        }
    try:
        ensure_im_tables(get_host_engine())
        db = HostSessionLocal()
        try:
            result = ImApplicationService(db).post_employee_message(
                boss_user_id=boss_user_id,
                employee_id=employee_id,
                body=text,
                display_name=display_name,
            )
        finally:
            db.close()
        if not result:
            return JSONResponse({"success": False, "message": "post failed"}, status_code=400)
        # 实时推送（best-effort，不可用也不影响：消息已落库并经 sync 投递）。
        try:
            from app.infrastructure.im.ws_hub import im_ws_hub

            conversation_id = int(result["conversation_id"])
            payload = {
                "type": "im.message",
                "conversation_id": conversation_id,
                "message": result["message"],
                "updated_at_ms": result.get("updated_at_ms"),
            }
            await im_ws_hub.send_to_user(int(boss_user_id), payload)
            await im_ws_hub.send_to_user(
                int(boss_user_id),
                {
                    "type": "message",
                    "conversation_id": conversation_id,
                    "message": result["message"],
                },
            )
            if notification:
                await im_ws_hub.send_to_user(
                    int(boss_user_id),
                    {
                        "type": "management_work.notification",
                        **notification,
                    },
                )
        except RECOVERABLE_ERRORS:
            logger.debug("internal employee-message ws push skipped", exc_info=True)
        push_result: dict[str, bool] = {}
        if notification:
            try:
                push_result = notify_mobile_user(
                    int(boss_user_id),
                    title=str(notification.get("title") or display_name or employee_id),
                    body=text,
                    data={
                        **notification,
                        "route": str(
                            notification.get("route")
                            or f"management_work/{notification.get('task_id') or ''}"
                        ),
                        "channel": str(notification.get("channel") or "management_work"),
                    },
                    audience="management",
                )
            except Exception:  # noqa: BLE001 - IM is already durable; push is best-effort
                logger.debug("management work mobile push skipped", exc_info=True)
        return {
            "success": True,
            **result,
            "mobile_push": push_result,
            "resolved_boss_user_id": int(boss_user_id),
        }
    except RECOVERABLE_ERRORS:
        logger.exception("internal_employee_message")
        return JSONResponse({"success": False, "message": "服务器内部错误"}, status_code=500)


# ── 手机 IM 屏所需端点（精简 router 内置，绕开 im_routes 依赖链，保证陈旧部署可用）──


@router.get("/api/mobile/v1/im/conversations")
def im_list_conversations(user: Any = Depends(get_mobile_user)) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        return {"success": True, "conversations": ImApplicationService(db).list_conversations(uid)}
    except RECOVERABLE_ERRORS:
        logger.exception("im_list_conversations")
        return JSONResponse({"success": False, "message": "服务器内部错误"}, status_code=500)
    finally:
        db.close()


@router.post("/api/mobile/v1/im/conversations/direct")
def im_create_direct(
    body: dict = Body(default_factory=dict), user: Any = Depends(get_mobile_user)
) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    peer = int(body.get("peer_user_id") or 0)
    if peer <= 0:
        return JSONResponse({"success": False, "message": "peer_user_id 无效"}, status_code=400)
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        return {
            "success": True,
            "conversation": ImApplicationService(db).get_or_create_direct(uid, peer),
        }
    except ValueError:
        return JSONResponse({"success": False, "message": "请求参数无效"}, status_code=400)
    except RECOVERABLE_ERRORS:
        logger.exception("im_create_direct")
        return JSONResponse({"success": False, "message": "服务器内部错误"}, status_code=500)
    finally:
        db.close()


@router.get("/api/mobile/v1/im/conversations/{conversation_id}/messages")
def im_list_messages(
    conversation_id: int,
    user: Any = Depends(get_mobile_user),
    limit: int = Query(default=50, ge=1, le=100),
) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        return {
            "success": True,
            "messages": ImApplicationService(db).list_messages(conversation_id, uid, limit=limit),
        }
    except PermissionError:
        return JSONResponse({"success": False, "message": "无权访问该会话"}, status_code=403)
    except RECOVERABLE_ERRORS:
        logger.exception("im_list_messages")
        return JSONResponse({"success": False, "message": "服务器内部错误"}, status_code=500)
    finally:
        db.close()


@router.post("/api/mobile/v1/im/conversations/{conversation_id}/messages")
def im_post_message(
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: Any = Depends(get_mobile_user),
) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    text = str(body.get("body") or "")
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        svc = ImApplicationService(db)
        result = svc.send_message(conversation_id, uid, text)
        emp_id = svc.employee_id_for_conversation(conversation_id, uid)
    except PermissionError:
        return JSONResponse({"success": False, "message": "无权访问该会话"}, status_code=403)
    except ValueError:
        return JSONResponse({"success": False, "message": "请求参数无效"}, status_code=400)
    except RECOVERABLE_ERRORS:
        logger.exception("im_post_message")
        return JSONResponse({"success": False, "message": "服务器内部错误"}, status_code=500)
    finally:
        db.close()
    # 入站回流：老板在某员工聊天页回复 → 回流成该员工最新 pending 问题的答案，解阻塞员工。
    if emp_id:
        _relay_employee_answer(uid, emp_id, text)
    return {"success": True, **result}


@router.post("/api/mobile/v1/im/conversations/{conversation_id}/read")
def im_mark_read(
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: Any = Depends(get_mobile_user),
) -> Any:
    """标记会话已读（清未读角标）。不带 last_message_id 时标记到最新（全部已读）。"""
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    try:
        last_id = int(body.get("last_message_id") or 0)
    except (TypeError, ValueError):
        last_id = 0
    if last_id <= 0:
        last_id = 2_147_483_647  # 标记到最新，清空未读
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        return {
            "success": True,
            **ImApplicationService(db).mark_read(conversation_id, uid, last_id),
        }
    except PermissionError:
        return JSONResponse({"success": False, "message": "无权访问该会话"}, status_code=403)
    except RECOVERABLE_ERRORS:
        logger.exception("im_mark_read")
        return JSONResponse({"success": False, "message": "服务器内部错误"}, status_code=500)
    finally:
        db.close()
