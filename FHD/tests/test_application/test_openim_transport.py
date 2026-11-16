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
