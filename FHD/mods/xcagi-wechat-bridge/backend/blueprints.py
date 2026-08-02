"""微信集成 Mod — 联系人 / 任务 / 消息。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)


MOD_SOURCE = "mod:xcagi-wechat-bridge"
EXECUTION_PATH = "mod_wechat_handler"


def _tag(out: Any) -> Any:
    if isinstance(out, dict):
        tagged = dict(out)
        inner = tagged.get("execution_path")
        if inner and inner != EXECUTION_PATH:
            tagged["handler_via"] = inner
        tagged["source"] = MOD_SOURCE
        tagged["execution_path"] = EXECUTION_PATH
        return tagged
    return out


def _contacts_list(**kw: Any) -> Any:
    from app.application import get_wechat_contact_app_service

    keyword = kw.get("keyword")
    contact_type = str(kw.get("type") or "all")
    starred = str(kw.get("starred") or "false")
    limit = int(kw.get("limit") or 100)
    contacts = get_wechat_contact_app_service().get_contacts(
        keyword=keyword,
        contact_type=contact_type if contact_type != "all" else None,
        starred_only=starred.lower() == "true",
        limit=limit,
    )
    return _tag({"success": True, "data": contacts, "total": len(contacts)})


def _contact_get(contact_id: int) -> Any:
    from fastapi.responses import JSONResponse

    from app.application import get_wechat_contact_app_service

    contact = get_wechat_contact_app_service().get_contact_by_id(contact_id)
    if contact:
        return _tag({"success": True, "data": contact})
    return JSONResponse({"success": False, "message": "联系人不存在"}, status_code=404)


def _tasks(**kw: Any) -> Any:
    from fastapi.responses import JSONResponse

    from app.application import get_wechat_task_app_service

    try:
        tasks = get_wechat_task_app_service().get_tasks(
            contact_id=kw.get("contact_id"),
            status=str(kw.get("status") or "pending"),
            limit=int(kw.get("limit") or 20),
        )
        return _tag({"success": True, "data": tasks, "total": len(tasks)})
    except Exception as exc:  # noqa: BLE001 - preserve legacy error contract
        return JSONResponse(
            {"success": False, "message": f"查询失败：{exc}"}, status_code=500
        )


def register_fastapi_routes(app, mod_id: str) -> None:
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"wechat-{mod_id}"])

    @router.get("/status")
    def status():
        return {
            "success": True,
            "data": {
                "mod_id": mod_id,
                "phase": "L",
                "description": "微信集成 Mod：联系人 / 任务 / 消息",
            },
        }

    # ── 微信联系人 ─────────────────────────────────────────────
    @router.get("/wechat/contacts")
    def mod_wechat_contacts(
        keyword: str | None = Query(default=None),
        type: str = Query(default="all"),
        starred: str = Query(default="false"),
        limit: int = Query(default=100),
    ):
        return _contacts_list(
            keyword=keyword,
            type=type,
            starred=starred,
            limit=limit,
        )

    @router.get("/wechat/contacts/{contact_id:int}")
    def mod_wechat_contact_get(contact_id: int):
        return _contact_get(contact_id)

    @router.get("/wechat/tasks")
    def mod_wechat_tasks(
        status: str = Query(default="pending"),
        contact_id: int | None = Query(default=None),
        limit: int = Query(default=20),
    ):
        return _tasks(
            status=status,
            contact_id=contact_id,
            limit=limit,
        )

    # ── 遗留路径代理 ────────────────────────────────────────────
    import wechat_contacts_routes

    wechat_contacts_routes.mount_wechat_contacts_routes(router)

    app.include_router(router)
    logger.info("xcagi-wechat-bridge registered: %s", mod_id)


def mod_init():
    logger.info("xcagi-wechat-bridge mod_init (wechat bridge)")
