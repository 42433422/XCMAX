"""员工大会：本地 MODstore 优先（与 digest 共用 modstore_local_client）。"""

from __future__ import annotations

import logging
from typing import Any

from app.application.modstore_local_client import (
    modstore_get,
    modstore_post,
    prefer_local_modstore,
)

logger = logging.getLogger(__name__)


def prefer_local_all_hands() -> bool:
    return prefer_local_modstore()


async def start_all_hands_session_local(body: dict[str, Any] | None = None) -> dict[str, Any]:
    return await modstore_post(
        "/api/agent/butler/all-hands-report/sessions",
        json_body=body or {},
    )


async def start_all_hands_session_with_authorization(
    authorization: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await modstore_post(
        "/api/agent/butler/all-hands-report/sessions",
        json_body=body or {},
        authorization=authorization,
    )


async def get_all_hands_session_local(session_id: str) -> dict[str, Any]:
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        raise ValueError("session_id 必填")
    return await modstore_get(f"/api/workbench/sessions/{sid}")


async def get_all_hands_session_with_authorization(
    authorization: str,
    session_id: str,
) -> dict[str, Any]:
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        raise ValueError("session_id 必填")
    return await modstore_get(f"/api/workbench/sessions/{sid}", authorization=authorization)
