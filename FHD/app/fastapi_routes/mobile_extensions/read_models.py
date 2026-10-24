"""MobileReadModels: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from app.fastapi_routes.mobile_extensions.ports import (
    Callable,
    DatabaseCall,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MobileReadModelsPorts:
    database: DatabaseCall


class MobileReadModels:
    def __init__(self, ports: MobileReadModelsPorts) -> None:
        self.ports = ports

        def _approval_items(limit: int = 100) -> list[dict[str, Any]]:
            from app.db.models.approval import ApprovalRequest

            with ports.database() as db:
                rows = (
                    db.query(ApprovalRequest)
                    .order_by(ApprovalRequest.created_at.desc())
                    .limit(limit)
                    .all()
                )
                return [
                    {"id": r.id, "title": r.title, "status": r.status, "request_no": r.request_no}
                    for r in rows
                ]

        self._approval_items = _approval_items

        def _shipment_items(limit: int = 100) -> list[dict[str, Any]]:
            from app.db.models.shipment import ShipmentRecord

            with ports.database() as db:
                rows = (
                    db.query(ShipmentRecord).order_by(ShipmentRecord.id.desc()).limit(limit).all()
                )
                return [
                    {
                        "id": r.id,
                        "order_number": getattr(r, "order_number", None)
                        or getattr(r, "shipment_no", None),
                        "status": getattr(r, "status", None),
                    }
                    for r in rows
                ]

        self._shipment_items = _shipment_items

        def _safe_mobile_sync_items(
            name: str, loader: Callable[[], list[dict[str, Any]]]
        ) -> list[dict[str, Any]]:
            try:
                return cast("list[dict[str, Any]]", loader())
            except RECOVERABLE_ERRORS as exc:
                logger.warning("mobile sync: %s skipped: %s", name, exc)
                return []

        self._safe_mobile_sync_items = _safe_mobile_sync_items

        def _ai_conversation_changes(user: object, limit: int = 100) -> list[dict[str, Any]]:
            """查询当前用户最近的 AI 对话消息，供移动端增量同步。"""
            uid = int(getattr(user, "id", 0) or 0)
            if uid <= 0:
                return []
            try:
                from app.db.models.ai import AIConversation, AIConversationSession

                with ports.database() as db:
                    rows = (
                        db.query(AIConversation)
                        .join(
                            AIConversationSession,
                            AIConversation.session_id == AIConversationSession.session_id,
                        )
                        .filter(AIConversationSession.user_id == uid)
                        .order_by(AIConversation.id.desc())
                        .limit(limit)
                        .all()
                    )
                    return [
                        {
                            "id": r.id,
                            "session_id": r.session_id,
                            "role": r.role,
                            "content": r.content,
                            "intent": r.intent or "",
                            "created_at": r.created_at.isoformat() if r.created_at else "",
                        }
                        for r in reversed(rows)
                    ]
            except RECOVERABLE_ERRORS as exc:
                logger.warning("ai_conversation_changes: %s", exc)
                return []

        self._ai_conversation_changes = _ai_conversation_changes
