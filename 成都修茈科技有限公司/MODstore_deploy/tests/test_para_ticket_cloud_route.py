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


ROUTE = "grok_bot@grok-cloud,dolt@dolt-cloud"


def _route_env(monkeypatch, route=ROUTE):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac-local")
    monkeypatch.setenv("MODSTORE_PARA_TICKET_DEVICE_ID", "legacy-grok")
    monkeypatch.setenv("MODSTORE_PARA_TICKET_ROUTE", route)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)


def _fake_once(monkeypatch, results):
    calls = []

    def fake(req):
        calls.append((req["device_id"], req["tool_name"], mod._tool_candidates(req)))
        return results[len(calls) - 1]

    monkeypatch.setattr(mod, "_post_para_api_once", fake)
    return calls


def test_ticket_route_parses_hops_and_keeps_legacy_when_unset(monkeypatch):
    _route_env(monkeypatch, "grok_bot@grok-cloud, dolt@dolt-cloud,bogus@x,dolt@,dolt@dolt-cloud")
    assert mod._ticket_route_hops(dict(TICKET)) == [
        {"tool_name": "grok_bot", "device_id": "grok-cloud"},
        {"tool_name": "dolt", "device_id": "dolt-cloud"},
    ]
    req = _req(dict(TICKET))
    assert (req["device_id"], req["tool_name"]) == ("grok-cloud", "grok_bot")
    assert mod._ticket_route_hops({**TICKET, "device_id": "chosen"}) == []
    assert mod._ticket_route_hops({"event_type": "self_maintenance"}) == []
    monkeypatch.delenv("MODSTORE_PARA_TICKET_ROUTE")
    req = _req(dict(TICKET))
    assert (req["device_id"], req["tool_name"]) == ("legacy-grok", "grok_bot")
    assert "_ticket_route" not in req["raw_input"]
    assert mod._normalize_tool_name("dolt-cloud") == "dolt"
    assert mod._device_eligible(
        {"status": "online", "tools": [{"toolName": "dolt", "status": "idle"}]}, "dolt"
    )


def test_ticket_route_hands_off_to_dolt_on_failure_timeout_or_cannot_handle(monkeypatch):
    _route_env(monkeypatch)
    for grok_result in (
        {"ok": False, "status": "para_task_failed", "error": "agent crashed"},
        {"ok": False, "status": "para_task_timeout", "error": "Para task t 未在 900s 内完成"},
        {"ok": False, "status": "blocked_no_online_para_device", "error": "offline"},
        {
            "ok": True,
            "status": "para_task_completed",
            "para_result": {"logs_tail": [{"content": "CANNOT_HANDLE: 需要人工"}]},
        },
    ):
        calls = _fake_once(
            monkeypatch, [grok_result, {"ok": True, "status": "para_task_completed"}]
        )
        out = mod._post_webhook(_req(dict(TICKET)))
        assert [c[:2] for c in calls] == [("grok-cloud", "grok_bot"), ("dolt-cloud", "dolt")]
        assert [c[2] for c in calls] == [
            ["grok_bot"],
            ["dolt"],
        ], "each hop is pinned to its own tool"
        assert out["ok"] is True and out["ticket_route"] == ["grok_bot", "dolt"]
        assert out["ticket_route_handoffs"][0]["status"] == grok_result["status"]


def test_ticket_route_stops_when_grok_succeeds_or_config_blocked(monkeypatch):
    _route_env(monkeypatch)
    calls = _fake_once(monkeypatch, [{"ok": True, "status": "para_task_completed"}])
    out = mod._post_webhook(_req(dict(TICKET)))
    assert len(calls) == 1 and out["ok"] and "ticket_route_handoffs" not in out
    calls = _fake_once(monkeypatch, [{"ok": False, "status": "blocked_missing_repo_url"}])
    assert mod._post_webhook(_req(dict(TICKET)))["status"] == "blocked_missing_repo_url"
    assert len(calls) == 1
    calls = _fake_once(monkeypatch, [{"ok": False, "status": "para_task_failed"}] * 2)
    out = mod._post_webhook(_req(dict(TICKET)))
    assert len(calls) == 2 and out["ok"] is False and out["status"] == "para_task_failed"


def test_ticket_route_does_not_touch_non_ticket_dispatch(monkeypatch):
    _route_env(monkeypatch)
    seen = []
    monkeypatch.setattr(mod, "_post_para_api", lambda req: seen.append(req) or {"ok": True})
    monkeypatch.setattr(
        mod, "_post_ticket_route", lambda *a: (_ for _ in ()).throw(AssertionError("route used"))
    )
    mod._post_webhook(_req({"event_type": "self_maintenance"}, "vibe-coding-maintainer"))
    mod._post_webhook(_req({**TICKET, "device_id": "chosen"}))
    monkeypatch.delenv("MODSTORE_PARA_TICKET_ROUTE")
    mod._post_webhook(_req(dict(TICKET)))
    assert [r["device_id"] for r in seen] == ["mac-local", "chosen", "legacy-grok"]
    assert mod._fallback_order_tools() == ["cursor", "claude_code", "trae"]
