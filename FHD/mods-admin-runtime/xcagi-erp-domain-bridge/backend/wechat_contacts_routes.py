# -*- coding: utf-8 -*-
"""里程碑 H：/api/wechat_contacts/* 遗留路径 Mod 门面代理。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query

from app.mod_sdk.erp_wechat_contacts_facade import tag_legacy_response


def _to_work_mode_feed_payload(raw: dict, *, per_contact: int) -> dict:
    """Adapt the legacy desktop feed into the shape consumed by the chat assistant."""
    items = raw.get("items") if isinstance(raw, dict) else []
    if not isinstance(items, list):
        items = []
    feed: list[dict] = []
    for index, item in enumerate(items[:per_contact]):
        if not isinstance(item, dict):
            continue
        contact_id = str(item.get("username") or item.get("contact_id") or index + 1)
        summary = str(item.get("summary") or "").strip()
        message = {
            "role": "contact",
            "text": summary,
            "timestamp": item.get("timestamp") or 0,
            "msg_type": str(item.get("msg_type") or "text"),
        }
        feed.append(
            {
                "contact_id": contact_id,
                "contact_name": str(item.get("display_name") or contact_id),
                "unread_count": int(item.get("unread_count") or 0),
                "messages": [message] if summary else [],
            }
        )
    error = str(raw.get("error") or "").strip() if isinstance(raw, dict) else ""
    return {
        "success": True,
        "feed": feed,
        "items": items[:per_contact],
        "per_contact": per_contact,
        "unavailable_reason": error or None,
    }


def mount_wechat_contacts_routes(router: APIRouter) -> None:
    @router.get("/wechat_contacts")
    def mod_wechat_contacts_list(
        type: str = Query("all"),
        keyword: str = Query(""),
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=200),
    ):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_list_compat

        return tag_legacy_response(
            wechat_contacts_list_compat(type=type, keyword=keyword, page=page, per_page=per_page)
        )

    @router.get("/wechat_contacts/search")
    def mod_wechat_contacts_search(q: str = Query(default="")):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_search_compat

        # 直接调用 FastAPI 路由函数时不会执行依赖注入；若不显式传 keyword，
        # 其默认值仍是 Query 对象，空 q 会在 .strip() 处触发 500。
        return tag_legacy_response(wechat_contacts_search_compat(q=q, keyword=""))

    @router.get("/wechat_contacts/work_mode_feed")
    def mod_wechat_work_mode_feed(per_contact: int = Query(default=1, ge=1, le=100)):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_work_mode_feed

        return tag_legacy_response(
            _to_work_mode_feed_payload(
                wechat_work_mode_feed(per_contact=per_contact),
                per_contact=per_contact,
            )
        )

    @router.get("/wechat_contacts/decrypt_status")
    def mod_wechat_contacts_decrypt_status():
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_contacts_decrypt_status_compat

        return wechat_contacts_decrypt_status_compat()

    @router.get("/wechat_contacts/ensure_contact_cache")
    def mod_wechat_ensure_cache_get():
        from app.fastapi_routes.legacy_wechat import wechat_contacts_ensure_cache

        return wechat_contacts_ensure_cache()

    @router.post("/wechat_contacts/ensure_contact_cache")
    def mod_wechat_ensure_cache_post():
        from app.fastapi_routes.legacy_wechat import wechat_contacts_ensure_cache_post

        return wechat_contacts_ensure_cache_post()

    @router.post("/wechat_contacts/refresh_contact_cache")
    def mod_wechat_refresh_contact_cache():
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_refresh_contact_cache_compat

        return tag_legacy_response(wechat_contacts_refresh_contact_cache_compat())

    @router.post("/wechat_contacts/refresh_messages_cache")
    def mod_wechat_refresh_messages_cache():
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_refresh_messages_cache_compat

        return tag_legacy_response(wechat_contacts_refresh_messages_cache_compat())

    @router.get("/wechat_contacts/message_source_size")
    def mod_wechat_message_source_size():
        from app.fastapi_routes.legacy_wechat import wechat_contacts_message_source_size

        return wechat_contacts_message_source_size()

    @router.get("/wechat_contacts/work_mode_feed")
    def mod_wechat_work_mode_feed(per_contact: int = Query(default=1, ge=1, le=100)):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_work_mode_feed

        return wechat_work_mode_feed(per_contact=per_contact)

    @router.post("/wechat_contacts/unstar_all")
    async def mod_wechat_unstar_all():
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_unstar_all_compat

        return tag_legacy_response(await wechat_contacts_unstar_all_compat())

    @router.post("/wechat_contacts")
    def mod_wechat_contacts_create(body: dict | None = Body(default=None)):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_create_compat

        return tag_legacy_response(wechat_contacts_create_compat(body=body or {}))

    @router.put("/wechat_contacts/{contact_id}")
    def mod_wechat_contacts_update(contact_id: str, body: dict | None = Body(default=None)):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_update_compat

        return tag_legacy_response(
            wechat_contacts_update_compat(contact_id, body=body or {})
        )

    @router.delete("/wechat_contacts/{contact_id}")
    def mod_wechat_contacts_delete(contact_id: str):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_delete_compat

        return tag_legacy_response(wechat_contacts_delete_compat(contact_id))

    @router.get("/wechat_contacts/{contact_id}/context")
    def mod_wechat_contacts_context(contact_id: str):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_context_compat

        return tag_legacy_response(wechat_contacts_context_compat(contact_id))

    @router.post("/wechat_contacts/{contact_id}/refresh_messages")
    def mod_wechat_refresh_messages(contact_id: str):
        from app.fastapi_routes.xcagi_compat_wechat import wechat_contacts_refresh_messages_compat

        return tag_legacy_response(wechat_contacts_refresh_messages_compat(contact_id))

    @router.post("/wechat_contacts/send_message")
    def mod_wechat_send_message(body: dict | None = Body(default=None)):
        from app.fastapi_routes.legacy_wechat import wechat_contacts_send_message

        return wechat_contacts_send_message(body=body or {})

    @router.post("/wechat_contacts/open_chat")
    def mod_wechat_open_chat(body: dict | None = Body(default=None)):
        _ = body
        return tag_legacy_response(
            {
                "success": False,
                "message": "open_chat 尚未在 compat 层实现，请使用桌面端 wechat_cv 工具",
            }
        )
