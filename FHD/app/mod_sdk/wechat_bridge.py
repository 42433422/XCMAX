"""Stable host contract for the standalone WeChat bridge Mod."""

from __future__ import annotations

from typing import Any


def list_contacts(
    *,
    keyword: str | None = None,
    contact_type: str | None = None,
    starred_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    from app.application import get_wechat_contact_app_service

    return get_wechat_contact_app_service().get_contacts(
        keyword=keyword,
        contact_type=contact_type,
        starred_only=starred_only,
        limit=limit,
    )


def get_contact_by_id(contact_id: int) -> dict[str, Any] | None:
    from app.application import get_wechat_contact_app_service

    return get_wechat_contact_app_service().get_contact_by_id(contact_id)


def list_tasks(
    *,
    contact_id: int | None = None,
    status: str = "pending",
    limit: int = 20,
) -> list[dict[str, Any]]:
    from app.application import get_wechat_task_app_service

    return get_wechat_task_app_service().get_tasks(
        contact_id=contact_id,
        status=status,
        limit=limit,
    )


def get_decrypt_status() -> dict[str, Any]:
    from app.application.wechat_decrypt_app_service import get_wechat_decrypt_status as impl

    return impl()


def auto_configure(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.application.wechat_decrypt_app_service import (
        wechat_decrypt_auto_configure_response,
    )

    return wechat_decrypt_auto_configure_response(body)


def mount_legacy_routes(router: Any) -> None:
    """Mount the legacy ``/wechat_contacts`` surface behind the stable SDK."""
    from fastapi import Body, Query
    from fastapi.responses import JSONResponse

    from app.mod_sdk.erp_wechat_contacts_facade import tag_legacy_response

    def tag(out: Any) -> Any:
        if isinstance(out, dict):
            out["source"] = "mod:xcagi-wechat-bridge"
        return out

    @router.get("/wechat_contacts")
    def contacts_list(
        type: str = Query(default="all"),
        keyword: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=20, ge=1, le=2000),
    ):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        return tag(
            wechat_contacts_list_compat(
                type=type,
                keyword=keyword,
                page=page,
                per_page=per_page,
            )
        )

    @router.get("/wechat_contacts/search")
    def contacts_search(q: str = Query(default="")):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_search_compat,
        )

        return tag_legacy_response(wechat_contacts_search_compat(q=q))

    @router.get("/wechat_contacts/work_mode_feed")
    def work_mode_feed(per_contact: int = Query(default=1, ge=1, le=100)):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_work_mode_feed

        return tag(wechat_work_mode_feed(per_contact=per_contact))

    @router.get("/wechat_contacts/ensure_contact_cache")
    def ensure_cache_get():
        from app.fastapi_routes.domains.wechat.routes import wechat_contacts_ensure_cache

        return wechat_contacts_ensure_cache()

    @router.post("/wechat_contacts/ensure_contact_cache")
    def ensure_cache_post():
        from app.fastapi_routes.domains.wechat.routes import (
            wechat_contacts_ensure_cache_post,
        )

        return wechat_contacts_ensure_cache_post()

    @router.post("/wechat_contacts/refresh_contact_cache")
    def refresh_contact_cache():
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_refresh_contact_cache_compat,
        )

        return tag_legacy_response(wechat_contacts_refresh_contact_cache_compat())

    @router.post("/wechat_contacts/refresh_messages_cache")
    def refresh_messages_cache():
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_refresh_messages_cache_compat,
        )

        return tag_legacy_response(wechat_contacts_refresh_messages_cache_compat())

    @router.post("/wechat_contacts/unstar_all")
    async def unstar_all():
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_unstar_all_compat,
        )

        return tag_legacy_response(await wechat_contacts_unstar_all_compat())

    @router.post("/wechat_contacts")
    def contacts_create(body: dict[str, Any] | None = Body(default=None)):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_create_compat,
        )

        return tag_legacy_response(wechat_contacts_create_compat(body=body or {}))

    @router.put("/wechat_contacts/{contact_id}")
    def contacts_update(
        contact_id: str,
        body: dict[str, Any] | None = Body(default=None),
    ):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_update_compat,
        )

        return tag_legacy_response(
            wechat_contacts_update_compat(contact_id, body=body or {})
        )

    @router.delete("/wechat_contacts/{contact_id}")
    def contacts_delete(contact_id: str):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_delete_compat,
        )

        return tag_legacy_response(wechat_contacts_delete_compat(contact_id))

    @router.get("/wechat_contacts/{contact_id}/context")
    def contacts_context(contact_id: str):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_context_compat,
        )

        return tag_legacy_response(wechat_contacts_context_compat(contact_id))

    @router.post("/wechat_contacts/{contact_id}/refresh_messages")
    def refresh_messages(contact_id: str):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_refresh_messages_compat,
        )

        return tag_legacy_response(wechat_contacts_refresh_messages_compat(contact_id))

    @router.post("/wechat_contacts/send_message")
    def send_message(body: dict[str, Any] | None = Body(default=None)):
        from app.fastapi_routes.domains.wechat.routes import wechat_contacts_send_message

        return wechat_contacts_send_message(body=body or {})

    @router.post("/wechat_contacts/open_chat")
    def open_chat(body: dict[str, Any] | None = Body(default=None)):
        del body
        return JSONResponse(
            {
                "success": False,
                "message": "open_chat 尚未在 compat 层实现，请使用桌面端 wechat_cv 工具",
            },
            status_code=501,
        )


__all__ = [
    "auto_configure",
    "get_contact_by_id",
    "get_decrypt_status",
    "list_contacts",
    "list_tasks",
    "mount_legacy_routes",
]
