# ruff: noqa: E402, F401
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx

from app.application.product_query_context import inject_product_query_fallback
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .types import (
    NodeExecutionResult,
    PlanGraph,
    StateSchema,
    WorkflowNode,
    WorkflowRunResult,
    apply_state_schema,
)

logger = logging.getLogger(__name__)

# 默认 StateSchema：覆盖 runtime_context 常用键。
DEFAULT_STATE_SCHEMA = (
    StateSchema()
    .declare("node_outputs", type=dict, merge="set")
    .declare("workflow_status", type=dict, merge="set")
    .declare("workflow_trace", type=list, merge="append")
    .declare("message", type=str, merge="set")
    .declare("agent_history", type=list, merge="append")
)

_sync_http_client: httpx.Client | None = None


def _get_sync_http_client() -> httpx.Client:
    global _sync_http_client
    if _sync_http_client is None:
        _sync_http_client = httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _sync_http_client


def close_sync_http_client() -> None:
    """Close the reusable workflow HTTP client during application shutdown."""
    global _sync_http_client
    client = _sync_http_client
    _sync_http_client = None
    if client is not None and not client.is_closed:
        client.close()


from app.application.workflow.engine_workflowengine_mixin01 import _WorkflowEnginePart01Mixin
from app.application.workflow.engine_workflowengine_mixin02 import _WorkflowEnginePart02Mixin


class WorkflowEngine(_WorkflowEnginePart01Mixin, _WorkflowEnginePart02Mixin):
    pass


























