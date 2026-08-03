"""微信集成 Mod — 联系人 / 任务 / 消息。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
MOD_SOURCE = "mod:xcagi-wechat-bridge"
EXECUTION_PATH = "mod_domain_handler"


def _invoke(domain: str, action: str, **kwargs: Any):
    if domain != "wechat":
        raise RuntimeError(f"wechat bridge domain missing: {domain}.{action}")

    if action == "contacts_list":
        from app.mod_sdk.wechat_bridge import list_contacts

        contact_type = str(kwargs.get("type") or "all")
        starred = str(kwargs.get("starred") or "false")
        contacts = list_contacts(
            keyword=kwargs.get("keyword"),
            contact_type=contact_type if contact_type != "all" else None,
            starred_only=starred.lower() == "true",
            limit=int(kwargs.get("limit") or 100),
        )
        return _tag({"success": True, "data": contacts, "total": len(contacts)})

    if action == "contact_get":
        from app.mod_sdk.wechat_bridge import get_contact_by_id

        contact = get_contact_by_id(int(kwargs.get("contact_id") or 0))
        if contact:
            return _tag({"success": True, "data": contact})
        return JSONResponse({"success": False, "message": "联系人不存在"}, status_code=404)

    if action == "tasks":
        from app.mod_sdk.wechat_bridge import list_tasks

        tasks = list_tasks(
            contact_id=kwargs.get("contact_id"),
            status=str(kwargs.get("status") or "pending"),
            limit=int(kwargs.get("limit") or 20),
        )
        return _tag({"success": True, "data": tasks, "total": len(tasks)})

    raise RuntimeError(f"wechat bridge action missing: {domain}.{action}")


def _tag(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "source": MOD_SOURCE,
        "execution_path": EXECUTION_PATH,
    }


def _decrypt_status() -> dict[str, Any]:
    from app.mod_sdk.wechat_bridge import get_decrypt_status

    return get_decrypt_status()


def _auto_configure(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.mod_sdk.wechat_bridge import auto_configure

    return auto_configure(body)


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
        return _invoke(
            "wechat",
            "contacts_list",
            keyword=keyword,
            type=type,
            starred=starred,
            limit=limit,
        )

    @router.get("/wechat/contacts/{contact_id:int}")
    def mod_wechat_contact_get(contact_id: int):
        return _invoke("wechat", "contact_get", contact_id=contact_id)

    @router.get("/wechat/tasks")
    def mod_wechat_tasks(
        status: str = Query(default="pending"),
        contact_id: int | None = Query(default=None),
        limit: int = Query(default=20),
    ):
        return _invoke(
            "wechat",
            "tasks",
            status=status,
            contact_id=contact_id,
            limit=limit,
        )

    @router.get("/wechat/decrypt/status")
    def mod_wechat_decrypt_status():
        return _decrypt_status()

    @router.post("/wechat/decrypt/auto_configure")
    def mod_wechat_decrypt_auto_configure(
        body: dict[str, Any] = Body(default_factory=dict),
    ):
        return _auto_configure(body)

    # ── 遗留路径代理 ────────────────────────────────────────────
    from app.mod_sdk.wechat_bridge import mount_legacy_routes

    mount_legacy_routes(router)

    app.include_router(router)
    logger.info("xcagi-wechat-bridge registered: %s", mod_id)


def mod_init():
    logger.info("xcagi-wechat-bridge mod_init (wechat bridge)")
