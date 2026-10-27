"""AIOPEN audit copies omit business payloads without changing client responses."""

from __future__ import annotations

import copy
import json
import logging
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.fastapi_routes import aiopen_route_support as support

PRIVATE = "synthetic-private-quote-tax-customer-value"
LOGGER = logging.getLogger(__name__)


@pytest.fixture()
def audit():
    saved = []

    def record(payload, **context):
        saved.append(copy.deepcopy((payload, context)))
        return SimpleNamespace(run_id="audit-fixture")

    common = {"create_trace_run": record, "logger": LOGGER}
    tool_defaults = {"route": "/api/aiopen/invoke", "channel": "aiopen_invoke", "tool": "api_call"}
    tool = partial(support.trace_tool_call, args={}, result={}, **tool_defaults, **common)
    control_defaults = {"route": "/api/aiopen/keys", "action": "keys_create"}
    control = partial(support.trace_control_result, **control_defaults, **common)
    return saved, tool, control


@pytest.mark.parametrize("status", [100, 200, 599, 0, 600, True, "200", None])
def test_audit_output_keeps_only_typed_flags_and_http_status(status):
    payload = {"message": PRIVATE, "key": PRIVATE, "nested": {PRIVATE: [PRIVATE]}}
    payload.update(success=False, pending_approval=True, status_code=status)
    result = support.safe_control_payload(payload)
    assert result["success"] is False and result["pending_approval"] is True
    assert ("status_code" in result) is (type(status) is int and 100 <= status <= 599)
    assert result["key_preview"] == "[REDACTED]"
    assert PRIVATE not in json.dumps(result)
    assert "success" not in support.safe_control_payload({"success": PRIVATE})


@pytest.mark.parametrize("tool", ["api_call", "ui_snapshot", PRIVATE])
def test_tool_trace_omits_arguments_results_and_unknown_tool_names(tool, audit):
    saved, trace, _ = audit
    args = {"body": {"quote": PRIVATE, "tax": PRIVATE}, "headers": {"Authorization": PRIVATE}}
    result = {"success": False, "status_code": 403, "message": PRIVATE, "data": [PRIVATE]}
    before = copy.deepcopy((args, result))
    run_id = trace(tool=tool, args=args, result=result, user_id="existing-actor")
    assert run_id == "audit-fixture" and (args, result) == before
    assert PRIVATE not in json.dumps(saved)
    payload, context = saved[0]
    record = payload["data"]["legacy_tool_records"][0]
    assert record["output"]["success"] is False and record["output"]["status_code"] == 403
    assert record["params"] == {"payload_redacted": True, "argument_count": 2}
    assert record["action"] == ("unknown_tool" if tool == PRIVATE else tool)
    assert context["user_id"] == "existing-actor"


def test_control_trace_does_not_mutate_or_redact_the_authorized_response(audit):
    saved, _, trace = audit
    payload = {"success": True, "key": PRIVATE, "label": PRIVATE, "message": PRIVATE}
    body = {"key": PRIVATE, "base_url": "https://example.invalid/?key=" + PRIVATE}
    before = copy.deepcopy((payload, body))
    response = trace(payload, body=body)
    assert (payload, body) == before
    assert response == {**payload, "run_id": "audit-fixture", "agent_run_id": "audit-fixture"}
    assert PRIVATE not in json.dumps(saved)


@pytest.mark.parametrize("kind", ["tool", "control"])
def test_trace_failure_does_not_log_exception_payload(kind, caplog, audit):
    def failing_recorder(*args, **kwargs):
        raise ValueError(PRIVATE)

    _, tool, control = audit
    payload = {"success": True, "key": PRIVATE}
    call = tool if kind == "tool" else partial(control, payload)
    with caplog.at_level(logging.WARNING, logger=__name__):
        result = call(create_trace_run=failing_recorder)
    assert result == "" if kind == "tool" else result is payload
    assert "ValueError" in caplog.text and PRIVATE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def _mcp(invoke, trace=lambda **_: "", request_id=7):
    message = {"id": request_id, "method": "tools/call", "params": {"name": "api_call"}}
    kwargs = {"manifest": lambda: {}, "invoke": invoke, "trace_call": trace}
    kwargs["format_result"] = lambda name, payload: json.dumps(payload)
    return await support.handle_mcp_message(message, None, "2024-11-05", **kwargs)


@pytest.mark.asyncio
async def test_mcp_operational_exception_is_generic_but_programming_errors_propagate():
    result = await _mcp(AsyncMock(side_effect=ValueError(PRIVATE)))
    assert result == support.jsonrpc_error(7, -32603, "tool execution failed")
    assert PRIVATE not in json.dumps(result)
    with pytest.raises(TypeError):
        await _mcp(AsyncMock(side_effect=TypeError("programming error fixture")))


@pytest.mark.asyncio
async def test_mcp_client_receives_original_result_while_trace_is_minimized(audit):
    saved, trace, _ = audit
    original = {"success": True, "data": {"quote": PRIVATE}}
    result = await _mcp(AsyncMock(return_value=original), trace, request_id=8)
    assert json.loads(result["result"]["content"][0]["text"]) == original
    assert result["result"]["isError"] is False
    assert result["result"]["_meta"]["run_id"] == "audit-fixture"
    assert PRIVATE not in json.dumps(saved)
