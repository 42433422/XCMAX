"""SyncRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.models import (
    SyncAckBody,
    SyncPullBody,
    SyncPushBody,
)
from app.fastapi_routes.mobile_extensions.ports import (
    AiCircleEmployeeProfilesCall,
    AiCircleUserCall,
    AiConversationChangesCall,
    ApplyInboxCall,
    ApprovalItemsCall,
    EnsureSyncSchemaCall,
    ListPostsCall,
    MobilePrincipal,
    MobileSyncCirclePostsCall,
    MobileSyncRuntimeContractCall,
    SafeMobileSyncItemsCall,
    ShipmentItemsCall,
    SyncCircleCall,
    SyncConnectionCall,
    SyncDatabaseCall,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncRoutesPorts:
    ai_circle_employee_profiles: AiCircleEmployeeProfilesCall
    ai_circle_user: AiCircleUserCall
    list_posts: ListPostsCall
    sync_circle: SyncCircleCall
    mobile_sync_runtime_contract: MobileSyncRuntimeContractCall
    sync_database: SyncDatabaseCall
    ensure_sync_schema: EnsureSyncSchemaCall
    sync_connection: SyncConnectionCall
    ai_conversation_changes: AiConversationChangesCall
    approval_items: ApprovalItemsCall
    mobile_sync_circle_posts: MobileSyncCirclePostsCall
    safe_mobile_sync_items: SafeMobileSyncItemsCall
    shipment_items: ShipmentItemsCall
    apply_inbox: ApplyInboxCall


class SyncRoutes:
    def __init__(self, ports: SyncRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _mobile_sync_runtime_contract() -> dict[str, Any]:
            return {
                "source": "cloud",
                "sync_mode": "cloud",
                "standalone_supported": True,
                "desktop_required": False,
                "executor_required": False,
                "mobile_flow_parity": True,
                "offline_cache_supported": True,
                "desktop_executor": {
                    "required": False,
                    "role": "optional_local_executor",
                    "required_for": ["local_files", "local_cli", "local_printing", "lan_devices"],
                },
            }

        self._mobile_sync_runtime_contract = _mobile_sync_runtime_contract

        async def _mobile_sync_circle_posts(
            user: object, *, limit: int = 50
        ) -> list[dict[str, Any]]:
            try:
                try:
                    await ports.sync_circle()
                except RECOVERABLE_ERRORS:  # noqa: BLE001 - 交流圈同步是拉取增强项，不能拖垮整次手机同步
                    logger.warning(
                        "mobile sync: circle modstore report sync skipped", exc_info=True
                    )

                uid, _, _ = ports.ai_circle_user(user)
                posts = ports.list_posts(user_id=uid, limit=limit)
                profiles = ports.ai_circle_employee_profiles()
                for post in posts:
                    profile = profiles.get(str(post.get("employee_id") or ""))
                    if profile:
                        post["author_name"] = profile["name"]
                        post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
                return posts
            except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - 手机同步的其他数据不能被交流圈投影拖垮
                logger.warning("mobile sync: circle posts skipped: %s", exc)
                return []

        self._mobile_sync_circle_posts = _mobile_sync_circle_posts

        @router.get("/sync/status", response_model=None)
        async def mobile_sync_status(user: MobilePrincipal | None = Depends(get_user)) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                db = ports.sync_database()
                st = dict(db.get_status())
                with ports.sync_connection() as conn:
                    ports.ensure_sync_schema(conn)
                    st["inbox_pending"] = conn.execute(
                        "SELECT COUNT(*) FROM sync_inbox WHERE status='pending'",
                    ).fetchone()[0]
            except RECOVERABLE_ERRORS:
                st = {"error": "同步服务健康检查失败", "healthy": False}
            st.update(ports.mobile_sync_runtime_contract())
            return format_mobile_response(data=st)

        self.mobile_sync_status = mobile_sync_status

        @router.post("/sync/pull", response_model=None)
        async def mobile_sync_pull(
            body: SyncPullBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                sync_db = ports.sync_database()
                changes = sync_db.get_changes(since_cursor=body.since_cursor, limit=200)
                cursor = sync_db.get_status().get("local_cursor") or body.since_cursor
                if cursor:
                    sync_db.update_remote_cursor(int(cursor))
                im_entity_types = {"im_message", "im_read_state"}
                im_changes = [
                    c for c in changes if str(c.get("entity_type") or "") in im_entity_types
                ]
                ai_changes = ports.ai_conversation_changes(user, limit=100)
                circle_posts = await ports.mobile_sync_circle_posts(user, limit=50)
                approvals = ports.safe_mobile_sync_items("approvals", ports.approval_items)
                shipments = ports.safe_mobile_sync_items("shipments", ports.shipment_items)
                return format_mobile_response(
                    data={
                        **ports.mobile_sync_runtime_contract(),
                        "cursor": cursor,
                        "changes": changes,
                        "im_changes": im_changes,
                        "im_change_count": len(im_changes),
                        "ai_changes": ai_changes,
                        "ai_change_count": len(ai_changes),
                        "circle_posts": circle_posts,
                        "circle_post_count": len(circle_posts),
                        "approvals": approvals,
                        "shipments": shipments,
                    },
                )
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile_sync_pull: %s", exc)
                return JSONResponse(
                    format_mobile_response(None, "同步服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_sync_pull = mobile_sync_pull

        @router.post("/sync/push", response_model=None)
        async def mobile_sync_push(
            body: SyncPushBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            actor = getattr(user, "username", None) or f"user-{getattr(user, 'id', 0)}"
            written = 0
            try:
                sync_db = ports.sync_database()
                for item in body.items[:50]:
                    sync_db.append_change(
                        item.entity_type,
                        item.entity_id,
                        item.operation,
                        item.payload,
                        actor=actor,
                        origin_node="mobile",
                    )
                    written += 1
                apply_result: dict[str, Any] = {}
                try:
                    apply_result = ports.apply_inbox(limit=written + 50) or {}
                except RECOVERABLE_ERRORS:
                    apply_result = {"error": "同步结果应用失败"}
                return format_mobile_response(data={"written": written, "apply": apply_result})
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile_sync_push: %s", exc)
                return JSONResponse(
                    format_mobile_response(None, "同步服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_sync_push = mobile_sync_push

        @router.post("/sync/ack", response_model=None)
        async def mobile_sync_ack(
            body: SyncAckBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            try:
                sync_db = ports.sync_database()
                sync_db.update_remote_cursor(int(body.cursor))
                return format_mobile_response(data={"acked": int(body.cursor)})
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile_sync_ack: %s", exc)
                return JSONResponse(
                    format_mobile_response(None, "同步服务暂不可用", success=False, code=500),
                    status_code=500,
                )

        self.mobile_sync_ack = mobile_sync_ack

        @router.get("/sync/conflicts", response_model=None)
        async def mobile_sync_conflicts(user: MobilePrincipal | None = Depends(get_user)) -> object:
            if user is None:
                return JSONResponse(
                    format_mobile_response(None, "未授权", success=False, code=401), status_code=401
                )
            items: list[dict[str, Any]] = []
            try:
                with ports.sync_connection() as conn:
                    ports.ensure_sync_schema(conn)
                    rows = conn.execute(
                        """
                        SELECT id, entity_type, entity_id, conflict_note, received_at
                        FROM sync_inbox WHERE status='conflict' ORDER BY id DESC LIMIT 50
                        """,
                    ).fetchall()
                    items = [dict(r) for r in rows]
            except RECOVERABLE_ERRORS:
                return format_mobile_response(data={"items": [], "error": "同步记录暂不可用"})
            return format_mobile_response(data={"items": items})

        self.mobile_sync_conflicts = mobile_sync_conflicts
