"""Tool request values and exceptions must not enter application logs."""

import logging

import pytest

from app.services.tools_execution import executor


@pytest.mark.parametrize("route", ["registered", "legacy", "error"])
def test_tool_execution_never_logs_request_or_exception_values(monkeypatch, caplog, route):
    secret = "test-only-xxxxxxxxxxxxxxxxxxxxxxxx"
    payload = {
        "tool_id": secret,
        "action": secret,
        "params": {"order_text": secret, secret: secret},
    }
    calls = []
    monkeypatch.setattr(executor, "_j", lambda body, status: (body, status))
    monkeypatch.setattr(executor, "_normalize_action", lambda action, params: action)
    monkeypatch.setattr(executor, "_validate_required_params", lambda *args: (True, ""))
    monkeypatch.setattr(
        executor,
        "get_workflow_tool_registry",
        lambda: {secret: {"actions": {secret: {}}}} if route == "registered" else {},
    )

    def invoke(*args, **kwargs):
        calls.append((args, kwargs))
        if route == "error":
            raise ValueError(secret)
        return {"success": True}

    monkeypatch.setattr(executor, "execute_registered_workflow_tool", invoke)
    monkeypatch.setattr(executor, "dispatch_legacy_tool_payload", invoke)
    with caplog.at_level(logging.INFO, logger=executor.__name__):
        result = executor.execute_tool_from_payload(payload)
    assert len(calls) == 1
    assert secret not in caplog.text
    assert "request received" in caplog.text
    if route == "registered":
        assert result == ({"success": True}, 200)
        assert calls[0][1]["params"] is payload["params"]
    elif route == "legacy":
        assert result == {"success": True}
        assert calls[0][0][2] is payload["params"]
    else:
        assert result == ({"success": False, "message": secret}, 500)
