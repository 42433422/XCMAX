"""
Flask → FastAPI 迁移缺口补齐 batch1 (原 ``archive_gap_batch1``)。

与 ``scripts/output/only_in_flask_native_batch1.json`` 对齐的原生 FastAPI 实现,
路径多为 ``/api/...``,覆盖 auth/users/conversations/inventory/purchase/report/
performance/products/skills/mp/traditional-mode/templates/system/database 等域。

**后续计划**: 按业务域继续拆分到 ``app/fastapi_routes/<domain>.py``
(Phase 2 遗留工作,见 ``docs/reports/LEGACY_CLEANUP_TRACKING.md``)。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Body, File, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse

from app.template_analysis_progress import get_template_analysis_progress
from app.traditional_mode_fs import list_files_response, read_file_response, sse_watch_events
from app.utils.json_safe import json_safe
from app.utils.path_utils import get_base_dir

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-gaps-batch1"])


def _emit_legacy_gaps_load_log() -> None:
    """启动阶段打一次日志,方便观测 legacy_gaps_batch1 当前承载的路由数。"""
    try:
        count = len([r for r in router.routes if hasattr(r, "path")])
    except Exception:
        count = -1
    logger.info(
        "[legacy-cleanup] legacy_gaps_batch1 loaded: routes=%s (further domain split pending; see LEGACY_CLEANUP_TRACKING.md)",
        count,
    )

def _secret_key() -> str:
    return os.environ.get("SECRET_KEY", "xcagi-dev-secret")


def _mp_jwt_user_id(authorization: str | None) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    try:
        secret_key = _secret_key()
        parts = token.split(".")
        if len(parts) != 3:
            return None

        def b64url_decode(data: str) -> bytes:
            padding = "=" * (4 - len(data) % 4)
            return base64.urlsafe_b64decode(data + padding)

        payload = json.loads(b64url_decode(parts[1]).decode("utf-8"))
        signature = b64url_decode(parts[2])
        message = f"{parts[0]}.{parts[1]}".encode("utf-8")
        expected = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        uid = payload.get("user_id")
        return int(uid) if uid is not None else None
    except Exception:
        return None


def _mp_json_response(code: int, message: str, data: Any = None, *, success: bool = True) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "success": success}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=code)


def _mp_paginate(items: list, total: int, page: int, page_size: int) -> JSONResponse:
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    payload = {
        "items": items,
        "pagination": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }
    return _mp_json_response(200, "success", payload)


def _session_id_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session_id")
    return (request.cookies.get(cookie_name) or "").strip()


def _require_login_user(request: Request):
    from app.services.session_service import get_session_service

    sid = _session_id_from_request(request)
    if not sid:
        return None, JSONResponse(
            {"success": False, "message": {"code": "UNAUTHORIZED", "message": "请先登录"}},
            status_code=401,
        )
    user = get_session_service().validate_session(sid)
    if not user:
        return None, JSONResponse(
            {"success": False, "message": {"code": "SESSION_EXPIRED", "message": "会话已过期，请重新登录"}},
            status_code=401,
        )
    if not user.is_active:
        return None, JSONResponse(
            {"success": False, "message": {"code": "ACCOUNT_DISABLED", "message": "账户已被禁用"}},
            status_code=403,
        )
    return user, None


def _require_permission(request: Request, permission_code: str):
    user, err = _require_login_user(request)
    if err:
        return None, err
    from app.services import get_auth_service

    auth_service = get_auth_service()
    if not auth_service.has_permission(user, permission_code):
        return None, JSONResponse(
            {"success": False, "message": {"code": "FORBIDDEN", "message": "权限不足"}},
            status_code=403,
        )
    return user, None


def _session_to_dict(session: object) -> dict:
    if isinstance(session, dict):
        return {
            "session_id": session.get("session_id"),
            "user_id": session.get("user_id"),
            "title": session.get("title") or "新会话",
            "summary": session.get("summary") or "",
            "message_count": session.get("message_count", 0),
            "last_message_at": session.get("last_message_at"),
            "created_at": session.get("created_at"),
        }
    if isinstance(session, tuple):
        return {
            "session_id": session[1] if len(session) > 1 else None,
            "user_id": session[2] if len(session) > 2 else None,
            "title": (session[3] if len(session) > 3 else None) or "新会话",
            "summary": (session[4] if len(session) > 4 else None) or "",
            "message_count": session[5] if len(session) > 5 else 0,
            "last_message_at": session[6] if len(session) > 6 else None,
            "created_at": session[7] if len(session) > 7 else None,
        }
    return {
        "session_id": getattr(session, "session_id", None),
        "user_id": getattr(session, "user_id", None),
        "title": getattr(session, "title", None) or "新会话",
        "summary": getattr(session, "summary", "") or "",
        "message_count": getattr(session, "message_count", 0),
        "last_message_at": getattr(session, "last_message_at", None),
        "created_at": getattr(session, "created_at", None),
    }


def _message_to_dict(message: object) -> dict:
    if isinstance(message, dict):
        return {
            "id": message.get("id"),
            "session_id": message.get("session_id"),
            "user_id": message.get("user_id"),
            "role": message.get("role"),
            "content": message.get("content"),
            "intent": message.get("intent") or "",
            "metadata": message.get("metadata") or message.get("conversation_metadata") or "",
            "created_at": message.get("created_at"),
        }
    if isinstance(message, tuple):
        return {
            "id": message[0] if len(message) > 0 else None,
            "session_id": message[1] if len(message) > 1 else None,
            "user_id": message[2] if len(message) > 2 else None,
            "role": message[3] if len(message) > 3 else None,
            "content": message[4] if len(message) > 4 else None,
            "intent": (message[5] if len(message) > 5 else "") or "",
            "metadata": (message[6] if len(message) > 6 else "") or "",
            "created_at": message[7] if len(message) > 7 else None,
        }
    return {
        "id": getattr(message, "id", None),
        "session_id": getattr(message, "session_id", None),
        "user_id": getattr(message, "user_id", None),
        "role": getattr(message, "role", None),
        "content": getattr(message, "content", None),
        "intent": getattr(message, "intent", "") or "",
        "metadata": getattr(message, "conversation_metadata", "") or "",
        "created_at": getattr(message, "created_at", None),
    }


# --- 根路径与静态首页 ---
@router.get("/")
def gap_batch1_index():
    base_dir = get_base_dir()
    vue_index = os.path.join(base_dir, "templates", "vue-dist", "index.html")
    if os.path.exists(vue_index):
        return FileResponse(vue_index, media_type="text/html")
    legacy = os.path.join(base_dir, "templates", "ai_assistant_console.html")
    if os.path.exists(legacy):
        return FileResponse(legacy, media_type="text/html")
    return JSONResponse({"success": False, "message": "前端模板未找到"}, status_code=404)


# --- AI（approval / test / export；kitten 与 qclaw 已拆出到独立模块）---
@router.get("/api/ai/approval/pending")
def ai_approval_pending():
    from app.application.workflow import get_approval_service

    approval_service = get_approval_service()
    all_pending = []
    for req in approval_service._pending_requests.values():
        all_pending.append(
            {
                "request_id": req.request_id,
                "plan_id": req.plan_id,
                "node_id": req.node_id,
                "tool_id": req.tool_id,
                "action": req.action,
                "status": req.status.value,
                "created_at": req.created_at.isoformat() if req.created_at else None,
            }
        )
    return {"success": True, "data": {"pending_approvals": all_pending}}


@router.get("/api/ai/config/approval")
def ai_config_approval_get():
    from resources.config.approval_config import get_approval_config

    c = get_approval_config()
    return {
        "success": True,
        "enabled": c.enabled,
        "rules": c.rules,
        "attendance_policy": getattr(c, "attendance_policy", None) or {},
    }


@router.get("/api/ai/analyze/export/{export_id}")
def ai_analyze_export(export_id: str):
    try:
        import os as _os

        from app.services.data_analysis_service import get_data_analysis_service
        from app.utils.path_utils import get_upload_dir

        service = get_data_analysis_service()
        output_path = _os.path.join(get_upload_dir(), f"report_{export_id}.xlsx")
        success = service.export_to_excel({}, output_path)
        if success and _os.path.exists(output_path):
            return FileResponse(
                output_path,
                filename=f"分析报告_{export_id[:8]}.xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        return JSONResponse({"success": False, "message": "导出失败"}, status_code=500)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# --- Auth / Users ---
@router.get("/api/auth/me")
def auth_me(request: Request):
    user, err = _require_login_user(request)
    if err:
        return err
    from app.application import get_auth_app_service

    auth_app_service = get_auth_app_service()
    permissions = auth_app_service.get_user_permissions(user)
    return {
        "success": True,
        "data": {
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active,
            },
            "permissions": permissions,
        },
    }


@router.get("/api/auth/session/validate")
def auth_session_validate(request: Request):
    from app.application import get_auth_app_service

    session_id = _session_id_from_request(request)
    if not session_id:
        return JSONResponse(
            {
                "success": False,
                "valid": False,
                "error": {"code": "NO_SESSION", "message": "无会话信息"},
            },
            status_code=401,
        )
    auth_app_service = get_auth_app_service()
    session_info = auth_app_service.session_manager.get_session_info(session_id)
    if not session_info:
        return JSONResponse(
            {
                "success": False,
                "valid": False,
                "error": {"code": "INVALID_SESSION", "message": "会话无效或已过期"},
            },
            status_code=401,
        )
    return {"success": True, "valid": True, "data": session_info}


@router.get("/api/users")
def users_list(request: Request, include_inactive: str = Query(default="false")):
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.application import get_user_app_service

    user_service = get_user_app_service()
    users = user_service.list_users(skip=0, limit=100)
    if include_inactive.lower() != "true":
        users = [u for u in users if u.get("is_active", True)]
    return {"success": True, "data": {"users": users, "count": len(users)}}


@router.get("/api/users/{user_id}")
def users_get(request: Request, user_id: int):
    _, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    from app.application import get_user_app_service

    user_service = get_user_app_service()
    user = user_service.get_user(user_id)
    if not user:
        return JSONResponse(
            {"success": False, "error": {"code": "NOT_FOUND", "message": "用户不存在"}},
            status_code=404,
        )
    return {"success": True, "data": {"user": user}}


@router.delete("/api/users/{user_id}")
def users_delete(request: Request, user_id: int):
    user, err = _require_permission(request, "admin.manage_users")
    if err:
        return err
    if user.id == user_id:
        return JSONResponse(
            {"success": False, "error": {"code": "SELF_DELETE", "message": "不能删除自己"}},
            status_code=400,
        )
    from app.application import get_user_app_service

    user_service = get_user_app_service()
    result = user_service.delete_user(user_id)
    if not result.get("success"):
        return JSONResponse(result, status_code=400)
    return result


# --- Conversations ---
@router.get("/api/conversations/{session_id}")
def conversations_get(session_id: str, limit: int = Query(default=50)):
    try:
        from app.services.conversation_service import get_conversation_service

        service = get_conversation_service()
        messages = service.get_session_messages(session_id, limit)
        sessions = service.get_sessions(user_id=None, limit=1000)
        session_info = None
        for s in sessions:
            current = _session_to_dict(s)
            if current.get("session_id") == session_id:
                session_info = current
                break
        result = [_message_to_dict(m) for m in messages]
        return json_safe({"success": True, "session": session_info, "messages": result})
    except Exception as e:
        logger.error("conversations get: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.delete("/api/conversations/{session_id}")
def conversations_delete(session_id: str):
    try:
        from app.services.conversation_service import get_conversation_service

        service = get_conversation_service()
        success = service.delete_session(session_id)
        return {"success": success}
    except Exception as e:
        logger.error("conversations delete: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# --- Customers ---
@router.get("/api/customers/import")
def customers_import_stub():
    return {"success": True, "message": "购买单位导入接口，请使用 POST 上传 .xlsx 文件"}


@router.delete("/api/customers/batch-delete")
def customers_batch_delete_delete(
    ids: str | None = Query(default=None),
    force: str = Query(default="false"),
    body: dict | None = Body(default=None),
):
    """与归档一致：DELETE 可用 query ``ids=1,2,3``；亦兼容 JSON body。"""
    from app.application import get_customer_app_service

    try:
        if isinstance(body, dict) and body.get("ids"):
            id_list = body.get("ids") or []
            force_b = bool(body.get("force", False))
        elif ids:
            id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
            force_b = force.lower() in ("true", "1", "yes")
        else:
            return JSONResponse({"success": False, "message": "ID 列表不能为空"}, status_code=400)
        if not id_list:
            return JSONResponse({"success": False, "message": "ID 列表不能为空"}, status_code=400)
        result = get_customer_app_service().batch_delete(id_list, force=force_b)
        code = 200 if result["success"] else (409 if result.get("has_associations") else 400)
        return JSONResponse(result, status_code=code)
    except ValueError as e:
        return JSONResponse({"success": False, "message": f"ID 格式错误：{str(e)}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"删除失败：{str(e)}"}, status_code=500)


# --- Preferences ---
@router.delete("/api/preferences/{key}")
def preferences_delete_key(key: str, user_id: str = Query(default="default")):
    try:
        from app.services.user_preference_service import get_user_preference_service

        success = get_user_preference_service().delete_preference(user_id, key)
        return {"success": success, "message": "偏好已删除" if success else "删除失败"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# --- Database / System / Templates ---
@router.get("/api/database/backups")
def database_backups_list():
    try:
        from app.services import get_database_service

        return get_database_service().list_backups()
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.delete("/api/database/backup/{backup_file:path}")
def database_backup_delete(backup_file: str):
    try:
        from app.services import get_database_service

        result = get_database_service().delete_backup(backup_file)
        return JSONResponse(result, status_code=200 if result.get("success") else 500)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/system/config")
def system_config_get():
    try:
        from resources.config import industry_config as ic

        return {
            "success": True,
            "data": {
                "current_industry": ic.get_current_industry(),
                "available_industries": ic.get_available_industries(),
            },
        }
    except Exception as e:
        logger.exception("system config: %s", e)
        return {
            "success": True,
            "data": {
                "current_industry": "涂料",
                "available_industries": [{"id": "涂料", "name": "涂料/油漆行业"}],
                "degraded": True,
                "hint": (str(e) or "error")[:300],
            },
        }


@router.get("/api/system/info")
def system_info_get():
    try:
        from app.services import get_system_service

        return {"success": True, "data": get_system_service().get_system_info()}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/system/printer")
def system_printer_get():
    try:
        from app.services import get_system_service

        return {"success": True, "data": get_system_service().get_printer_config()}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/system/startup")
def system_startup_get():
    try:
        from app.services import get_system_service

        return {"success": True, "data": get_system_service().get_startup_config()}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.delete("/api/system/startup")
def system_startup_delete():
    try:
        from app.services import get_system_service

        result = get_system_service().disable_startup()
        return JSONResponse(result, status_code=200 if result.get("success") else 500)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/templates/progress/{task_id}")
def templates_progress(task_id: str):
    return get_template_analysis_progress(task_id)


@router.delete("/api/templates/delete")
def templates_delete(request: Request, body: dict = Body(default_factory=dict)):
    try:
        import os as _os
        from datetime import datetime

        from sqlalchemy import text

        from app.db.session import get_db
        from app.db.init_db import init_template_tables

        template_id = str(body.get("id") or request.query_params.get("id") or "").strip()
        if not template_id:
            return JSONResponse({"success": False, "message": "缺少模板 id"}, status_code=400)
        if template_id.startswith("fs:"):
            filename = template_id.split(":", 1)[1].strip()
            if not filename:
                return JSONResponse({"success": False, "message": "模板文件名无效"}, status_code=400)
            base_dir = get_base_dir()
            candidates = [
                _os.path.join(base_dir, filename),
                _os.path.join(base_dir, "templates", filename),
                _os.path.join(base_dir, "resources", "templates", filename),
            ]
            target_path = None
            for p in candidates:
                if _os.path.isfile(p):
                    target_path = p
                    break
            if not target_path:
                return JSONResponse({"success": False, "message": f"模板文件不存在: {filename}"}, status_code=404)
            _os.remove(target_path)
            return {"success": True, "message": "模板删除成功", "deleted": {"id": template_id, "path": target_path}}
        db_id = None
        if template_id.startswith("db:"):
            raw_db_id = template_id.split(":", 1)[1].strip()
            if raw_db_id.isdigit():
                db_id = int(raw_db_id)
        elif template_id.isdigit():
            db_id = int(template_id)
        if db_id is not None:
            try:
                init_template_tables()
            except Exception:
                pass
            with get_db() as db:
                row = db.execute(text("SELECT id FROM templates WHERE id = :id"), {"id": db_id}).fetchone()
                if not row:
                    return JSONResponse({"success": False, "message": "模板不存在"}, status_code=404)
                db.execute(
                    text("UPDATE templates SET is_active = 0, updated_at = :updated_at WHERE id = :id"),
                    {"id": db_id, "updated_at": datetime.now()},
                )
                db.commit()
            return {"success": True, "message": "模板删除成功", "deleted": {"id": template_id, "db_id": db_id}}
        return JSONResponse({"success": False, "message": f"暂不支持删除该模板类型: {template_id}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"删除失败：{str(e)}"}, status_code=500)


# --- Skills / Intent ---
@router.get("/api/skills/list")
def skills_list():
    try:
        from app.infrastructure.skills import get_skill_registry

        registry = get_skill_registry()
        return {"success": True, "skills": registry.list_all()}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/api/skills/info/{skill_id}")
def skills_info(skill_id: str):
    try:
        from app.infrastructure.skills import get_skill_registry

        registry = get_skill_registry()
        skill_info = registry.get(skill_id)
        if skill_info:
            return {
                "success": True,
                "skill": {
                    "id": skill_id,
                    "name": skill_info.get("name", ""),
                    "description": skill_info.get("description", ""),
                    "keywords": skill_info.get("keywords", []),
                    "category": skill_info.get("category", "general"),
                },
            }
        return JSONResponse({"success": False, "message": "技能不存在"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# --- Inventory / Purchase / Report ---
@router.get("/api/inventory")
def inventory_list(
    warehouse_id: int | None = Query(default=None),
    product_id: int | None = Query(default=None),
    batch_no: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=50),
):
    from app.services.inventory_service import InventoryService

    return InventoryService().get_inventory(
        warehouse_id=warehouse_id,
        product_id=product_id,
        batch_no=batch_no,
        page=page,
        per_page=per_page,
    )


@router.get("/api/inventory/summary")
def inventory_summary(warehouse_id: int | None = Query(default=None)):
    from app.services.inventory_service import InventoryService

    return InventoryService().get_inventory_summary(warehouse_id=warehouse_id)


@router.get("/api/inventory/transactions")
def inventory_transactions(
    product_id: int | None = Query(default=None),
    warehouse_id: int | None = Query(default=None),
    transaction_type: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=50),
):
    from datetime import datetime

    from app.services.inventory_service import InventoryService

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return InventoryService().get_inventory_transactions(
        product_id=product_id,
        warehouse_id=warehouse_id,
        transaction_type=transaction_type,
        start_date=start_dt,
        end_date=end_dt,
        page=page,
        per_page=per_page,
    )


@router.get("/api/inventory/locations")
def inventory_locations(warehouse_id: int | None = Query(default=None), status: str | None = Query(default=None)):
    from app.services.inventory_service import InventoryService

    if not warehouse_id:
        return {"success": False, "message": "仓库ID不能为空"}
    return InventoryService().get_storage_locations(warehouse_id=warehouse_id, status=status)


@router.get("/api/inventory/warehouses")
def inventory_warehouses_list(status: str | None = Query(default=None)):
    from app.services.inventory_service import InventoryService

    return InventoryService().get_warehouses(status=status)


@router.get("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_get(warehouse_id: int):
    from app.services.inventory_service import InventoryService

    return InventoryService().get_warehouse(warehouse_id)


@router.delete("/api/inventory/warehouses/{warehouse_id}")
def inventory_warehouses_delete(warehouse_id: int):
    from app.services.inventory_service import InventoryService

    return InventoryService().delete_warehouse(warehouse_id)


@router.get("/api/inventory/inventory/alert")
def inventory_alert():
    from app.services.inventory_service import InventoryService

    return InventoryService().get_inventory_alert()


@router.get("/api/purchase/suppliers")
def purchase_suppliers(status: str | None = Query(default=None), keyword: str | None = Query(default=None)):
    from app.services.purchase_service import PurchaseService

    return PurchaseService().get_suppliers(status=status, keyword=keyword)


@router.get("/api/purchase/suppliers/summary")
def purchase_suppliers_summary():
    from app.services.purchase_service import PurchaseService

    return PurchaseService().get_supplier_summary()


@router.get("/api/purchase/suppliers/{supplier_id}")
def purchase_supplier_get(supplier_id: int):
    from app.services.purchase_service import PurchaseService

    return PurchaseService().get_supplier(supplier_id)


@router.delete("/api/purchase/suppliers/{supplier_id}")
def purchase_supplier_delete(supplier_id: int):
    from app.services.purchase_service import PurchaseService

    return PurchaseService().delete_supplier(supplier_id)


@router.get("/api/purchase/orders")
def purchase_orders(
    supplier_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=20),
):
    from datetime import datetime

    from app.services.purchase_service import PurchaseService

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return PurchaseService().get_purchase_orders(
        supplier_id=supplier_id,
        status=status,
        start_date=start_dt,
        end_date=end_dt,
        page=page,
        per_page=per_page,
    )


@router.get("/api/purchase/orders/{order_id}")
def purchase_order_get(order_id: int):
    from app.services.purchase_service import PurchaseService

    return PurchaseService().get_purchase_order(order_id)


@router.get("/api/purchase/inbounds")
def purchase_inbounds(
    supplier_id: int | None = Query(default=None),
    order_id: int | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    page: int = Query(default=1),
    per_page: int = Query(default=20),
):
    from datetime import datetime

    from app.services.purchase_service import PurchaseService

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return PurchaseService().get_purchase_inbounds(
        supplier_id=supplier_id,
        order_id=order_id,
        start_date=start_dt,
        end_date=end_dt,
        page=page,
        per_page=per_page,
    )


@router.get("/api/purchase/summary")
def purchase_summary():
    from app.services.purchase_service import PurchaseService

    return PurchaseService().get_purchase_summary()


@router.get("/api/report/sales")
def report_sales(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    group_by: str = Query(default="product"),
    customer_id: int | None = Query(default=None),
):
    from datetime import datetime

    from app.services.report_service import ReportService

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return ReportService().get_sales_report(
        start_date=start_dt, end_date=end_dt, group_by=group_by, customer_id=customer_id
    )


@router.get("/api/report/inventory")
def report_inventory(warehouse_id: int | None = Query(default=None), category: str | None = Query(default=None)):
    from app.services.report_service import ReportService

    return ReportService().get_inventory_report(warehouse_id=warehouse_id, category=category)


@router.get("/api/report/inventory/transactions")
def report_inventory_transactions(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    transaction_type: str | None = Query(default=None),
    product_id: int | None = Query(default=None),
):
    from datetime import datetime

    from app.services.report_service import ReportService

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return ReportService().get_inventory_transaction_report(
        start_date=start_dt,
        end_date=end_dt,
        transaction_type=transaction_type,
        product_id=product_id,
    )


@router.get("/api/report/purchase")
def report_purchase(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    group_by: str = Query(default="supplier"),
):
    from datetime import datetime

    from app.services.report_service import ReportService

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return ReportService().get_purchase_report(start_date=start_dt, end_date=end_dt, group_by=group_by)


@router.get("/api/report/dashboard")
def report_dashboard():
    from app.services.report_service import ReportService

    return ReportService().get_dashboard_summary()


# --- Performance ---
@router.get("/api/performance/status")
def performance_status():
    import time as _time

    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer._initialized:
            return JSONResponse(
                {"success": False, "message": "性能优化系统未初始化", "data": None},
                status_code=503,
            )
        return {"success": True, "data": optimizer.get_status(), "timestamp": _time.time()}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.get("/api/performance/health")
def performance_health():
    import time as _time

    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        health = optimizer.get_health_check()
        code = 200 if health["status"] == "healthy" else (503 if health["status"] == "degraded" else 500)
        resp = {
            "status": health["status"],
            "timestamp": health["timestamp"],
            "checks": health.get("checks", {}),
        }
        if "issues" in health:
            resp["issues"] = health["issues"]
        return JSONResponse(resp, status_code=code)
    except Exception as e:
        return JSONResponse(
            {"status": "unhealthy", "error": str(e), "timestamp": _time.time()},
            status_code=500,
        )


@router.get("/api/performance/metrics/summary")
def performance_metrics_summary(minutes: int = Query(default=5)):
    try:
        minutes = max(1, min(minutes, 60))
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.performance_monitor:
            return JSONResponse(
                {"success": False, "message": "性能监控未启用", "data": None},
                status_code=503,
            )
        summary = optimizer.performance_monitor.get_metrics_summary(minutes=minutes)
        return {"success": True, "data": summary}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.get("/api/performance/metrics/prometheus")
def performance_metrics_prometheus():
    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.performance_monitor:
            return PlainTextResponse("# XCAGI metrics unavailable\n", status_code=503)
        return PlainTextResponse(
            optimizer.performance_monitor.get_prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    except Exception as e:
        return PlainTextResponse(f"# Error: {str(e)}\n", status_code=500)


@router.get("/api/performance/cache/stats")
def performance_cache_stats():
    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return JSONResponse(
                {"success": False, "message": "Redis 缓存未初始化", "data": None},
                status_code=503,
            )
        return {"success": True, "data": optimizer.redis_cache.stats}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.get("/api/performance/tasks/status")
def performance_tasks_status(task_id: str | None = Query(default=None)):
    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.async_task_manager:
            return JSONResponse(
                {"success": False, "message": "异步任务管理未启用", "data": None},
                status_code=503,
            )
        if task_id:
            result = optimizer.async_task_manager.get_status(task_id)
            if result is None:
                return JSONResponse(
                    {"success": False, "message": "任务不存在", "data": None},
                    status_code=404,
                )
            return {
                "success": True,
                "data": {
                    "task_id": result.task_id,
                    "status": result.status.value,
                    "progress": result.progress,
                    "duration_ms": round(result.duration_ms, 2) if result.duration_ms else None,
                    "error": result.error,
                    "metadata": result.metadata,
                },
            }
        active_tasks = optimizer.async_task_manager.active_tasks
        stats = optimizer.async_task_manager.stats
        return {
            "success": True,
            "data": {
                "active_tasks": {
                    tid: {
                        "task_id": t.task_id,
                        "status": t.status.value,
                        "progress": t.progress,
                        "name": t.metadata.get("task_name", ""),
                    }
                    for tid, t in (active_tasks or {}).items()
                }
                if active_tasks
                else {},
                "stats": stats,
            },
        }
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e), "data": None}, status_code=500)


@router.get("/api/performance/alerts")
def performance_alerts(level: str | None = Query(default=None), limit: int = Query(default=20)):
    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.performance_monitor:
            return JSONResponse(
                {"success": False, "message": "性能监控未启用", "data": []},
                status_code=503,
            )
        alerts = optimizer.performance_monitor.get_alerts(level=level, limit=limit)
        return {"success": True, "data": alerts, "count": len(alerts)}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e), "data": []}, status_code=500)


@router.get("/api/performance/slow-queries")
def performance_slow_queries(limit: int = Query(default=20)):
    try:
        from app.utils.performance_initializer import get_performance_optimizer

        optimizer = get_performance_optimizer()
        if not optimizer.query_optimizer:
            return JSONResponse(
                {"success": False, "message": "查询优化器未启用", "data": []},
                status_code=503,
            )
        slow = optimizer.query_optimizer.get_slow_queries(limit=limit)
        return {"success": True, "data": slow, "count": len(slow)}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e), "data": []}, status_code=500)


# --- Products ---
@router.delete("/api/products/{product_id}")
def products_delete(product_id: int):
    from app.bootstrap import get_products_service

    return get_products_service().delete_product(product_id)


@router.post("/api/products/import/price-list-template")
async def products_import_price_list_template(
    template_file: UploadFile | None = File(default=None),
):
    """将上传的 .docx 写入仓库默认价目表模板路径，供 ``/api/products/export.docx`` 等使用。"""
    try:
        from app.infrastructure.documents.template_registry import fhd_repo_root
    except Exception as e:  # pragma: no cover
        logger.exception("template_registry import failed")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

    if template_file is None or not template_file.filename:
        return JSONResponse({"success": False, "message": "请上传 .docx 模板文件"}, status_code=400)
    if not str(template_file.filename).lower().endswith(".docx"):
        return JSONResponse({"success": False, "message": "只支持 .docx 格式"}, status_code=400)
    try:
        body = await template_file.read()
    except Exception as e:
        logger.exception("price list template read failed")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)
    if len(body) < 64:
        return JSONResponse({"success": False, "message": "文件过小或已损坏"}, status_code=400)
    if not body.startswith(b"PK"):
        return JSONResponse(
            {"success": False, "message": "不是有效的 Office Open XML（.docx）文件"},
            status_code=400,
        )
    try:
        dest_dir = fhd_repo_root() / "424" / "document_templates"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "price_list_default.docx"
        dest.write_bytes(body)
        rel = dest.relative_to(fhd_repo_root())
    except Exception as e:
        logger.exception("price list template write failed")
        return JSONResponse({"success": False, "message": f"保存失败：{e}"}, status_code=500)
    return {
        "success": True,
        "message": f"已保存价目表 Word 模板（{rel.as_posix()}），导出 Word 价目表时将使用该文件。",
    }


@router.get("/api/products/export.xlsx")
def products_export_xlsx(
    unit: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
):
    import os as _os

    from app.bootstrap import get_products_service

    service = get_products_service()
    result = service.export_to_excel(unit_name=unit, keyword=keyword, template_id=template_id)
    if not result.get("success"):
        return JSONResponse(result, status_code=400)
    file_path = result.get("file_path")
    filename = result.get("filename")
    if file_path and _os.path.exists(file_path):
        return FileResponse(
            file_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return JSONResponse({"success": False, "message": "导出文件不存在"}, status_code=500)


@router.get("/api/products/product_names")
def products_product_names():
    from app.bootstrap import get_products_service

    return get_products_service().get_product_names()


@router.get("/api/products/product_names/search")
def products_product_names_search(keyword: str = Query(default="")):
    from app.bootstrap import get_products_service

    return get_products_service().get_product_names(keyword=keyword)


@router.get("/api/products/search")
def products_search(keyword: str = Query(default="")):
    from app.bootstrap import get_products_service

    return get_products_service().get_products(keyword=keyword)


# --- Traditional mode ---
@router.get("/api/traditional-mode/list")
def traditional_list(path: str = Query(default="")):
    payload, code = list_files_response(path)
    return JSONResponse(payload, status_code=code)


@router.get("/api/traditional-mode/read")
def traditional_read(file: str = Query(default="")):
    payload, code = read_file_response(file)
    return JSONResponse(payload, status_code=code)


@router.get("/api/traditional-mode/watch")
def traditional_watch(path: str = Query(default="")):
    return StreamingResponse(sse_watch_events(path), media_type="text/event-stream")


# --- WeChat（桌面 + 小程序 JWT 子集）---
@router.get("/api/wechat/tasks")
def wechat_tasks(
    status: str = Query(default="pending"),
    contact_id: int | None = Query(default=None),
    limit: int = Query(default=20),
):
    try:
        from app.application import get_wechat_task_app_service

        service = get_wechat_task_app_service()
        tasks = service.get_tasks(contact_id=contact_id, status=status, limit=limit)
        return {"success": True, "data": tasks, "total": len(tasks)}
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat/contacts")
def wechat_contacts_list_api(
    keyword: str | None = Query(default=None),
    type: str = Query(default="all"),
    starred: str = Query(default="false"),
    limit: int = Query(default=100),
):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        contacts = service.get_contacts(
            keyword=keyword,
            contact_type=type if type != "all" else None,
            starred_only=starred.lower() == "true",
            limit=limit,
        )
        return {"success": True, "data": contacts, "total": len(contacts)}
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat/contacts/{contact_id}")
def wechat_contact_get_api(contact_id: int):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        contact = service.get_contact_by_id(contact_id)
        if contact:
            return {"success": True, "data": contact}
        return JSONResponse({"success": False, "message": "联系人不存在"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.delete("/api/wechat/contacts/{contact_id}")
def wechat_contact_delete_api(contact_id: int):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        result = service.delete_contact(contact_id)
        return JSONResponse(result, status_code=200 if result.get("success") else 400)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"删除失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat/contacts/{contact_id}/context")
def wechat_contact_context_api(contact_id: int):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        messages = service.get_contact_context(contact_id)
        return {"success": True, "messages": messages, "count": len(messages)}
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat/status")
def wechat_status():
    try:
        import sys

        from app.utils.path_utils import get_resource_path

        wechat_cv_path = get_resource_path("wechat_cv")
        if os.path.isdir(wechat_cv_path) and wechat_cv_path not in sys.path:
            sys.path.insert(0, wechat_cv_path)
        from wechat_cv_send import _find_wechat_handle

        hwnd = _find_wechat_handle()
        is_logined = hwnd is not None
        return {
            "success": True,
            "logined": is_logined,
            "message": "微信已登录" if is_logined else "微信未登录",
        }
    except Exception as e:
        return {"success": False, "logined": False, "message": f"检测失败：{str(e)}"}


@router.get("/api/wechat/test")
def wechat_test():
    return {"success": True, "message": "微信服务运行正常"}


@router.get("/api/wechat/session/check")
def wechat_session_check(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        return _mp_json_response(401, "未授权", {"error": "缺少 token"}, success=False)
    token = authorization[7:].strip()
    try:
        secret_key = _secret_key()
        parts = token.split(".")
        if len(parts) != 3:
            return _mp_json_response(401, "token 无效或已过期", {"error": "invalid_token"}, success=False)

        def b64url_decode(data: str) -> bytes:
            padding = "=" * (4 - len(data) % 4)
            return base64.urlsafe_b64decode(data + padding)

        payload = json.loads(b64url_decode(parts[1]).decode("utf-8"))
        signature = b64url_decode(parts[2])
        message = f"{parts[0]}.{parts[1]}".encode("utf-8")
        expected = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return _mp_json_response(401, "token 无效或已过期", {"error": "invalid_token"}, success=False)
        if int(payload.get("exp", 0)) < int(time.time()):
            return _mp_json_response(401, "会话已过期", {"error": "session_expired"}, success=False)
        return _mp_json_response(
            200,
            "会话有效",
            {"user_id": payload.get("user_id"), "openid": payload.get("openid"), "expires_at": payload.get("exp")},
        )
    except Exception as e:
        logger.error("wechat session check: %s", e)
        return _mp_json_response(500, f"检查失败：{str(e)}", {"error": "internal_error"}, success=False)


@router.get("/api/wechat/user/info")
def wechat_user_info_miniprogram(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"error": "缺少 token"}, success=False)
    try:
        from app.db.models import User
        from app.db.session import get_db

        with get_db() as db:
            user = db.query(User).filter(User.id == uid).first()
            if not user:
                return _mp_json_response(404, "用户不存在", {"error": "user_not_found"}, success=False)
            return _mp_json_response(
                200,
                "获取成功",
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "email": user.email,
                    "role": user.role,
                    "avatar": "",
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                },
            )
    except Exception as e:
        logger.error("wechat user info: %s", e)
        return _mp_json_response(500, f"获取失败：{str(e)}", {"error": "internal_error"}, success=False)


# --- wechat_contacts 兼容路径 ---
@router.get("/api/wechat_contacts/ensure_contact_cache")
def wechat_contacts_ensure_cache():
    from app.services.wechat_contact_cache_import import refresh_wechat_contacts_from_decrypt

    payload, code = refresh_wechat_contacts_from_decrypt()
    return JSONResponse(payload, status_code=code)


@router.get("/api/wechat_contacts/message_source_size")
def wechat_contacts_message_source_size():
    from app.services.wechat_contact_cache_import import wechat_message_source_size_payload

    payload, code = wechat_message_source_size_payload()
    return JSONResponse(payload, status_code=code)


# --- 小程序 /api/mp/v1/* ---
@router.get("/api/mp/v1/address/list")
def mp_address_list(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpAddress
    from app.db.session import get_db

    with get_db() as db:
        addresses = (
            db.query(MpAddress)
            .filter(MpAddress.user_id == uid)
            .order_by(MpAddress.is_default.desc(), MpAddress.created_at.desc())
            .all()
        )
        result = []
        for addr in addresses:
            result.append(
                {
                    "id": addr.id,
                    "contact_name": addr.contact_name,
                    "contact_phone": addr.contact_phone,
                    "province": addr.province,
                    "city": addr.city,
                    "district": addr.district,
                    "detail_address": addr.detail_address,
                    "full_address": f"{addr.province}{addr.city}{addr.district}{addr.detail_address}",
                    "is_default": addr.is_default,
                }
            )
        return _mp_json_response(200, "success", result)


@router.delete("/api/mp/v1/address/delete/{address_id}")
def mp_address_delete(address_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpAddress
    from app.db.session import get_db

    with get_db() as db:
        address = db.query(MpAddress).filter(MpAddress.id == address_id, MpAddress.user_id == uid).first()
        if not address:
            return _mp_json_response(404, "地址不存在", success=False)
        db.delete(address)
        db.commit()
        return _mp_json_response(200, "地址删除成功")


@router.get("/api/mp/v1/cart/list")
def mp_cart_list(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpCart, Product
    from app.db.session import get_db

    with get_db() as db:
        carts = db.query(MpCart).filter(MpCart.user_id == uid).order_by(MpCart.created_at.desc()).all()
        items = []
        total_amount = 0.0
        selected_count = 0
        for cart in carts:
            product = db.query(Product).filter(Product.id == cart.product_id).first()
            if not product or product.is_active != 1:
                continue
            unit_price = float(product.price) if product.price else 0
            subtotal = round(unit_price * cart.quantity, 2)
            items.append(
                {
                    "cart_id": cart.id,
                    "product_id": product.id,
                    "product_name": product.name,
                    "model_number": product.model_number or "",
                    "specification": product.specification or "",
                    "unit_price": unit_price,
                    "quantity": cart.quantity,
                    "selected": cart.selected,
                    "subtotal": subtotal,
                    "unit": product.unit or "个",
                }
            )
            if cart.selected:
                total_amount += subtotal
                selected_count += cart.quantity
        return _mp_json_response(
            200,
            "success",
            {
                "items": items,
                "summary": {
                    "total_amount": round(total_amount, 2),
                    "selected_count": selected_count,
                    "total_types": len(items),
                },
            },
        )


@router.delete("/api/mp/v1/cart/clear")
def mp_cart_clear(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpCart
    from app.db.session import get_db

    with get_db() as db:
        db.query(MpCart).filter(MpCart.user_id == uid).delete()
        db.commit()
        return _mp_json_response(200, "购物车已清空")


@router.delete("/api/mp/v1/cart/remove")
def mp_cart_remove(authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    product_id = body.get("product_id")
    if not product_id:
        return _mp_json_response(400, "商品ID不能为空", success=False)
    from app.db.models import MpCart
    from app.db.session import get_db

    with get_db() as db:
        deleted = db.query(MpCart).filter(MpCart.user_id == uid, MpCart.product_id == product_id).delete()
        if deleted == 0:
            return _mp_json_response(404, "购物车中不存在该商品", success=False)
        db.commit()
        return _mp_json_response(200, "删除成功")


@router.get("/api/mp/v1/favorite/list")
def mp_favorite_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    from app.db.models import MpFavorite, Product
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(MpFavorite).filter(MpFavorite.user_id == uid).order_by(MpFavorite.created_at.desc())
        total = query.count()
        favorites = query.offset((page - 1) * page_size).limit(page_size).all()
        items = []
        for fav in favorites:
            product = db.query(Product).filter(Product.id == fav.product_id).first()
            if product and product.is_active == 1:
                items.append(
                    {
                        "fav_id": fav.id,
                        "product_id": product.id,
                        "product_name": product.name,
                        "price": float(product.price) if product.price else 0,
                        "unit": product.unit or "个",
                        "created_at": fav.created_at.isoformat() if fav.created_at else None,
                    }
                )
        return _mp_paginate(items, total, page, page_size)


@router.get("/api/mp/v1/favorite/check/{product_id}")
def mp_favorite_check(product_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpFavorite
    from app.db.session import get_db

    with get_db() as db:
        fav = db.query(MpFavorite).filter(MpFavorite.user_id == uid, MpFavorite.product_id == product_id).first()
        return _mp_json_response(200, "success", {"is_favorited": fav is not None, "fav_id": fav.id if fav else None})


@router.delete("/api/mp/v1/favorite/remove/{fav_id}")
def mp_favorite_remove(fav_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpFavorite
    from app.db.session import get_db

    with get_db() as db:
        deleted = db.query(MpFavorite).filter(MpFavorite.id == fav_id, MpFavorite.user_id == uid).delete()
        if not deleted:
            return _mp_json_response(404, "收藏记录不存在", success=False)
        db.commit()
        return _mp_json_response(200, "取消收藏成功")


@router.get("/api/mp/v1/product/list")
def mp_product_list(
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    keyword: str = Query(default=""),
    category: str = Query(default=""),
    sort_by: str = Query(default="newest"),
):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    keyword = keyword.strip()
    category = category.strip()
    from app.db.models import Product
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(Product).filter(Product.is_active == 1)
        if keyword:
            query = query.filter(
                (Product.name.ilike(f"%{keyword}%"))
                | (Product.model_number.ilike(f"%{keyword}%"))
                | (Product.description.ilike(f"%{keyword}%"))
            )
        if category:
            query = query.filter(Product.category == category)
        if sort_by == "price_asc":
            query = query.order_by(Product.price.asc())
        elif sort_by == "price_desc":
            query = query.order_by(Product.price.desc())
        else:
            query = query.order_by(Product.created_at.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for p in items:
            result.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "model_number": p.model_number or "",
                    "specification": p.specification or "",
                    "price": float(p.price) if p.price else 0,
                    "unit": p.unit or "个",
                    "brand": p.brand or "",
                    "category": p.category or "",
                    "description": (p.description or "")[:200],
                }
            )
        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/product/detail/{product_id}")
def mp_product_detail(product_id: int, x_user_id: str | None = Header(default=None, alias="X-User-ID")):
    from app.db.models import Product
    from app.db.session import get_db

    user_id = int(x_user_id) if x_user_id and str(x_user_id).isdigit() else None
    with get_db() as db:
        product = db.query(Product).filter(Product.id == product_id, Product.is_active == 1).first()
        if not product:
            return _mp_json_response(404, "商品不存在", success=False)
        if user_id:
            try:
                from app.db.models import MpBrowseHistory

                existing = (
                    db.query(MpBrowseHistory)
                    .filter(MpBrowseHistory.user_id == user_id, MpBrowseHistory.product_id == product_id)
                    .first()
                )
                if existing:
                    from sqlalchemy.sql import func

                    existing.viewed_at = func.now()
                else:
                    db.add(MpBrowseHistory(user_id=user_id, product_id=product_id))
                db.commit()
            except Exception:
                db.rollback()
        return _mp_json_response(
            200,
            "success",
            {
                "id": product.id,
                "name": product.name,
                "model_number": product.model_number or "",
                "specification": product.specification or "",
                "price": float(product.price) if product.price else 0,
                "unit": product.unit or "个",
                "brand": product.brand or "",
                "category": product.category or "",
                "description": product.description or "",
            },
        )


@router.get("/api/mp/v1/product/categories")
def mp_product_categories():
    from app.db.models import Product
    from app.db.session import get_db
    from sqlalchemy import distinct

    with get_db() as db:
        rows = db.query(distinct(Product.category)).filter(Product.is_active == 1, Product.category.isnot(None)).all()
        cats = sorted([r[0] for r in rows if r[0]])
        return _mp_json_response(200, "success", cats)


@router.get("/api/mp/v1/product/search")
def mp_product_search(
    keyword: str = Query(default=""),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    return mp_product_list(page=page, page_size=page_size, keyword=keyword, category="", sort_by="newest")


@router.get("/api/mp/v1/product/price/{product_id}")
def mp_product_price(product_id: int):
    from app.db.models import Product
    from app.db.session import get_db

    with get_db() as db:
        p = db.query(Product).filter(Product.id == product_id, Product.is_active == 1).first()
        if not p:
            return _mp_json_response(404, "商品不存在", success=False)
        return _mp_json_response(
            200,
            "success",
            {"product_id": p.id, "price": float(p.price) if p.price else 0, "unit": p.unit or "个"},
        )


@router.get("/api/mp/v1/order/list")
def mp_order_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status: str = Query(default=""),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    status_filter = status.strip()
    from app.db.models import MpOrder
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(MpOrder).filter(MpOrder.user_id == uid)
        if status_filter and status_filter != "all":
            query = query.filter(MpOrder.status == status_filter)
        query = query.order_by(MpOrder.created_at.desc())
        total = query.count()
        orders = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for o in orders:
            first_item = o.items[0] if o.items else None
            result.append(
                {
                    "id": o.id,
                    "order_no": o.order_no,
                    "status": o.status,
                    "pay_status": o.pay_status,
                    "total_amount": float(o.total_amount),
                    "pay_amount": float(o.pay_amount) if o.pay_amount else None,
                    "item_count": len(o.items),
                    "first_item_name": first_item.product_name if first_item else "",
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
            )
        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/order/detail/{order_id}")
def mp_order_detail(order_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpOrder
    from app.db.session import get_db

    with get_db() as db:
        order = db.query(MpOrder).filter(MpOrder.id == order_id, MpOrder.user_id == uid).first()
        if not order:
            return _mp_json_response(404, "订单不存在", success=False)
        items = []
        for item in order.items:
            items.append(
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "product_name": item.product_name,
                    "product_sku": item.product_sku or "",
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price),
                    "subtotal": float(item.subtotal),
                }
            )
        return _mp_json_response(
            200,
            "success",
            {
                "id": order.id,
                "order_no": order.order_no,
                "status": order.status,
                "pay_status": order.pay_status,
                "total_amount": float(order.total_amount),
                "pay_amount": float(order.pay_amount) if order.pay_amount else None,
                "pay_time": order.pay_time.isoformat() if order.pay_time else None,
                "delivery_name": order.delivery_name or "",
                "delivery_phone": order.delivery_phone or "",
                "delivery_address": order.delivery_address or "",
                "remark": order.remark or "",
                "items": items,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            },
        )


@router.get("/api/mp/v1/message/list")
def mp_message_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    type: str = Query(default=""),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    msg_type = type.strip()
    from app.db.models import MpNotification
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(MpNotification).filter(MpNotification.user_id == uid)
        if msg_type and msg_type != "all":
            query = query.filter(MpNotification.type == msg_type)
        query = query.order_by(MpNotification.created_at.desc())
        total = query.count()
        messages = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for msg in messages:
            result.append(
                {
                    "id": msg.id,
                    "title": msg.title,
                    "content": (msg.content or "")[:200],
                    "type": msg.type,
                    "is_read": msg.is_read,
                    "related_type": msg.related_type,
                    "related_id": msg.related_id,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            )
        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/message/unread-count")
def mp_message_unread_count(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpNotification
    from app.db.session import get_db

    with get_db() as db:
        count = db.query(MpNotification).filter(
            MpNotification.user_id == uid,
            MpNotification.is_read == False,
        ).count()
        return _mp_json_response(200, "success", {"count": count})


@router.get("/api/mp/v1/feedback/list")
def mp_feedback_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    from app.db.models import MpFeedback
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(MpFeedback).filter(MpFeedback.user_id == uid).order_by(MpFeedback.created_at.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for fb in items:
            result.append(
                {
                    "id": fb.id,
                    "type": fb.type,
                    "content": fb.content[:200],
                    "status": fb.status,
                    "has_reply": bool(fb.reply),
                    "replied_at": fb.replied_at.isoformat() if fb.replied_at else None,
                    "created_at": fb.created_at.isoformat() if fb.created_at else None,
                }
            )
        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/feedback/detail/{feedback_id}")
def mp_feedback_detail(feedback_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    import json as _json

    from app.db.models import MpFeedback
    from app.db.session import get_db

    with get_db() as db:
        fb = db.query(MpFeedback).filter(MpFeedback.id == feedback_id, MpFeedback.user_id == uid).first()
        if not fb:
            return _mp_json_response(404, "反馈不存在", success=False)
        images = []
        if fb.images:
            try:
                images = _json.loads(fb.images)
            except Exception:
                images = []
        return _mp_json_response(
            200,
            "success",
            {
                "id": fb.id,
                "type": fb.type,
                "content": fb.content,
                "images": images,
                "status": fb.status,
                "reply": fb.reply or "",
                "replied_at": fb.replied_at.isoformat() if fb.replied_at else None,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
            },
        )


@router.get("/api/mp/v1/ai/history")
def mp_ai_history(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    from app.db.models import AIConversation, AIConversationSession
    from app.db.session import get_db

    try:
        with get_db() as db:
            sessions = (
                db.query(AIConversationSession)
                .filter(AIConversationSession.user_id == uid)
                .order_by(AIConversationSession.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            result = []
            for session in sessions:
                last_msg = (
                    db.query(AIConversation)
                    .filter(AIConversation.session_id == session.id)
                    .order_by(AIConversation.created_at.desc())
                    .first()
                )
                result.append(
                    {
                        "session_id": session.id,
                        "last_message": last_msg.content[:100] if last_msg else "",
                        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                    }
                )
            return _mp_json_response(200, "success", result)
    except Exception as e:
        logger.error("mp ai history: %s", e)
        return _mp_json_response(500, "获取历史失败", success=False)


@router.get("/api/mp/v1/ai/intents")
def mp_ai_intents():
    intents = [
        {"key": "price_inquiry", "label": "询价", "example": "这个产品多少钱？"},
        {"key": "product_search", "label": "找产品", "example": "有没有白色的底漆？"},
        {"key": "order_status", "label": "查订单", "example": "我的订单到哪了？"},
        {"key": "after_sales", "label": "售后", "example": "产品质量有问题怎么办？"},
        {"key": "other", "label": "其他问题", "example": "我想咨询其他问题"},
    ]
    return _mp_json_response(200, "success", intents)


@router.get("/api/mp/v1/auth/session/check")
def mp_auth_session_check(authorization: str | None = Header(default=None)):
    return wechat_session_check(authorization)


@router.get("/api/mp/v1/user/info")
def mp_user_info(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"error": "missing_token"}, success=False)
    from app.db.models import User
    from app.db.session import get_db

    with get_db() as db:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            return _mp_json_response(404, "用户不存在", {"error": "user_not_found"}, success=False)
        return _mp_json_response(
            200,
            "success",
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name or "微信用户",
                "nickname": user.mp_nickname or "",
                "avatar": user.wx_avatar_url or "",
                "phone": user.mp_phone or "",
                "email": user.email or "",
                "role": user.role,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
        )


_emit_legacy_gaps_load_log()
