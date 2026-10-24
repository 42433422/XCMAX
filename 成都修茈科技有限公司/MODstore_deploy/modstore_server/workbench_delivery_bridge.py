"""Public session API retained for customer-delivery integrations."""

from __future__ import annotations

from typing import Any


async def start_workbench_session_for_user(
    user_id: int,
    payload: dict[str, Any],
    *,
    session_id: str = "",
    run_inline: bool = False,
    delivery_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    from modstore_server.workbench_api import start_workbench_session_for_user as operation

    return await operation(
        user_id,
        payload,
        session_id=session_id,
        run_inline=run_inline,
        delivery_context=delivery_context,
    )


async def get_workbench_session_snapshot(session_id: str, user_id: int) -> dict[str, Any] | None:
    from modstore_server.workbench_api import get_workbench_session_snapshot as operation

    return await operation(session_id, user_id)


__all__ = ["get_workbench_session_snapshot", "start_workbench_session_for_user"]
