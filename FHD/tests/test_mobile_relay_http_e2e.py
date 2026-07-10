from __future__ import annotations

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

    complete_response = client.post(
        f"/api/mobile/v1/relay/desktop/tasks/{task['task_id']}/complete",
        json={
            "relay_id": registered["relay_id"],
            "desktop_token": registered["desktop_token"],
            "status": "completed",
            "result": {
                "ok": True,
                "codex": {"assistant_message": {"body": "真实 Codex 已完成并回写"}},
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
    assert final_task["result"]["codex"]["assistant_message"]["body"] == "真实 Codex 已完成并回写"
    thread_after = client.get(f"/api/mobile/v1/relay/threads/{thread['thread_id']}").json()["data"][
        "thread"
    ]
    assert thread_after["cli_session_id"] == "codex-session-1"
    assert thread_after["branch"] == "super-employee/codex/thread-1"
    history = client.get(
        "/api/mobile/v1/relay/tasks", params={"thread_id": thread["thread_id"]}
    ).json()["data"]
    assert history["count"] == 1

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
