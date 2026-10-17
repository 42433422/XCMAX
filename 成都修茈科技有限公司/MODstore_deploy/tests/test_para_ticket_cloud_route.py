"""工单 AI 处理优先走云端执行器（Grok Bot）的路由测试。"""

from modstore_server import para_delegate_handler as mod

TICKET_INPUT = {"event_type": "ops.intake.customer_ticket", "role": "scout"}


def test_grok_bot_is_a_valid_para_tool():
    assert "grok_bot" in mod._VALID_DEV_TOOLS
    assert mod._normalize_tool_name("grok-bot") == "grok_bot"
    assert mod._normalize_tool_name("grok") == "grok_bot"


def test_ticket_routes_to_cloud_device_when_configured(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac-local")
    monkeypatch.setenv("MODSTORE_PARA_TICKET_DEVICE_ID", "grok-cloud")
    monkeypatch.delenv("MODSTORE_PARA_TICKET_TOOL", raising=False)
    req = mod._build_request(
        task="t", input_data=dict(TICKET_INPUT), employee_id="change-request-auditor"
    )
    assert req["device_id"] == "grok-cloud"
    assert req["tool_name"] == "grok_bot"
    assert req["dispatch_line"] == "grok-bot-cloud"
    assert mod._tool_candidates(req)[0] == "grok_bot"


def test_non_ticket_dispatch_keeps_existing_route(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac-local")
    monkeypatch.setenv("MODSTORE_PARA_TICKET_DEVICE_ID", "grok-cloud")
    req = mod._build_request(
        task="t",
        input_data={"event_type": "self_maintenance"},
        employee_id="vibe-coding-maintainer",
    )
    assert req["device_id"] == "mac-local"
    assert req["tool_name"] == ""


def test_ticket_route_disabled_without_env(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac-local")
    monkeypatch.delenv("MODSTORE_PARA_TICKET_DEVICE_ID", raising=False)
    req = mod._build_request(
        task="t", input_data=dict(TICKET_INPUT), employee_id="change-request-auditor"
    )
    assert req["device_id"] == "mac-local"


def test_explicit_device_id_wins_over_ticket_route(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_TICKET_DEVICE_ID", "grok-cloud")
    req = mod._build_request(
        task="t",
        input_data={**TICKET_INPUT, "device_id": "chosen"},
        employee_id="change-request-auditor",
    )
    assert req["device_id"] == "chosen"


def test_grok_bot_device_eligibility_uses_reported_tool():
    device = {"status": "online", "tools": [{"toolName": "grok_bot", "status": "idle"}]}
    assert mod._device_eligible(device, "grok_bot") is True
    assert (
        mod._device_eligible(
            {**device, "tools": [{"toolName": "grok_bot", "status": "not_installed"}]},
            "grok_bot",
        )
        is False
    )
