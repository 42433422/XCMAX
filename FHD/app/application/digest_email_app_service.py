"""日更 digest：本地 MODstore 优先（邮件 / 摘要列表 / Vibe / 补丁派发）。"""

from __future__ import annotations

import logging
from typing import Any

from app.application.modstore_local_client import (
    modstore_digest_base_url,
    modstore_get,
    modstore_post,
    prefer_local_modstore,
)

logger = logging.getLogger(__name__)


def _digest_timeout() -> float:
    import os

    try:
        return float(os.environ.get("MODSTORE_DIGEST_HTTP_TIMEOUT_SEC", "900"))
    except ValueError:
        return 900.0


async def trigger_digest_now_with_authorization(authorization: str) -> dict[str, Any]:
    return await modstore_post(
        "/api/admin/email/digest-now",
        authorization=authorization,
        timeout=_digest_timeout(),
    )


async def trigger_digest_now_local() -> dict[str, Any]:
    return await modstore_post("/api/admin/email/digest-now", timeout=_digest_timeout())


async def list_daily_digests_local(*, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    q = f"limit={max(1, min(int(limit), 100))}&offset={max(0, int(offset))}"
    return await modstore_get(
        "/api/agent/butler/daily-digests",
        query=q,
        base_url=modstore_digest_base_url(),
    )


async def get_daily_digest_local(record_id: int) -> dict[str, Any]:
    return await modstore_get(
        f"/api/agent/butler/daily-digests/{int(record_id)}",
        base_url=modstore_digest_base_url(),
    )


async def get_daily_digest_artifacts_local(record_id: int) -> dict[str, Any]:
    return await modstore_get(
        f"/api/agent/butler/daily-digests/{int(record_id)}/artifacts",
        base_url=modstore_digest_base_url(),
    )


async def list_action_items_local(*, kind: str = "", day: str = "") -> dict[str, Any]:
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    return await modstore_get(
        "/api/admin/action-items",
        query="&".join(q),
        base_url=modstore_digest_base_url(),
    )


async def action_items_stats_local(*, kind: str = "", day: str = "") -> dict[str, Any]:
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    return await modstore_get(
        "/api/admin/action-items/stats",
        query="&".join(q),
        base_url=modstore_digest_base_url(),
    )


async def set_action_item_status_local(item_id: int, status: str) -> dict[str, Any]:
    return await modstore_post(
        f"/api/admin/action-items/{int(item_id)}/status",
        json_body={"status": status},
        base_url=modstore_digest_base_url(),
    )


async def start_vibe_prep_local(
    record_id: int, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    return await modstore_post(
        f"/api/agent/butler/daily-digests/{int(record_id)}/vibe-prep/sessions",
        json_body=body or {},
        base_url=modstore_digest_base_url(),
    )


async def start_line_execute_local(
    record_id: int, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    return await modstore_post(
        f"/api/agent/butler/daily-digests/{int(record_id)}/line-execute",
        json_body=body or {},
        base_url=modstore_digest_base_url(),
    )


async def get_workbench_session_local(session_id: str) -> dict[str, Any]:
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        raise ValueError("session_id 必填")
    return await modstore_get(f"/api/workbench/sessions/{sid}")


def allow_local_digest() -> bool:
    return prefer_local_modstore()


# 兼容旧名
_allow_local_digest_list = allow_local_digest
_allow_local_digest_fallback = allow_local_digest
