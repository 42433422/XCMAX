"""客服工单优先走云端执行器（Grok Bot）的路由测试。"""

from modstore_server import para_delegate_handler as mod

TICKET = {"event_type": "ops.intake.customer_ticket", "role": "scout"}


def _req(input_data, employee_id="change-request-auditor"):
    return mod._build_request(task="t", input_data=input_data, employee_id=employee_id)


def test_ticket_routes_to_grok_bot_only_when_configured(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac-local")
    monkeypatch.delenv("MODSTORE_PARA_TICKET_TOOL", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_TICKET_DEVICE_ID", raising=False)
    assert _req(dict(TICKET))["device_id"] == "mac-local"
    monkeypatch.setenv("MODSTORE_PARA_TICKET_DEVICE_ID", "grok-cloud")
    req = _req(dict(TICKET))
    assert (req["device_id"], req["tool_name"]) == ("grok-cloud", "grok_bot")
    assert mod._tool_candidates(req)[0] == "grok_bot"
    assert _req({**TICKET, "device_id": "chosen"})["device_id"] == "chosen"
    other = _req({"event_type": "self_maintenance"}, "vibe-coding-maintainer")
    assert (other["device_id"], other["tool_name"]) == ("mac-local", "")
    assert mod._normalize_tool_name("grok-bot") == "grok_bot"
    assert mod._device_eligible(
        {"status": "online", "tools": [{"toolName": "grok_bot", "status": "idle"}]}, "grok_bot"
    )
