"""One failure boundary for deterministic business queries.

Fetching and presentation are separate ports: a rejected operation never reaches
the success presenter, and both service and presentation failures keep the same
user-visible unavailable response.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from app.utils.operational_errors import RECOVERABLE_ERRORS

JsonObject = dict[str, Any]
Result = TypeVar("Result")


def slot_reply(
    intent: str,
    response: str,
    *,
    data: JsonObject | None = None,
    success: bool = True,
    **flags: Any,
) -> JsonObject:
    return {
        "success": success,
        "response": response,
        "data": {"intent": intent, **(data or {})},
        "normal_slot_dispatch": True,
        **flags,
    }


class QueryExecutor:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def run(
        self,
        route: JsonObject,
        *,
        intent: str,
        fetch: Callable[[], Result],
        present: Callable[[Result], JsonObject],
        failed: str,
        unavailable: str,
        log_name: str,
        reject: Callable[[JsonObject], JsonObject] | None = None,
        agent_tool: bool = False,
    ) -> JsonObject | None:
        if route.get("intent") != intent:
            return None
        try:
            result = fetch()
            if isinstance(result, dict) and result.get("success") is False:
                if reject is not None:
                    return reject(result)
                return slot_reply(
                    intent,
                    str(result.get("message") or result.get("response") or failed),
                    success=False,
                )
            return present(result)
        except RECOVERABLE_ERRORS as error:
            self._logger.warning("%s 失败: %s", log_name, error)
            body = {
                "success": False,
                "response": unavailable,
                "data": {},
                "normal_slot_dispatch": True,
            }
            if agent_tool:
                body["agent_tool_dispatch"] = True
            return body
