"""UI input observations must not persist the value supplied to a control."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

from app.fastapi_routes.aiopen_route_support import trace_tool_call


def test_typing_trace_redacts_input_without_mutating_execution_payload():
    args = {"selector": "#password", "text": "private-value"}
    result = {"success": True, "typed": "private-value"}
    create = Mock(return_value=SimpleNamespace(run_id="trace-1"))
    assert (
        trace_tool_call(
            route="/api/aiopen/invoke",
            channel="rest",
            tool="ui_type",
            args=args,
            result=result,
            create_trace_run=create,
            logger=logging.getLogger(__name__),
        )
        == "trace-1"
    )
    record = create.call_args.args[0]["data"]["legacy_tool_records"][0]
    assert record["params"] == {"selector": "#password", "text": "[redacted]"}
    assert record["output"]["typed"] == "[redacted]"
    assert "private-value" not in repr(create.call_args)
    assert args["text"] == result["typed"] == "private-value"
