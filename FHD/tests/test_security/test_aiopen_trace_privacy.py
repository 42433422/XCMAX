"""AIOPEN audit copies omit business payloads without changing client responses."""

from __future__ import annotations

import copy
import json
import logging
from types import SimpleNamespace

import pytest

from app.fastapi_routes import aiopen_route_support as support

PRIVATE = "synthetic-private-quote-tax-customer-value"
LOGGER = logging.getLogger(__name__)


def _recorder(saved):
    def record(payload, **context):
        saved.append((copy.deepcopy(payload), copy.deepcopy(context)))
        return SimpleNamespace(run_id="audit-fixture")

    return record


@pytest.mark.parametrize("status", [100, 200, 599, 0, 600, True, "200", None])
def test_audit_output_keeps_only_typed_flags_and_http_status(status):
    result = support.safe_control_payload(
        {
            "success": False,
            "pending_approval": True,
            "status_code": status,
            "message": PRIVATE,
            "key": PRIVATE,
            "nested": {PRIVATE: [PRIVATE]},
        }
    )
    assert result["success"] is False and result["pending_approval"] is True
    assert ("status_code" in result) is (type(status) is int and 100 <= status <= 599)
    assert result["key_preview"] == "[REDACTED]"
    assert PRIVATE not in json.dumps(result)
    assert "success" not in support.safe_control_payload({"success": PRIVATE})


@pytest.mark.parametrize("tool", ["api_call", "ui_snapshot", PRIVATE])
def test_tool_trace_omits_arguments_results_and_unknown_tool_names(tool):
    saved = []
    args = {"body": {"quote": PRIVATE, "tax": PRIVATE}, "headers": {"Authorization": PRIVATE}}
    result = {"success": False, "status_code": 403, "message": PRIVATE, "data": [PRIVATE]}
    before = copy.deepcopy((args, result))
    run_id = support.trace_tool_call(
        route="/api/aiopen/invoke",
        channel="aiopen_invoke",
        tool=tool,
        args=args,
        result=result,
        create_trace_run=_recorder(saved),
        logger=LOGGER,
        user_id="existing-actor",
    )
    assert run_id == "audit-fixture" and (args, result) == before
    assert PRIVATE not in json.dumps(saved)
    payload, context = saved[0]
    record = payload["data"]["legacy_tool_records"][0]
    assert record["output"]["success"] is False and record["output"]["status_code"] == 403
    assert record["params"] == {"payload_redacted": True, "argument_count": 2}
    assert record["action"] == ("unknown_tool" if tool == PRIVATE else tool)
    assert context["user_id"] == "existing-actor"


def test_control_trace_does_not_mutate_or_redact_the_authorized_response():
    saved = []
    payload = {"success": True, "key": PRIVATE, "label": PRIVATE, "message": PRIVATE}
    body = {"key": PRIVATE, "base_url": "https://example.invalid/?key=" + PRIVATE}
    before = copy.deepcopy((payload, body))
    response = support.trace_control_result(
        payload,
        route="/api/aiopen/keys",
        action="keys_create",
        body=body,
        create_trace_run=_recorder(saved),
        logger=LOGGER,
    )
    assert (payload, body) == before
    assert response == {**payload, "run_id": "audit-fixture", "agent_run_id": "audit-fixture"}
    assert PRIVATE not in json.dumps(saved)


@pytest.mark.parametrize("kind", ["tool", "control"])
def test_trace_failure_does_not_log_exception_payload(kind, caplog):
    def failing_recorder(*args, **kwargs):
        raise ValueError(PRIVATE)

    with caplog.at_level(logging.WARNING, logger=__name__):
        if kind == "tool":
            result = support.trace_tool_call(
                route="/api/aiopen/invoke",
                channel="aiopen_invoke",
                tool="api_call",
                args={},
                result={},
                create_trace_run=failing_recorder,
                logger=LOGGER,
            )
            assert result == ""
        else:
            payload = {"success": True, "key": PRIVATE}
            result = support.trace_control_result(
                payload,
                route="/api/aiopen/keys",
                action="keys_create",
                create_trace_run=failing_recorder,
                logger=LOGGER,
            )
            assert result is payload
    assert "ValueError" in caplog.text and PRIVATE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_mcp_operational_exception_is_generic_but_programming_errors_propagate():
    async def invoke(*args):
        raise ValueError(PRIVATE)

    kwargs = {
        "manifest": lambda: {},
        "invoke": invoke,
        "format_result": lambda *_: "",
        "trace_call": lambda **_: "",
    }
    message = {"id": 7, "method": "tools/call", "params": {"name": "api_call"}}
    result = await support.handle_mcp_message(message, None, "2024-11-05", **kwargs)
    assert result == support.jsonrpc_error(7, -32603, "tool execution failed")
    assert PRIVATE not in json.dumps(result)

    async def programming_error(*args):
        raise TypeError("programming error fixture")

    kwargs["invoke"] = programming_error
    with pytest.raises(TypeError):
        await support.handle_mcp_message(message, None, "2024-11-05", **kwargs)


@pytest.mark.asyncio
async def test_mcp_client_receives_original_result_while_trace_is_minimized():
    saved = []
    original = {"success": True, "data": {"quote": PRIVATE}}

    async def invoke(*args):
        return original

    def trace(**kwargs):
        return support.trace_tool_call(**kwargs, create_trace_run=_recorder(saved), logger=LOGGER)

    result = await support.handle_mcp_message(
        {"id": 8, "method": "tools/call", "params": {"name": "api_call"}},
        None,
        "2024-11-05",
        manifest=lambda: {},
        invoke=invoke,
        format_result=lambda name, payload: json.dumps(payload),
        trace_call=trace,
    )
    assert json.loads(result["result"]["content"][0]["text"]) == original
    assert result["result"]["isError"] is False
    assert result["result"]["_meta"]["run_id"] == "audit-fixture"
    assert PRIVATE not in json.dumps(saved)
