"""微信集成 Mod — 联系人 / 任务 / 消息。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query, Request

logger = logging.getLogger(__name__)


def _invoke(domain: str, action: str, **kwargs: Any):
    from app.mod_sdk.erp_domain_dispatch import invoke_erp_domain_handler

    return invoke_erp_domain_handler(domain, action, **kwargs)


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

    # ── 遗留路径代理 ────────────────────────────────────────────
    import wechat_contacts_routes

    wechat_contacts_routes.mount_wechat_contacts_routes(router)

    app.include_router(router)
    logger.info("xcagi-wechat-bridge registered: %s", mod_id)


def mod_init():
    logger.info("xcagi-wechat-bridge mod_init (wechat bridge)")