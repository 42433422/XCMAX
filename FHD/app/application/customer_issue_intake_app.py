"""Private rework submits the same durable Market ticket on every retry."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.application.private_mod_delivery_app import custom_delivery_remote_json
from app.services.user_cs_change_request import bind_change_request_intake, create_change_request


async def submit_private_rework(
    *,
    market_user_id: int,
    token: str,
    mod_id: str,
    track: str,
    node_id: str,
    note: str,
    version: str,
    username: str = "",
) -> dict[str, Any]:
    if not token or market_user_id <= 0:
        raise PermissionError("转返工须绑定市场账号并登录")
    identity = hashlib.sha256(
        json.dumps(
            [market_user_id, mod_id, track, node_id, note, version], ensure_ascii=False
        ).encode()
    ).hexdigest()
    title = f"定制交付返工 · {mod_id} · {node_id or track}"
    description = (
        f"Mod：{mod_id}\n版本：{version}\n轨道：{track}\n节点：{node_id or '整轨'}\n问题：{note}"
    )
    row = create_change_request(
        market_user_id,
        change_type="bug_fix",
        title=title,
        description=description,
        username=username,
        source="private_mod_rework",
        idempotency_key=identity,
    )
    payload = {
        "source": "private_mod_rework",
        "source_ref": str(row["id"]),
        "title": title,
        "description": description,
        "issue_domain": "custom",
        "target_mod_id": mod_id,
        "installed_version": version,
        "acceptance_criteria": f"修复并验证原问题：{note}",
    }
    try:
        result = await custom_delivery_remote_json(
            token, "/api/customer-service/issues/intake", method="POST", payload=payload
        )
        if (
            result.get("success") is not True
            or not result.get("ticket_id")
            or not str(result.get("ticket_no") or "").strip()
        ):
            raise RuntimeError("统一工单未返回受理成功与工单标识")
    except (ConnectionError, RuntimeError, PermissionError) as exc:
        bind_change_request_intake(market_user_id, str(row["id"]), {"error": str(exc)})
        raise
    bound = bind_change_request_intake(market_user_id, str(row["id"]), result)
    return {
        **bound,
        "local_ticket_no": bound["ticket_no"],
        "ticket_no": result["ticket_no"],
        "market_ticket_id": result["ticket_id"],
    }
