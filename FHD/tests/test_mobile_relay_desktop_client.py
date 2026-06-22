from __future__ import annotations

import json
import time


def test_register_desktop_relay_reuses_cached_pairing_on_timeout(monkeypatch, tmp_path):
    from app.services import mobile_relay_desktop_client as relay

    config_file = tmp_path / "mobile_relay_desktop.json"
    config_file.write_text(
        json.dumps(
            {
                "relay_id": "relay-cached",
                "desktop_token": "desktop-secret",
                "pairing_code": "123456",
                "relay_base_url": "https://xiu-ci.com/fhd-api/",
                "registered_at": int(time.time()),
            }
        ),
        encoding="utf-8",
    )

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise relay.httpx.ConnectTimeout("handshake timeout")

    monkeypatch.setattr(relay, "_CONFIG_FILE", config_file)
    monkeypatch.setattr(relay.httpx, "Client", FailingClient)
    monkeypatch.setattr(relay, "start_desktop_relay_poller", lambda: True)

    payload = relay.register_desktop_relay(host="192.168.0.38", port=17500)

    assert payload is not None
    assert payload["relay_id"] == "relay-cached"
    assert payload["pairing_code"] == "123456"
    assert payload["qr_json"]["v"] == 3
    assert "desktop_token" not in payload


def test_execute_task_waits_for_real_codex_result(monkeypatch):
    from app.services import mobile_relay_desktop_client as relay

    class FakeCodexService:
        def invoke(self, **kwargs):
            return {
                "dispatch": {
                    "request_id": "req-1",
                    "task_id": "para-1",
                    "status": "accepted",
                    "accepted": True,
                },
                "assistant_message": {"role": "system", "body": "已派发"},
            }

        def list_messages(self, **kwargs):
            return [
                {
                    "role": "assistant",
                    "kind": "codex_result",
                    "dispatch_request_id": "req-1",
                    "task_id": "para-1",
                    "body": "真实 Codex 已完成",
                }
            ]

    monkeypatch.setattr(relay, "CodexSuperEmployeeService", FakeCodexService)
    result = relay._execute_task(
        {
            "task_id": "relay-task-1",
            "kind": "codex.invoke",
            "created_by_user_id": 7,
            "payload": {"message": "修复并测试"},
        }
    )

    assert result["_relay_status"] == "completed"
    assert result["codex"]["assistant_message"]["body"] == "真实 Codex 已完成"


def test_execute_task_marks_dispatch_unavailable_as_blocked(monkeypatch):
    from app.services import mobile_relay_desktop_client as relay

    class FakeCodexService:
        def invoke(self, **kwargs):
            return {
                "dispatch": {
                    "request_id": "req-2",
                    "status": "queued",
                    "accepted": False,
                    "reason": "para_no_online_codex_device",
                }
            }

    monkeypatch.setattr(relay, "CodexSuperEmployeeService", FakeCodexService)
    result = relay._execute_task(
        {
            "task_id": "relay-task-2",
            "kind": "codex.invoke",
            "created_by_user_id": 7,
            "payload": {"message": "打包 APK"},
        }
    )

    assert result["_relay_status"] == "blocked"
    assert result["error"] == "para_no_online_codex_device"
