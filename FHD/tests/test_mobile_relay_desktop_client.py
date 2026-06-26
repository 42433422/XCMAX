from __future__ import annotations

import json
import time


def test_register_desktop_relay_uses_stable_device_id(monkeypatch, tmp_path):
    from app.services import mobile_relay_desktop_client as relay
    from app.utils import device_identity

    posted: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "relay_id": "relay-1",
                    "desktop_token": "secret",
                    "pairing_code": "123456",
                    "relay_base_url": "https://xiu-ci.com/fhd-api/",
                }
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            posted.append(kwargs["json"])
            return FakeResponse()

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("XCAGI_DEVICE_ID", raising=False)
    monkeypatch.setattr(relay, "_CONFIG_FILE", tmp_path / "mobile_relay_desktop.json")
    monkeypatch.setattr(relay.httpx, "Client", FakeClient)
    monkeypatch.setattr(relay, "start_desktop_relay_poller", lambda: True)
    device_identity._cached = None

    relay.register_desktop_relay(host="192.168.0.38", port=17500)
    device_identity._cached = None
    relay.register_desktop_relay(host="192.168.0.38", port=17501)

    assert len(posted) == 2
    assert posted[0]["device_id"] == posted[1]["device_id"]
    assert posted[0]["device_id"] != "192.168.0.38:17500"
    assert posted[0]["capabilities"]["port"] == 17500
    assert posted[1]["capabilities"]["port"] == 17501


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
                    "body": "真实 Codex 已完成。改动文件：app/application/ai_group_chat_service.py；验证：pytest tests/test_application/test_ai_group_chat_service.py 通过。",
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
    assert "改动文件" in result["codex"]["assistant_message"]["body"]


def test_execute_task_marks_blocked_terminal_result_as_blocked(monkeypatch):
    from app.services import mobile_relay_desktop_client as relay

    class FakeCodexService:
        def invoke(self, **kwargs):
            return {
                "dispatch": {
                    "request_id": "req-blocked",
                    "task_id": "para-blocked",
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
                    "dispatch_request_id": "req-blocked",
                    "task_id": "para-blocked",
                    "body": "BLOCKED: 未完成；当前没有执行权限，未修改文件。",
                }
            ]

    monkeypatch.setattr(relay, "CodexSuperEmployeeService", FakeCodexService)
    result = relay._execute_task(
        {
            "task_id": "relay-task-blocked",
            "kind": "codex.invoke",
            "created_by_user_id": 7,
            "payload": {"message": "修复并测试移动端派工闭环"},
        }
    )

    assert result["_relay_status"] == "blocked"
    assert result["ok"] is False
    assert "BLOCKED" in result["error"]


def test_execute_task_routes_explicit_merge_message_to_git_op(monkeypatch):
    from app.services import mobile_relay_desktop_client as relay

    captured = {}

    def fake_handle_git_op(kind, payload):
        captured["kind"] = kind
        captured["payload"] = payload
        return {"ok": True, "_relay_status": "completed", "reply": "merged"}

    class ShouldNotRunCodex:
        def __init__(self):
            raise AssertionError("merge text should not call CLI")

    monkeypatch.setattr(relay, "handle_git_op", fake_handle_git_op)
    monkeypatch.setattr(relay, "CodexSuperEmployeeService", ShouldNotRunCodex)

    result = relay._execute_task(
        {
            "task_id": "relay-task-merge",
            "kind": "codex.invoke",
            "created_by_user_id": 7,
            "payload": {
                "message": (
                    "MERGE_BRANCH_TASK_SOURCE_mobile-group/task-123"
                    "_TARGET_CURRENT_feat/quality-to-9_CHECK_GIT_STATUS_FIRST"
                )
            },
        }
    )

    assert result["reply"] == "merged"
    assert captured["kind"] == "git.merge"
    assert captured["payload"]["branch"] == "mobile-group/task-123"
    assert captured["payload"]["target_branch"] == "feat/quality-to-9"


def test_execute_task_does_not_treat_generic_merge_word_as_git_op(monkeypatch):
    from app.services import mobile_relay_desktop_client as relay

    class FakeCodexService:
        def invoke(self, **kwargs):
            return {
                "dispatch": {"status": "completed", "accepted": True},
                "assistant_message": {
                    "body": (
                        "已合并首页和个人资料页的交互逻辑。"
                        "改动文件：mobile-android/app/src/main/java/com/xiuci/xcagi/mobile/navigation/ChatScreen.kt；"
                        "验证：./gradlew testEnterpriseDebugUnitTest 通过。"
                    )
                },
            }

    def fail_git_op(kind, payload):
        raise AssertionError("generic development wording should not call git op")

    monkeypatch.setattr(relay, "CodexSuperEmployeeService", FakeCodexService)
    monkeypatch.setattr(relay, "handle_git_op", fail_git_op)

    result = relay._execute_task(
        {
            "task_id": "relay-task-generic-merge",
            "kind": "codex.invoke",
            "created_by_user_id": 7,
            "payload": {
                "message": "合并首页和个人资料页的交互逻辑，修复测试",
                "context": {"branch": "mobile-group/task-123"},
            },
        }
    )

    assert result["_relay_status"] == "completed"
    assert "已合并首页" in result["codex"]["assistant_message"]["body"]


def test_execute_task_blocks_progress_body_without_evidence(monkeypatch):
    from app.services import mobile_relay_desktop_client as relay

    class FakeCodexService:
        def invoke(self, **kwargs):
            return {
                "dispatch": {
                    "request_id": "req-progress",
                    "task_id": "para-progress",
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
                    "dispatch_request_id": "req-progress",
                    "task_id": "para-progress",
                    "body": "正在搜索代码库中与群组任务讨论相关的实现；正在实现移动端展示。",
                }
            ]

    monkeypatch.setattr(relay, "CodexSuperEmployeeService", FakeCodexService)
    result = relay._execute_task(
        {
            "task_id": "relay-task-progress",
            "kind": "codex.invoke",
            "created_by_user_id": 7,
            "payload": {"message": "修复超级开发部任务讨论和验收假阳性"},
        }
    )

    assert result["_relay_status"] == "blocked"
    assert result["ok"] is False
    assert "正在搜索" in result["error"]


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
