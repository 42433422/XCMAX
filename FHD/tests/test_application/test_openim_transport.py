import json
from types import SimpleNamespace

import pytest

from app.infrastructure.im import openim
from app.infrastructure.tenant_scope import tenant_scope


class Remote:
    api = "http://openim.test"

    def __init__(self):
        self.sent = []
        self.visible = False
        self.uncertain = False

    def call(self, path, body):
        if path == "/msg/search_msg":
            return {
                "chatLogs": [{"chatLog": {"content": json.dumps(x["content"])}} for x in self.sent]
                if self.visible
                else None
            }
        if path == "/msg/send_msg":
            self.sent.append(body)
            if self.uncertain:
                raise openim.OpenIMError("timeout after acceptance")
            return {"clientMsgID": "ack"}
        raise AssertionError(path)


def setup_bridge(tmp_path, monkeypatch):
    remote = Remote()
    row = {
        "id": "message-1",
        "tenant_id": 1,
        "user_id": 7,
        "group_id": "group",
        "role": "user",
        "sender_id": "user",
        "sender_name": "我",
        "body": "任务",
    }
    group = {"user_id": 7, "id": "group", "members": []}
    repo = SimpleNamespace(
        root=tmp_path,
        read_messages=lambda: [row],
        user_groups=lambda uid: [group] if uid == 7 else [],
        find=lambda rows, gid: next((r for r in rows if r["id"] == gid), None),
    )
    monkeypatch.setattr(openim, "_client", lambda *args: remote)
    monkeypatch.setattr(openim.OpenIMGroups, "ensure_group", lambda self, group: "remote-group")
    return openim.OpenIMGroups(repo), remote, row


def test_namespace_separates_tenants_users_and_employee_ids(tmp_path, monkeypatch):
    with tenant_scope(1):
        first, _, _ = setup_bridge(tmp_path, monkeypatch)
        values = {first.identity(7, "u"), first.identity(8, "u"), first.identity(7, "e", "user")}
    with tenant_scope(2):
        second, _, _ = setup_bridge(tmp_path, monkeypatch)
        values.add(second.identity(7, "u"))
    assert len(values) == 4
    with tenant_scope(None), pytest.raises(openim.OpenIMError):
        openim.OpenIMGroups(None)


def test_acknowledged_publish_is_not_repeated_while_history_lags(tmp_path, monkeypatch):
    with tenant_scope(1):
        bridge, remote, row = setup_bridge(tmp_path, monkeypatch)
        bridge.sync(7, "group")
        bridge.sync(7, "group")
        assert len(remote.sent) == 1
        assert json.loads(remote.sent[0]["content"]["data"])["id"] == row["id"]
        with pytest.raises(ValueError, match="群不存在"):
            bridge.sync(8, "group")


def test_unknown_publish_is_reconciled_without_blind_replay(tmp_path, monkeypatch):
    with tenant_scope(1):
        bridge, remote, _ = setup_bridge(tmp_path, monkeypatch)
        remote.uncertain = True
        with pytest.raises(openim.OpenIMError):
            bridge.sync(7, "group")
        with pytest.raises(openim.OpenIMError, match="待核对"):
            bridge.sync(7, "group")
        remote.visible = True
        bridge.sync(7, "group")
        assert len(remote.sent) == 1


def test_foreign_audit_rows_are_never_published(tmp_path, monkeypatch):
    with tenant_scope(1):
        bridge, remote, row = setup_bridge(tmp_path, monkeypatch)
        row["tenant_id"] = 2
        bridge.sync(7, "group")
        assert not remote.sent


def test_transport_session_collects_finished_work_before_remote_sync(tmp_path, monkeypatch):
    from app.application.group_chat import message_transport
    from tests.test_application.test_ai_group_chat_service import make_service

    with tenant_scope(1):
        service = make_service(tmp_path)
        group = service.create_group(user_id=7, name="synthetic")
        collected = []

        def collect(*, user_id, group_id):
            collected.append((user_id, group_id))
            if not service._storage.read_messages():
                service._append_messages(
                    [
                        service._message_row(
                            user_id=user_id,
                            group_id=group_id,
                            role="ai",
                            sender_id="worker",
                            sender_name="worker",
                            sender_avatar="",
                            body="finished synthetic task",
                            kind="work_report",
                            status="completed",
                        )
                    ]
                )

        monkeypatch.setattr(service._progress, "sync_relay_progress_for_group", collect)
        monkeypatch.setattr(
            service._progress, "sync_super_employee_progress_for_group", lambda **kw: None
        )
        monkeypatch.setattr(message_transport, "enabled", lambda: False)

        class Transport:
            def __init__(self, repository):
                self.repository = repository

            def session(self, user_id, group_id):
                rows = self.repository.read_messages()
                assert rows[0]["status"] == "completed"
                return {"enabled": True, "groupID": group_id}

        monkeypatch.setattr(message_transport, "OpenIMGroups", Transport)
        assert message_transport.session(service, 7, group["id"])["enabled"]
        assert collected == [(7, group["id"])]
        message_transport.session(service, 7, group["id"])
        assert len(service._storage.read_messages()) == 1


def test_transport_route_uses_host_reconciliation_and_preserves_failure(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.group_chat import message_transport
    from app.fastapi_routes import im_ai_group_routes as routes
    from app.infrastructure.auth.dependencies import require_identified_user

    user = SimpleNamespace(id=7)
    calls = []
    service = SimpleNamespace(_storage=object())

    def get_messages(**kwargs):
        calls.append(kwargs)
        raise openim.OpenIMError("synthetic collection unavailable")

    service.get_messages = get_messages
    monkeypatch.setattr(
        routes,
        "_facade",
        lambda: SimpleNamespace(
            _ai_group_guard=lambda request: None,
            AiGroupChatService=lambda: service,
            _uid=lambda user: user.id,
        ),
    )
    monkeypatch.setattr(openim, "enabled", lambda: True)
    monkeypatch.setattr(
        message_transport,
        "OpenIMGroups",
        lambda _: pytest.fail("must not issue transport session after collection failure"),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_identified_user] = lambda: user
    with TestClient(app) as client:
        response = client.post("/api/admin/ai-groups/group/transport")
    assert calls == [{"user_id": 7, "group_id": "group"}]
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_transport_session_never_publishes_after_owner_rejection(monkeypatch):
    from app.application.group_chat import message_transport

    def denied(**kwargs):
        raise ValueError("群不存在")

    monkeypatch.setattr(
        message_transport,
        "OpenIMGroups",
        lambda _: pytest.fail("must not publish another owner's group"),
    )
    with pytest.raises(ValueError, match="群不存在"):
        message_transport.session(SimpleNamespace(get_messages=denied), 8, "group")
