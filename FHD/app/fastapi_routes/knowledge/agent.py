"""Dataset HTTP projection of the shared capability execution contract."""

from __future__ import annotations

from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.knowledge.protocols import RecallMerger
from app.fastapi_routes.knowledge.serialization import _public_dataset_payload
from app.fastapi_routes.tools_execute import run_tools_execute_agent


class DatasetAgent:
    def __init__(self, *, recall: RecallMerger) -> None:
        self._recall = recall

    def run(
        self, *, request: Request, action: str, params: dict[str, Any], route_path: str
    ) -> JSONResponse:
        payload, status = run_tools_execute_agent(
            request=request,
            body={"tool_id": "dataset_rag", "action": action, "params": params},
            route_path=route_path,
        )
        if action == "query" and payload.get("success") is True:
            payload = self._recall(payload, request=request, params=params)
        return JSONResponse(
            cast("dict[str, Any]", _public_dataset_payload(payload)), status_code=status
        )
