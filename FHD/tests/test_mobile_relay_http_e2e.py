from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_mobile_server_desktop_codex_relay_http_round_trip(monkeypatch, tmp_path):
    from app.fastapi_routes import mobile_api  # noqa: F401
    from app.fastapi_routes import mobile_api_extensions as ext
    from app.services import mobile_relay_service as relay

    engine = create_engine(f"sqlite:///{tmp_path / 'relay-http.db'}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_db():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(relay, "get_db", test_db)
    app = FastAPI()
    app.include_router(ext.extension_router, prefix="/api/mobile/v1")
    app.dependency_overrides[ext.get_mobile_user] = lambda: SimpleNamespace(
        id=7,
        username="admin",
        display_name="管理员",
        role="admin",
        is_active=True,
        account_id="account-7",
        tenant_id=41,
    )
    client = TestClient(app)

    registered_response = client.post(
        "/api/mobile/v1/relay/desktop/register",
        json={
            "label": "真实桌面执行端",
            "device_id": "desktop-1",
            "relay_base_url": "https://relay.example.test/api",
            "capabilities": {
                "codex": True,
                "codex_cli": True,
                "host": "192.168.1.8",
                "port": 17500,
            },
        },
    )
    assert registered_response.status_code == 200
    registered = registered_response.json()["data"]

    confirm_response = client.post(
        "/api/mobile/v1/relay/mobile/bind-account",
        json={"relay_id": registered["relay_id"]},
    )
    assert confirm_response.status_code == 200
    binding = confirm_response.json()["data"]
    assert binding["account_id"] == "account-7"
    assert binding["tenant_id"] == 41
    assert binding["session_token"]
    assert binding["relay_base_url"] == "https://relay.example.test/api/"
    assert binding["local_base_url"] == "http://192.168.1.8:17500"
    assert binding["paired_at"]

    thread_response = client.post(
        "/api/mobile/v1/relay/threads",
        json={
            "relay_id": registered["relay_id"],
            "employee_id": "codex-super-employee",
            "title": "移动端 Codex 多轮对话",
            "context": {"workspace_root": "/workspace/XCMAX"},
        },
    )
    assert thread_response.status_code == 200
    thread = thread_response.json()["data"]["thread"]
    assert thread["employee_id"] == "codex-super-employee"
    assert client.get("/api/mobile/v1/relay/threads").json()["data"]["count"] == 1

    create_response = client.post(
        "/api/mobile/v1/relay/tasks",
        json={
            "relay_id": registered["relay_id"],
            "kind": "codex.invoke",
            "thread_id": thread["thread_id"],
            "payload": {"message": "修复并运行测试"},
        },
    )
    assert create_response.status_code == 200
    task = create_response.json()["data"]["task"]
    assert task["status"] == "queued"
    assert task["thread_id"] == thread["thread_id"]
    assert task["payload"]["context"]["persistent_conversation"] is True

    poll_response = client.post(
        "/api/mobile/v1/relay/desktop/poll",
        json={
            "relay_id": registered["relay_id"],
            "desktop_token": registered["desktop_token"],
            "max_tasks": 5,
        },
    )
    assert poll_response.status_code == 200
    assert poll_response.json()["data"]["tasks"][0]["status"] == "running"

    large_trace = "DETAIL_ONLY_MARKER-" + ("x" * 600_000)
    full_assistant_body = "真实 Codex 已完成并回写" + ("答" * 5_000)
    complete_response = client.post(
        f"/api/mobile/v1/relay/desktop/tasks/{task['task_id']}/complete",
        json={
            "relay_id": registered["relay_id"],
            "desktop_token": registered["desktop_token"],
            "status": "completed",
            "result": {
                "ok": True,
                "elapsed_seconds": 3.5,
                "codex": {
                    "assistant_message": {"body": full_assistant_body},
                    "messages": [{"content": large_trace}],
                    "tool_calls": [{"arguments": large_trace}],
                    "dispatch": {"stdout": large_trace},
                },
                "session": {
                    "session_id": "codex-session-1",
                    "workspace_root": "/workspace/thread-1",
                    "branch": "super-employee/codex/thread-1",
                },
            },
        },
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["data"]["task"]["status"] == "completed"

    status_response = client.get(f"/api/mobile/v1/relay/tasks/{task['task_id']}")
    assert status_response.status_code == 200
    final_task = status_response.json()["data"]["task"]
    assert final_task["status"] == "completed"
    assert final_task["result"]["codex"]["assistant_message"]["body"] == full_assistant_body
    assert final_task["result"]["codex"]["messages"][0]["content"] == large_trace
    assert final_task["result"]["codex"]["tool_calls"][0]["arguments"] == large_trace
    assert final_task["result"]["codex"]["dispatch"]["stdout"] == large_trace
    thread_after = client.get(f"/api/mobile/v1/relay/threads/{thread['thread_id']}").json()["data"][
        "thread"
    ]
    assert thread_after["cli_session_id"] == "codex-session-1"
    assert thread_after["branch"] == "super-employee/codex/thread-1"
    history_response = client.get(
        "/api/mobile/v1/relay/tasks", params={"thread_id": thread["thread_id"]}
    )
    assert history_response.status_code == 200
    assert len(history_response.content) <= relay.MobileRelayService.task_list_max_response_bytes
    assert history_response.headers["X-XCAGI-Relay-List-Mode"] == "summary"
    assert "DETAIL_ONLY_MARKER" not in history_response.text
    history = history_response.json()["data"]
    assert history["count"] == 1
    assert history["limit"] == relay.MobileRelayService.task_list_default_limit
    assert history["summary_only"] is True
    history_task = history["items"][0]
    assert history_task["summary_only"] is True
    assert history_task["summary_truncated"] is True
    assert "messages" not in history_task["result"].get("codex", {})
    assert "tool_calls" not in history_task["result"].get("codex", {})
    assert "dispatch" not in history_task["result"].get("codex", {})
    assert len(history_task["result"]["codex"]["assistant_message"]["body"]) <= (
        relay.MobileRelayService.task_summary_result_max_chars
    )
    assert history_task["result"]["session"]["branch"] == "super-employee/codex/thread-1"

    legacy_page = client.get(
        "/api/mobile/v1/relay/tasks",
        params={"thread_id": thread["thread_id"], "limit": 300, "offset": 1},
    )
    assert legacy_page.status_code == 200
    legacy_data = legacy_page.json()["data"]
    assert legacy_data["requested_limit"] == 300
    assert legacy_data["limit"] == relay.MobileRelayService.task_list_max_page_limit
    assert legacy_data["offset"] == 1
    assert legacy_data["items"] == []

    cancel_create = client.post(
        "/api/mobile/v1/relay/tasks",
        json={
            "relay_id": registered["relay_id"],
            "kind": "codex.invoke",
            "thread_id": thread["thread_id"],
            "payload": {"message": "运行一个可取消的长任务"},
        },
    )
    cancel_task = cancel_create.json()["data"]["task"]
    claimed_cancel_task = client.post(
        "/api/mobile/v1/relay/desktop/poll",
        json={
            "relay_id": registered["relay_id"],
            "desktop_token": registered["desktop_token"],
            "max_tasks": 1,
        },
    ).json()["data"]["tasks"][0]
    assert claimed_cancel_task["task_id"] == cancel_task["task_id"]
    assert (
        client.post(f"/api/mobile/v1/relay/tasks/{cancel_task['task_id']}/cancel").json()["data"][
            "task"
        ]["status"]
        == "cancelled"
    )
    cancellation_poll = client.post(
        "/api/mobile/v1/relay/desktop/poll",
        json={
            "relay_id": registered["relay_id"],
            "desktop_token": registered["desktop_token"],
            "max_tasks": 0,
            "inflight_task_ids": [cancel_task["task_id"]],
        },
    )
    assert cancellation_poll.status_code == 200
    assert cancellation_poll.json()["data"]["tasks"] == []
    assert cancellation_poll.json()["data"]["cancelled_task_ids"] == [cancel_task["task_id"]]
    late_complete = client.post(
        f"/api/mobile/v1/relay/desktop/tasks/{cancel_task['task_id']}/complete",
        json={
            "relay_id": registered["relay_id"],
            "desktop_token": registered["desktop_token"],
            "status": "completed",
            "result": {"ok": True, "answer": "late"},
        },
    )
    assert late_complete.status_code == 200
    assert late_complete.json()["data"]["task"]["status"] == "cancelled"


def test_mobile_relay_summary_page_has_hard_utf8_response_budget():
    from app.fastapi_routes import mobile_api_extensions as ext
    from app.services.mobile_relay_service import MobileRelayService

    max_message = "中" * MobileRelayService.task_summary_message_max_chars
    max_result = "答" * MobileRelayService.task_summary_result_max_chars
    max_branch = "分" * MobileRelayService.task_summary_branch_max_chars
    items = [
        {
            "task_id": f"task-{index:04d}",
            "thread_id": f"thread-{index:04d}",
            "work_item_id": f"work-{index:04d}",
            "employee_id": "codex-super-employee",
            "kind": "codex.invoke",
            "status": "completed",
            "attempt_no": 1,
            "created_at": "2026-07-10T00:00:00+00:00",
            "updated_at": "2026-07-10T00:00:01+00:00",
            "payload": {"message": max_message},
            "result": {
                "codex": {"assistant_message": {"body": max_result}},
                "session": {"branch": max_branch},
            },
            "summary_only": True,
            "summary_truncated": True,
        }
        for index in range(MobileRelayService.task_list_max_page_limit)
    ]

    response = ext._mobile_relay_task_list_response(
        items,
        offset=0,
        page_limit=MobileRelayService.task_list_max_page_limit,
        requested_limit=MobileRelayService.task_list_max_requested_limit,
        has_more=False,
    )
    data = json.loads(response.body)["data"]

    assert len(response.body) <= MobileRelayService.task_list_max_response_bytes
    assert 0 < data["count"] < MobileRelayService.task_list_max_page_limit
    assert data["truncated_by_size"] is True
    assert data["has_more"] is True
    assert data["next_offset"] == data["count"]
