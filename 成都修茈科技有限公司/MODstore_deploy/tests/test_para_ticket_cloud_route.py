"""客服工单优先走云端执行器（Grok Bot）的路由测试。"""

import httpx
import pytest

from modstore_server import para_delegate_handler as mod

TICKET = {"event_type": "ops.intake.customer_ticket", "role": "scout"}


def test_github_employee_route_keeps_codex_inside_para_and_cannot_fallback(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_DEVICE_ID", "cloud-code-worker")
    monkeypatch.setenv("MODSTORE_PARA_WORKSPACE_ROOT", "/opt/production/workspace")
    req = _req({**TICKET, "github_workspace": {"issue_number": 123}})
    assert req["device_id"] == "cloud-code-worker" and req["tool_name"] == "codex"
    assert req["workspace_root"] == ""
    assert mod._tool_candidates(req) == ["codex"]
    monkeypatch.setattr(
        mod,
        "_fetch_devices",
        lambda *args: [
            {
                "id": "cloud-code-worker",
                "status": "online",
                "capabilities": {"platform": "linux", "server_bridge": True},
                "tools": [{"toolName": "codex", "status": "idle"}],
            }
        ],
    )
    _, devices, reason = mod._resolve_dispatch_devices(None, "", "", req)
    assert not devices and "GitHub 临时执行器" in reason
    monkeypatch.delenv("MODSTORE_PARA_GITHUB_DEVICE_ID")
    assert (
        _req({**TICKET, "github_workspace": {"issue_number": 123}})["device_id"]
        == "unconfigured-cloud-worker"
    )


CANNOT_HANDLE = {"logs_tail": [{"content": "CANNOT_HANDLE"}]}


def test_only_same_github_job_can_become_the_worker(monkeypatch):
    from datetime import UTC, datetime
    from modstore_server.para_github_runner import device_matches

    monkeypatch.setenv("MODSTORE_PARA_GITHUB_DEVICE_ID", "dedicated-worker")
    workspace = {"request_id": "same-request", "run_id": 123}
    device = {
        "id": "dedicated-worker",
        "status": "online",
        "lastSeen": datetime.now(UTC).isoformat(),
        "tools": [{"toolName": "codex", "status": "idle"}],
        "capabilities": {
            "github_actions": True,
            "github_request_id": "same-request",
            "github_run_id": "123",
            "github_run_attempt": "1",
        },
    }
    assert device_matches(device, workspace)
    for key, value in {
        "github_request_id": "other-request",
        "github_run_id": "999",
        "github_run_attempt": "2",
        "github_actions": False,
        "server_bridge": True,
    }.items():
        assert not device_matches(
            {**device, "capabilities": {**device["capabilities"], key: value}},
            workspace,
        )


def test_github_credentials_never_fall_back_to_mac_or_guest(monkeypatch):
    from modstore_server.maintenance_loop import para_auth
    from modstore_server import cred_vault

    monkeypatch.setenv("MODSTORE_PARA_GITHUB_API_BASE", "https://para.example.test")
    monkeypatch.setattr(
        cred_vault,
        "get_credential",
        lambda name, **kw: "old-mac" if name == "MODSTORE_PARA_AUTH_TOKEN" else "",
    )
    with pytest.raises(ValueError, match="专用服务身份"):
        mod._get_para_token(None, "https://para.example.test")
    with pytest.raises(ValueError, match="专用服务身份"):
        para_auth._guest_auth_headers("https://para.example.test")


def test_cloud_dispatch_remains_available_after_removing_legacy_mac_connection(
    monkeypatch,
):
    monkeypatch.delenv("MODSTORE_PARA_API_BASE", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_API_BASE", "https://para.example.test")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_AUTH_TOKEN", "test-only")
    monkeypatch.setenv("MODSTORE_PARA_GITHUB_DEVICE_ID", "github-worker")
    assert mod.para_delegate_ready_for_dispatch()
    monkeypatch.delenv("MODSTORE_PARA_GITHUB_AUTH_TOKEN")
    assert not mod.para_delegate_ready_for_dispatch()


def test_untrusted_github_workspace_does_not_dispatch(monkeypatch):
    monkeypatch.setattr(mod, "_post_webhook", lambda *a: pytest.fail("must not dispatch"))
    result = mod.dispatch_para_delegate(
        task="untrusted",
        employee_id="someone",
        input_data={"github_workspace": {"run_id": 123}},
    )
    assert result["status"] == "blocked_github_dispatch_identity" and not result["accepted"]


def _req(input_data=None, employee_id="change-request-auditor"):
    return mod._build_request(
        task="t",
        input_data=TICKET if input_data is None else input_data,
        employee_id=employee_id,
    )


def _result(status, **fields):
    return {"ok": False, "status": status, **fields}


REFUSAL = _result("blocked_no_online_para_device", accepted=False, queued=False)


def test_ticket_routes_to_grok_bot_only_when_configured(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac-local")
    monkeypatch.delenv("MODSTORE_PARA_TICKET_TOOL", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_TICKET_DEVICE_ID", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_TICKET_ROUTE")
    assert _req()["device_id"] == "mac-local"
    monkeypatch.setenv("MODSTORE_PARA_TICKET_DEVICE_ID", "grok-cloud")
    req = _req()
    assert (req["device_id"], req["tool_name"]) == ("grok-cloud", "grok_bot")
    for alias, tool in (("grok-bot", "grok_bot"), ("dolt-cloud", "dolt")):
        assert mod._normalize_tool_name(alias) == tool
        assert mod._device_eligible(
            {"status": "online", "tools": [{"toolName": tool, "status": "idle"}]}, tool
        )


ROUTE = "grok_bot@grok-cloud,dolt@dolt-cloud"


@pytest.fixture(autouse=True)
def _route_env(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "mac-local")
    monkeypatch.setenv("MODSTORE_PARA_TICKET_DEVICE_ID", "legacy-grok")
    monkeypatch.setenv("MODSTORE_PARA_TICKET_ROUTE", ROUTE)
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)


def _fake_once(monkeypatch, results):
    calls = []

    def fake(req):
        calls.append((req["device_id"], req["tool_name"], mod._tool_candidates(req)))
        return results[len(calls) - 1]

    monkeypatch.setattr(mod, "_post_para_api_once", fake)
    return calls


def test_ticket_route_parses_hops_and_keeps_legacy_when_unset(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_TICKET_ROUTE", ROUTE + ",bogus@x,dolt@,dolt@dolt-cloud")
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


def test_ticket_route_hands_off_only_before_submission_without_outbox(monkeypatch):
    calls = _fake_once(monkeypatch, [dict(REFUSAL), {"ok": True, "status": "para_task_completed"}])
    out = mod._post_webhook(_req())
    assert calls == [
        ("grok-cloud", "grok_bot", ["grok_bot"]),
        ("dolt-cloud", "dolt", ["dolt"]),
    ]
    assert out["ok"] and out["ticket_route_handoffs"][0]["status"] == REFUSAL["status"]


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        _result("para_task_timeout", accepted=True),
        _result("para_task_poll_failed", accepted=True),
        _result("para_api_failed_outboxed", queued=True),
        _result("para_api_rejected_outboxed", status_code=503),
        _result("para_api_missing_task_id", accepted=True),
        _result("para_task_failed", error="CANNOT_HANDLE"),
        _result("blocked_no_online_para_device", queued=True),
        _result("para_task_completed", ok=True, para_result=CANNOT_HANDLE),
    ],
)
def test_uncertain_or_accepted_hop_never_dispatches_second_executor(monkeypatch, result):
    calls = _fake_once(monkeypatch, [result])
    out = mod._post_webhook(_req())
    assert len(calls) == 1 and "ticket_route_handoffs" not in out
    if not out.get("ok"):
        assert out["ticket_route_requires_reconciliation"] is True


def test_ticket_route_stops_when_grok_succeeds_or_config_blocked(monkeypatch):
    for result in (
        _result("para_task_completed", ok=True),
        _result("blocked_missing_repo_url"),
        _result("para_task_failed"),
    ):
        calls = _fake_once(monkeypatch, [result])
        out = mod._post_webhook(_req())
        assert len(calls) == 1 and out["ok"] == result["ok"] and out["status"] == result["status"]
        assert "ticket_route_handoffs" not in out


def test_existing_task_cannot_be_handed_off_even_after_local_refusal(monkeypatch):
    calls = _fake_once(monkeypatch, [dict(REFUSAL)])
    out = mod._post_webhook(_req({**TICKET, "para_task_id": "already-running"}))
    assert len(calls) == 1 and out["ticket_route_requires_reconciliation"] is True


@pytest.mark.parametrize(
    "failure", ["no_device", "post_timeout", "post_503", "poll_timeout", "poll_503"]
)
def test_transport_failures_do_not_create_a_second_task(monkeypatch, failure):
    posts, outboxes = [], []

    def transport(request):
        phase = "post" if request.method == "POST" else "poll"
        if phase == "post":
            posts.append(request)
        if failure == phase + "_timeout":
            raise httpx.ReadTimeout("response lost", request=request)
        if failure == phase + "_503":
            return httpx.Response(503, json={"error": "unknown"})
        return httpx.Response(200, json={"task": {"id": "accepted-task"}, "subtask": {"id": "sub"}})

    client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: client(transport=httpx.MockTransport(transport), **kw),
    )
    devices = [] if failure == "no_device" else [{"id": "grok-cloud", "_selected_tool": "grok_bot"}]
    for name, value in {
        "_api_base": "https://para.invalid",
        "_allow_local_workdir": True,
        "_get_para_token": {"token": "test", "source": "test"},
        "_resolve_dispatch_devices": (1, devices, "offline"),
    }.items():
        monkeypatch.setattr(mod, name, lambda *a, value=value: value)
    monkeypatch.setattr(mod, "_write_outbox", lambda req: outboxes.append(req) or "test-outbox")
    out = mod._post_webhook(_req({**TICKET, "wait_for_para": True}))
    if failure == "no_device":
        assert posts == outboxes == [] and out["accepted"] is False and out["queued"] is False
    else:
        assert len(posts) == 1 and out["ticket_route_requires_reconciliation"] is True
        assert "ticket_route_handoffs" not in out
        if failure.startswith("poll_"):
            assert out["accepted"] is True and out["task_id"] == "accepted-task"
        if failure == "poll_timeout":
            assert outboxes[0]["para_task_id"] == "accepted-task"


def test_ticket_route_does_not_touch_non_ticket_dispatch(monkeypatch):
    seen = []
    monkeypatch.setattr(mod, "_post_para_api", lambda req: seen.append(req) or {"ok": True})
    monkeypatch.setattr(mod, "_post_ticket_route", lambda *a: pytest.fail("route used"))
    mod._post_webhook(_req({"event_type": "self_maintenance"}, "vibe-coding-maintainer"))
    mod._post_webhook(_req({**TICKET, "device_id": "chosen"}))
    monkeypatch.delenv("MODSTORE_PARA_TICKET_ROUTE")
    mod._post_webhook(_req(dict(TICKET)))
    assert [r["device_id"] for r in seen] == ["mac-local", "chosen", "legacy-grok"]
    assert mod._fallback_order_tools() == ["cursor", "claude_code", "trae"]
