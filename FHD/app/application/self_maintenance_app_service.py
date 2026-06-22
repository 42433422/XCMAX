"""自维护 loop runtime — 本地 MODstore :8788 读/写接口。"""

from __future__ import annotations

from typing import Any

from app.application.modstore_local_client import modstore_get, modstore_post


async def get_runtime_status_local(
    limit: int = 80,
    *,
    authorization: str | None = None,
) -> dict[str, Any]:
    bounded = max(1, min(int(limit or 80), 300))
    return await modstore_get(
        "/api/ops/self-maintenance/status",
        query=f"limit={bounded}",
        authorization=authorization,
    )


async def governance_review_local(
    note: str = "",
    *,
    authorization: str | None = None,
) -> dict[str, Any]:
    return await modstore_post(
        "/api/ops/self-maintenance/governance-review",
        json_body={"note": note},
        authorization=authorization,
    )


async def get_yuangon_onboard_status_local() -> dict[str, Any]:
    return await modstore_get("/api/admin/yuangon-onboard/status")


async def run_yuangon_onboard_local(payload: dict[str, Any]) -> dict[str, Any]:
    return await modstore_post(
        "/api/admin/yuangon-onboard/run",
        json_body=payload,
        timeout=900.0,
    )
